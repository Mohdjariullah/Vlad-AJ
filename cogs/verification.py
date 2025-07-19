import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
import os
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Set
import json
from cogs.security_utils import safe_int_convert, security_check
from cogs.calendly import check_email_booked

BOOKING_LINK = os.getenv('CALENDLY_LINK')
UNVERIFIED_FILE = 'unverified_users.json'

# Calendly configuration - will use environment variables or fallback to defaults
CALENDLY_USER_UUID = os.getenv('CALENDLY_USER_UUID', '2ae4f947-d7f5-4610-93cf-fc67ff729342')
CALENDLY_TOKEN = os.getenv('CALENDLY_TOKEN', 'eyJraWQiOiIxY2UxZTEzNjE3ZGNmNzY2YjNjZWJjY2Y4ZGM1YmFmYThhNjVlNjg0MDIzZjdjMzJiZTgzNDliMjM4MDEzNWI0IiwidHlwIjoiUEFUIiwiYWxnIjoiRVMyNTYifQ.eyJpc3MiOiJodHRwczovL2F1dGguY2FsZW5kbHkuY29tIiwiaWF0IjoxNzUyNzY4MDI1LCJqdGkiOiIyY2Q4MjQ5OS0wNmI3LTRjM2QtYmI3MS01MDMxZWFkZTRiYjYiLCJ1c2VyX3V1aWQiOiIyYWU0Zjk0Ny1kN2Y1LTQ2MTAtOTNjZi1mYzY3ZmY3MjkzNDIifQ.-Ff2-NjGkvV6f9eSEbMT6qoRDIlactRzPFGa9r8ooW3AmYHZvMCxpSd4apwZodBx45HBMshq98Bt0f8tv6cVbQ')

def get_env_role_id(var_name):
    value = os.getenv(var_name)
    try:
        return int(value) if value is not None else None
    except Exception:
        return None

def require_guild_admin(interaction: discord.Interaction) -> bool:
    """Security check for admin commands"""
    if not interaction.guild:
        return False
    if not isinstance(interaction.user, discord.Member):
        return False
    return interaction.user.guild_permissions.administrator

# --- Email Collection Modal ---
class EmailCollectionModal(Modal, title="Please provide your email"):
    def __init__(self, verification_view):
        super().__init__()
        self.verification_view = verification_view
        
    email = TextInput(
        label="Email Address",
        placeholder="Enter your email address",
        required=True,
        min_length=5,
        max_length=100
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        email = self.email.value.strip()
        
        # Basic email validation
        if '@' not in email or '.' not in email:
            await interaction.response.send_message(
                "❌ Please enter a valid email address!",
                ephemeral=True
            )
            return
        
        # Show checking message
        await interaction.response.send_message(
            "🔍 **Checking your booking status...**\n\n"
            f"📧 Email: `{email}`\n"
            "⏳ Please wait while we verify your booking in our systems...",
            ephemeral=True
        )
        
        try:
            # Check Calendly for booking (will use env vars if not provided)
            has_booked = check_email_booked(email)
            
            if has_booked:
                # User has booked, directly give them roles
                await self.verification_view.direct_role_assignment(interaction, email)
            else:
                # User hasn't booked yet
                embed = discord.Embed(
                    title="📅 Booking Required",
                    description=(
                        "❌ **No booking found for this email address.**\n\n"
                        "You must book your onboarding call before gaining access.\n\n"
                        f"**Please book your call first:**\n"
                        f"👉 [**CLICK HERE TO BOOK YOUR CALL**]({BOOKING_LINK}) 👈\n\n"
                        "After booking, return here and try again with the same email address."
                    ),
                    color=discord.Color.red()
                )
                embed.add_field(
                    name="📧 Email Checked", 
                    value=f"`{email}`", 
                    inline=False
                )
                embed.set_footer(text="Book your call first, then try again!")
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                
        except Exception as e:
            logging.error(f"Error checking Calendly booking for {email}: {e}")
            await interaction.followup.send(
                "❌ Error checking booking status. Please try again or contact support.",
                ephemeral=True
            )

# --- Persistent Verification Ticket View ---
class PersistentVerifyView(View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.add_item(Button(label="Start Verification", style=discord.ButtonStyle.green, custom_id=f"verify_ticket_{user_id}"))

    @discord.ui.button(label="Start Verification", style=discord.ButtonStyle.green, custom_id="persistent_verify")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Only allow the ticket owner to use the button
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Only the ticket owner can use this button!", ephemeral=True)
            return
        # Check if user is still unverified
        try:
            with open(UNVERIFIED_FILE, 'r') as f:
                unverified = json.load(f)
        except Exception:
            unverified = {}
        if str(self.user_id) not in unverified:
            await interaction.response.send_message("❌ You are not pending verification or your ticket is no longer valid.", ephemeral=True)
            return
        # Proceed with verification logic (call your verification handler here)
        await interaction.response.send_message("✅ Verification process started! Please follow the instructions.", ephemeral=True)
        # You can add more logic here to open a modal, DM, or whatever your flow requires

class VerificationView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.ticket_cooldowns = {}  # user_id: timestamp
        self.pending_email = None

    @discord.ui.button(
        label="Start Verification",
        style=discord.ButtonStyle.green,
        custom_id="verify_button",
        emoji="🔒"
    )
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        import time
        if not interaction.guild:
            return await interaction.response.send_message(
                "❌ Verification can only be started in the server!",
                ephemeral=True
            )
        user_id = interaction.user.id
        now = time.time()
        cooldown = 10
        last_press = self.ticket_cooldowns.get(user_id, 0)
        if now - last_press < cooldown:
            return await interaction.response.send_message(
                f"⏳ Please wait {int(cooldown - (now - last_press))} seconds before trying again.",
                ephemeral=True
            )
        self.ticket_cooldowns[user_id] = now
        
        # Add user to verification tracking
        member_cog = getattr(getattr(interaction, 'client', None), 'get_cog', lambda name: None)('MemberManagement')
        if member_cog:
            member_cog.users_started_verification.add(user_id)
            logging.info(f"Added {interaction.user.name} to verification tracking from button click")
        
        # Show email collection modal immediately
        modal = EmailCollectionModal(self)
        await interaction.response.send_modal(modal)

    async def direct_role_assignment(self, interaction: discord.Interaction, email: str):
        """Directly assign roles if booking is confirmed"""
        try:
            member_cog = getattr(getattr(interaction, 'client', None), 'get_cog', lambda name: None)('MemberManagement')
            
            # Add user to verification tracking FIRST
            if member_cog:
                member_cog.users_started_verification.add(interaction.user.id)
                logging.info(f"Added {interaction.user.name} to verification tracking")
            
            # Check if user is already verified
            launchpad_role_id = get_env_role_id('LAUNCHPAD_ROLE_ID')
            member_role_id = get_env_role_id('MEMBER_ROLE_ID')
            subscription_roles = set(filter(None, [launchpad_role_id, member_role_id]))
            user_roles = {r.id for r in getattr(interaction.user, 'roles', [])}
            
            if user_roles & subscription_roles:
                await interaction.followup.send(
                    "✅ You already have subscription access! No verification needed.",
                    ephemeral=True
                )
                return

            # --- PATCH: If user is not tracked, trigger tracking logic and proceed ---
            if not member_cog or interaction.user.id not in getattr(member_cog, 'member_original_roles', {}):
                # Try to trigger the member join logic to track the user
                if member_cog:
                    try:
                        await member_cog.on_member_join(interaction.user)
                    except Exception as e:
                        logging.error(f"Error triggering on_member_join for {interaction.user}: {e}")
                # After triggering, check again
                if not member_cog or interaction.user.id not in getattr(member_cog, 'member_original_roles', {}):
                    await interaction.followup.send(
                        "⏳ Setting up your access. Please wait a few seconds and try again!",
                        ephemeral=True
                    )
                    return

            # Check if user has any subscription roles stored (VIP, etc.)
            stored_roles = member_cog.member_original_roles.get(interaction.user.id, [])
            has_subscription_roles = any(role_id in stored_roles for role_id in [launchpad_role_id, member_role_id] if role_id)
            
            # If user has subscription roles stored, restore them
            if has_subscription_roles and member_cog:
                await interaction.followup.send(
                    "⏳ **Booking confirmed!** Restoring your subscription access...",
                    ephemeral=True
                )
                
                restored_roles = await member_cog.restore_member_roles(interaction.user)
                member = None
                if interaction.guild and hasattr(interaction.guild, 'get_member'):
                    member = interaction.guild.get_member(interaction.user.id)
                subscription_role_ids = set([role.id for role in restored_roles]) if restored_roles else set()
                user_role_ids = {role.id for role in member.roles} if member else set()
                missing_roles = subscription_role_ids - user_role_ids
                
                if restored_roles and not missing_roles:
                    role_names = [role.name for role in restored_roles]
                    
                    # Success embed
                    embed = discord.Embed(
                        title="🎉 **Verification Complete!**",
                        description=(
                            "✅ **Your booking has been confirmed and your access has been granted!**\n\n"
                            f"**📧 Email:** `{email}`\n"
                            f"**🎯 Subscription Roles:** {', '.join(role_names)}\n\n"
                            "Welcome to the server! Enjoy your subscription access."
                        ),
                        color=discord.Color.green()
                    )
                    embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1370122090631532655/1386775344631119963/65fe71ca-e301-40a0-b69b-de77def4f57e.jpeg")
                    embed.set_footer(text="Your verification is complete!")
                    
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    
                    # Send DM notification
                    async def send_verified_dm():
                        await asyncio.sleep(2)
                        try:
                            dm_embed = discord.Embed(
                                title="🎉 You Are Verified!",
                                description=(
                                    "Your booking has been confirmed and your subscription access has been granted!\n\n"
                                    f"**📧 Email:** `{email}`\n"
                                    f"**🎯 Roles:** {', '.join(role_names)}\n\n"
                                    "Welcome to the server! Enjoy your stay."
                                ),
                                color=discord.Color.green()
                            )
                            dm_embed.set_footer(text=f"Server: {getattr(interaction.guild, 'name', 'Unknown')}")
                            await interaction.user.send(embed=dm_embed)
                        except Exception as e:
                            logging.warning(f"Could not send verification DM to {interaction.user.name}: {e}")
                    
                    asyncio.create_task(send_verified_dm())
                    
                elif restored_roles and missing_roles:
                    await interaction.followup.send(
                        f"⚠️ We tried to restore your roles, but some roles could not be added: {', '.join(str(rid) for rid in missing_roles)}. Please contact an admin for help",
                        ephemeral=True
                    )
                    await self.log_verification_event(
                        interaction.guild,
                        "❌ Direct Role Assignment Failed",
                        f"{interaction.user.mention} did not receive all subscription roles after booking confirmation. Manual intervention required.",
                        interaction.user,
                        discord.Color.red()
                    )
                else:
                    await interaction.followup.send(
                        "✅ Verification complete! No roles to restore.",
                        ephemeral=True
                    )
            
            # If user doesn't have subscription roles stored, give them member role
            else:
                await interaction.followup.send(
                    "⏳ **Email verified!** Granting you member access...",
                    ephemeral=True
                )
                
                # Give member role to users who join through Discord invite
                member_role = None
                if member_role_id and interaction.guild:
                    member_role = interaction.guild.get_role(member_role_id)
                
                if member_role and isinstance(interaction.user, discord.Member) and member_role not in interaction.user.roles:
                    try:
                        await interaction.user.add_roles(member_role, reason="Email verification completed - granting member access")
                        
                        # Remove unverified role if present
                        unverified_role_id = int(os.getenv('UNVERIFIED_ROLE_ID', 0))
                        if unverified_role_id and interaction.guild:
                            unverified_role = interaction.guild.get_role(unverified_role_id)
                            if unverified_role and unverified_role in interaction.user.roles:
                                await interaction.user.remove_roles(unverified_role, reason="Verification complete")
                        
                        # Success embed for member role
                        embed = discord.Embed(
                            title="🎉 **Welcome to the Community!**",
                            description=(
                                "✅ **Your email has been verified and you now have member access!**\n\n"
                                f"**📧 Email:** `{email}`\n"
                                f"**🎯 Role:** {member_role.name}\n\n"
                                "Welcome to the server! Enjoy your stay in our community."
                            ),
                            color=discord.Color.green()
                        )
                        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1370122090631532655/1386775344631119963/65fe71ca-e301-40a0-b69b-de77def4f57e.jpeg")
                        embed.set_footer(text="Your verification is complete!")
                        
                        await interaction.followup.send(embed=embed, ephemeral=True)
                        
                        # Send DM notification
                        async def send_member_dm():
                            await asyncio.sleep(2)
                            try:
                                dm_embed = discord.Embed(
                                    title="🎉 Welcome to the Community!",
                                    description=(
                                        "Your email has been verified and you now have member access!\n\n"
                                        f"**📧 Email:** `{email}`\n"
                                        f"**🎯 Role:** {member_role.name}\n\n"
                                        "Welcome to the server! Enjoy your stay."
                                    ),
                                    color=discord.Color.green()
                                )
                                dm_embed.set_footer(text=f"Server: {getattr(interaction.guild, 'name', 'Unknown')}")
                                await interaction.user.send(embed=dm_embed)
                            except Exception as e:
                                logging.warning(f"Could not send member DM to {interaction.user.name}: {e}")
                        
                        asyncio.create_task(send_member_dm())
                        
                        # Log the member role assignment
                        await self.log_verification_event(
                            interaction.guild,
                            "🎫 Member Role Assigned (Email Verified)",
                            f"{interaction.user.mention} received member role after email verification\n📧 Email: {email}\n✅ Role: {member_role.name}",
                            interaction.user,
                            discord.Color.green()
                        )
                        
                    except Exception as e:
                        logging.error(f"Error adding member role to {interaction.user.name}: {e}")
                        await interaction.followup.send(
                            "❌ Error assigning member role. Please contact support.",
                            ephemeral=True
                        )
                        await self.log_verification_event(
                            interaction.guild,
                            "❌ Member Role Assignment Failed",
                            f"Error assigning member role to {interaction.user.mention}: {str(e)}",
                            interaction.user,
                            discord.Color.red()
                        )
                else:
                    await interaction.followup.send(
                        "✅ You already have member access!",
                        ephemeral=True
                    )
            
            # Log the direct role assignment
            await self.log_verification_event(
                interaction.guild,
                "🎫 Direct Role Assignment (Email Verified)",
                f"{interaction.user.mention} received direct role assignment\n📧 Email: {email}\n✅ Email: Verified",
                interaction.user,
                discord.Color.green()
            )
            
        except Exception as e:
            logging.error(f"Error in direct role assignment for {interaction.user.name}: {e}")
            await interaction.followup.send(
                "❌ Error during role assignment. Please contact support.",
                ephemeral=True
            )
            await self.log_verification_event(
                interaction.guild,
                "❌ Direct Role Assignment Failed",
                f"Error during direct role assignment for {interaction.user.mention}: {str(e)}",
                interaction.user,
                discord.Color.red()
            )

    async def proceed_with_verification(self, interaction: discord.Interaction, email: str):
        """Proceed with verification after email is collected and booking is confirmed"""
        # Don't defer again since it's already deferred in the modal
        if interaction.response.is_done():
            # If interaction is already done, we need to use followup
            await self._create_verification_ticket(interaction, email, use_followup=True)
        else:
            await self._create_verification_ticket(interaction, email, use_followup=False)

    async def _create_verification_ticket(self, interaction: discord.Interaction, email: str, use_followup: bool = False):
        """Create verification ticket with proper interaction handling"""
        launchpad_role_id = get_env_role_id('LAUNCHPAD_ROLE_ID')
        member_role_id = get_env_role_id('MEMBER_ROLE_ID')
        subscription_roles = set(filter(None, [launchpad_role_id, member_role_id]))
        user_roles = {r.id for r in getattr(interaction.user, 'roles', [])}
        if user_roles & subscription_roles:
            message = "✅ You already have subscription access! No verification needed."
            if use_followup:
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return

        member_cog = getattr(getattr(interaction, 'client', None), 'get_cog', lambda name: None)('MemberManagement')
        
        # --- PATCH: If user is not tracked, trigger tracking logic and proceed ---
        if not member_cog or interaction.user.id not in getattr(member_cog, 'member_original_roles', {}):
            # Try to trigger the member join logic to track the user
            if member_cog:
                try:
                    await member_cog.on_member_join(interaction.user)
                except Exception as e:
                    logging.error(f"Error triggering on_member_join for {interaction.user}: {e}")
            # After triggering, check again
            if not member_cog or interaction.user.id not in getattr(member_cog, 'member_original_roles', {}):
                message = "⏳ Setting up your access. Please wait a few seconds and try again!"
                if use_followup:
                    await interaction.followup.send(message, ephemeral=True)
                else:
                    await interaction.response.send_message(message, ephemeral=True)
                return

        # --- Only allow one ticket per user ---
        if member_cog and interaction.user.id in member_cog.user_ticket_channels:
            channel_id = member_cog.user_ticket_channels[interaction.user.id]
            channel = interaction.guild.get_channel(channel_id) if interaction.guild else None
            if channel:
                message = f"🔗 You already have a verification ticket: {channel.mention}"
                if use_followup:
                    await interaction.followup.send(message, ephemeral=True)
                else:
                    await interaction.response.send_message(message, ephemeral=True)
                return
            else:
                member_cog.unregister_ticket(interaction.user.id)

        # FIXED: Better duplicate ticket prevention
        ticket_name = f"verify-{interaction.user.name.lower()}"
        existing_tickets = []
        # Find ALL existing tickets for this user
        if interaction.guild:
            for channel in interaction.guild.channels:
                if isinstance(channel, discord.TextChannel) and channel.name.startswith(f"verify-{interaction.user.name.lower()}"):
                    existing_tickets.append(channel)
        if existing_tickets:
            # Delete all existing tickets first
            for ticket in existing_tickets:
                try:
                    await ticket.delete(reason=f"Cleaning up duplicate tickets for {interaction.user.name}")
                    logging.info(f"Deleted existing ticket: {ticket.name}")
                except Exception as e:
                    logging.error(f"Failed to delete existing ticket {ticket.name}: {e}")
            # Small delay to ensure deletion completes
            await asyncio.sleep(1)  # Reduced from 2 to 1 second

        # --- Add user to started verification set ---
        if member_cog:
            member_cog.users_started_verification.add(interaction.user.id)

        # Create ticket channel with proper permissions from the start
        overwrites = {}
        if interaction.guild:
            overwrites[interaction.guild.default_role] = discord.PermissionOverwrite(
                view_channel=False,
                read_messages=False,
                send_messages=False
            )
            overwrites[interaction.user] = discord.PermissionOverwrite(
                view_channel=True,
                read_messages=True,
                read_message_history=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
                use_external_emojis=True
            )
            overwrites[interaction.guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                read_messages=True,
                read_message_history=True,
                send_messages=True,
                manage_messages=True,
                embed_links=True,
                attach_files=True,
                manage_channels=True
            )
            # Add permissions for administrators
            if interaction.guild:
                for role in interaction.guild.roles:
                    if role.permissions.administrator:
                        overwrites[role] = discord.PermissionOverwrite(
                            view_channel=True,
                            read_messages=True,
                            read_message_history=True,
                            send_messages=True,
                            manage_messages=True
                        )

        try:
            if not interaction.guild:
                message = "❌ Guild not found!"
                if use_followup:
                    await interaction.followup.send(message, ephemeral=True)
                else:
                    await interaction.response.send_message(message, ephemeral=True)
                return

            ticket_channel = await interaction.guild.create_text_channel(
                name=ticket_name,
                overwrites=overwrites,
                category=getattr(interaction.channel, 'category', None),
                topic=f"🎫 Verification ticket for {interaction.user.display_name} | User ID: {interaction.user.id} | Email: {email} | ✅ Booking Confirmed",
                reason=f"Verification ticket created for {interaction.user.name} (booking confirmed)"
            )
            logging.info(f"Created verification ticket: {ticket_channel.name} for {interaction.user.name}")
            # Register ticket in MemberManagement
            if member_cog:
                member_cog.register_ticket(interaction.user.id, ticket_channel.id)
        except Exception as e:
            message = f'❌ Failed to create ticket channel: {e}'
            if use_followup:
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            logging.error(f"Failed to create ticket channel for {interaction.user.name}: {e}")
            return

        # Get user's subscription info
        stored_role_ids = member_cog.member_original_roles[interaction.user.id]
        subscription_info = []
        for role_id in stored_role_ids:
            if launchpad_role_id and role_id == launchpad_role_id:
                subscription_info.append("🚀 VIP ($98/mo),($750/yr), or $1,000 for lifetime access)")
            elif member_role_id and role_id == member_role_id:
                subscription_info.append("👤 Member (Free)")

        # Send the welcome embed with booking confirmation
        expiry = datetime.now(timezone.utc) + timedelta(hours=24)
        exp_ts = int(expiry.timestamp())
        embed = discord.Embed(
            title="🎉 Welcome to Your Verification Process!",
            description=(
                "✅ **Your booking has been confirmed!**\n\n"
                "To complete your verification and gain access to your subscription, please follow these steps:\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "# 🟢 __STEP 1: CONFIRM YOUR BOOKING__\n"
                "\n"
                "Your call has been scheduled. Please click the **`I Have Booked`** button below to confirm.\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"**⏰ This ticket closes <t:{exp_ts}:R>**\n"
            ),
            color=discord.Color.green()
        )
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1370122090631532655/1386775344631119963/65fe71ca-e301-40a0-b69b-de77def4f57e.jpeg")
        embed.add_field(name="📅 Booking Status", value="**✅ Confirmed**", inline=True)
        embed.add_field(name="⏳ Expires", value=f"<t:{exp_ts}:f>", inline=True)
        embed.add_field(name="🎯 Subscription", value="\n".join(subscription_info), inline=False)
        embed.add_field(name="🆔 User ID", value=f"`{interaction.user.id}`", inline=False)
        embed.add_field(name="📧 Email", value=f"`{email}`", inline=False)
        embed.set_footer(text="Your booking is confirmed! Click the button below.")

        await ticket_channel.send(
            f"Welcome {interaction.user.mention}! Your booking has been confirmed. Let's complete your verification.",
            embed=embed,
            view=PersistentConfirmBookingView(interaction.user.id, ticket_channel.id)
        )

        # Log verification start with email and booking confirmation
        await self.log_verification_event(
            interaction.guild,
            "🎫 Subscription Verification Started (Booking Confirmed)",
            f"{interaction.user.mention} started verification for: {', '.join(subscription_info)}\n📧 Email: {email}\n✅ Booking: Confirmed",
            interaction.user,
            discord.Color.green()
        )

        # Auto-close after 24 hours with DM notification
        async def auto_close():
            await asyncio.sleep(86400)
            try:
                # Check if ticket still exists and user is still in server
                current_ticket = interaction.guild.get_channel(ticket_channel.id) if interaction.guild else None
                current_member = interaction.guild.get_member(interaction.user.id) if interaction.guild else None
                
                if not current_ticket:
                    logging.info(f"Ticket for {interaction.user.name} already deleted - skipping auto-close")
                    return
                
                # Send DM to user before closing ticket (only if they're still in server)
                if current_member:
                    try:
                        dm_embed = discord.Embed(
                            title="⏰ Verification Ticket Expired",
                            description=(
                                "Your verification ticket has been automatically closed after 24 hours.\n\n"
                                "**To continue your verification:**\n"
                                "1. Return to the verification channel\n"
                                "2. Click the 'Start Verification' button again\n"
                                "3. Complete your booking and verification process\n\n"
                                "We are waiting for you to return and complete your verification!"
                            ),
                            color=discord.Color.orange()
                        )
                        dm_embed.add_field(
                            name="📋 Your Subscription",
                            value="\n".join(subscription_info),
                            inline=False
                        )
                        dm_embed.add_field(
                            name="🔗 Quick Actions",
                            value=(
                                f"• [Book Your Call]({BOOKING_LINK})\n"
                                "• Return to server to create new ticket"
                            ),
                            inline=False
                        )
                        dm_embed.set_footer(text=f"Server: {getattr(interaction.guild, 'name', 'Unknown')}")
                        
                        await interaction.user.send(embed=dm_embed)
                        logging.info(f"Sent DM notification to {interaction.user.name} about expired ticket")
                        
                    except discord.Forbidden:
                        logging.warning(f"Could not send DM to {interaction.user.name} - DMs disabled")
                    except Exception as e:
                        logging.error(f"Error sending DM to {interaction.user.name}: {e}")

                # Delete the ticket channel
                try:
                    await current_ticket.delete(reason="Verification ticket expired after 24 hours")
                    logging.info(f"Auto-deleted expired ticket for {interaction.user.name}")
                    
                    # Unregister ticket
                    if member_cog:
                        member_cog.unregister_ticket(interaction.user.id)
                        
                except Exception as e:
                    logging.error(f'Failed to delete expired ticket channel: {e}')
                
                # Log the auto-close
                await self.log_verification_event(
                    interaction.guild,
                    "⏰ Verification Ticket Auto-Closed",
                    f"Verification ticket for {interaction.user.mention} auto-closed after 24 hours (DM sent: {'Yes' if current_member else 'No - user left'})",
                    interaction.user,
                    discord.Color.orange()
                )
                
            except Exception as e:
                logging.error(f"Error in auto-close for {interaction.user.name}: {e}")

        asyncio.create_task(auto_close())

        # Let them know
        message = f"✅ Your verification ticket is ready: {ticket_channel.mention}\n\n**Your booking has been confirmed!**"
        if use_followup:
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def log_verification_event(self, guild, title, description, user, color):
        """Log verification events to the logs channel"""
        if not guild:
            return
            
        logs_channel_id = os.getenv('LOGS_CHANNEL_ID')
        if logs_channel_id:
            logs_channel = guild.get_channel(int(logs_channel_id))
            if logs_channel:
                embed = discord.Embed(
                    title=title,
                    description=description,
                    color=color,
                    timestamp=datetime.now(timezone.utc)
                )
                embed.set_thumbnail(url=user.display_avatar.url)
                embed.add_field(name="User", value=f"{user.mention}\n({user.name})", inline=True)
                embed.add_field(name="User ID", value=user.id, inline=True)
                embed.add_field(name="Account Created", value=f"<t:{int(user.created_at.timestamp())}:R>", inline=True)
                embed.set_footer(text=f"Guild: {guild.name}")
                
                try:
                    await logs_channel.send(embed=embed)
                except Exception as e:
                    logging.error(f"Failed to send log message: {e}")

# --- Persistent Confirm Booking View ---
class PersistentConfirmBookingView(discord.ui.View):
    def __init__(self, authorized_user_id, ticket_channel_id):
        super().__init__(timeout=None)
        self.authorized_user_id = authorized_user_id
        self.ticket_channel_id = ticket_channel_id

    @discord.ui.button(label="I Have Booked", style=discord.ButtonStyle.green, emoji="✅", custom_id="persistent_confirm_booking")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # SECURITY: Check authorized user and guild context
        if not interaction.guild:
            return await interaction.response.send_message(
                "❌ This command can only be used in a server, not in DMs!",
                ephemeral=True
            )
        if interaction.user.id != self.authorized_user_id:
            return await interaction.response.send_message(
                "❌ Only the person who started this verification can use this button!",
                ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        try:
            member_cog = getattr(getattr(interaction, 'client', None), 'get_cog', lambda name: None)('MemberManagement')
            if member_cog:
                await interaction.followup.send(
                    "⏳ Please wait while we restore your subscription roles and double-check your access. This may take up to 2 minutes...",
                    ephemeral=True
                )
                restored_roles = await member_cog.restore_member_roles(interaction.user)
                member = None
                if interaction.guild and hasattr(interaction.guild, 'get_member'):
                    member = interaction.guild.get_member(interaction.user.id)
                subscription_role_ids = set([role.id for role in restored_roles]) if restored_roles else set()
                user_role_ids = {role.id for role in member.roles} if member else set()
                missing_roles = subscription_role_ids - user_role_ids
                if restored_roles and not missing_roles:
                    role_names = [role.name for role in restored_roles]
                    await interaction.followup.send(
                        f"✅ Verification complete! Your subscription roles have been restored: {', '.join(role_names)}\n\n"
                        "We will continue to monitor your access for a short period to ensure no other bot removes your roles.",
                        ephemeral=True
                    )
                    async def send_verified_dm():
                        await asyncio.sleep(20)
                        try:
                            dm_embed = discord.Embed(
                                title="🎉 You Are Verified!",
                                description="You now have full access to the server. Enjoy your stay and make the most of your subscription!",
                                color=discord.Color.green()
                            )
                            dm_embed.set_footer(text=f"Server: {getattr(interaction.guild, 'name', 'Unknown')}")
                            await interaction.user.send(embed=dm_embed)
                        except Exception as e:
                            logging.warning(f"Could not send verification DM to {interaction.user.name}: {e}")
                    asyncio.create_task(send_verified_dm())
                elif restored_roles and missing_roles:
                    await interaction.followup.send(
                        f"⚠️ We tried to restore your roles, but some roles could not be added: {', '.join(str(rid) for rid in missing_roles)}. Please contact an admin for help",
                        ephemeral=True
                    )
                    await self.log_verification_event(
                        interaction.guild,
                        "❌ Verification Role Restoration Failed",
                        f"{interaction.user.mention} did not receive all subscription roles after verification retries. Manual intervention required.",
                        interaction.user,
                        discord.Color.red(),
                        restored_roles
                    )
                else:
                    await interaction.followup.send("✅ Verification complete! No roles to restore.", ephemeral=True)
            channel_to_delete = getattr(interaction, 'channel', None)
            if channel_to_delete and hasattr(channel_to_delete, 'delete'):
                try:
                    await asyncio.sleep(5)
                    await channel_to_delete.delete()
                except Exception as e:
                    logging.error(f'Failed to delete ticket channel: {e}')
            logging.info(f"Closed verification ticket for {interaction.user.name}")
        except discord.Forbidden:
            logging.error(f"Permission error during role restoration for {interaction.user.name}")
            await interaction.followup.send("❌ Bot lacks required permissions to restore roles", ephemeral=True)
            await self.log_verification_event(
                interaction.guild,
                "❌ Verification Failed",
                f"Permission error during verification for {interaction.user.mention}",
                interaction.user,
                discord.Color.red()
            )
        except Exception as e:
            logging.error(f"Error in verification process for {interaction.user.name}: {e}")
            await interaction.followup.send("❌ Error during verification process", ephemeral=True)
            await self.log_verification_event(
                interaction.guild,
                "❌ Verification Failed",
                f"Error during verification for {interaction.user.mention}: {str(e)}",
                interaction.user,
                discord.Color.red()
            )

    async def log_verification_event(self, guild, title, description, user, color, restored_roles=None):
        """Log verification events to the logs channel"""
        logs_channel_id = os.getenv('LOGS_CHANNEL_ID')
        if logs_channel_id:
            logs_channel = guild.get_channel(int(logs_channel_id))
            if logs_channel:
                embed = discord.Embed(
                    title=title,
                    description=description,
                    color=color,
                    timestamp=datetime.now(timezone.utc)
                )
                embed.set_thumbnail(url=user.display_avatar.url)
                embed.add_field(name="User", value=f"{user.mention}\n({user.name})", inline=True)
                embed.add_field(name="User ID", value=user.id, inline=True)
                embed.add_field(name="Account Created", value=f"<t:{int(user.created_at.timestamp())}:R>", inline=True)
                
                if restored_roles:
                    roles_text = ", ".join([role.name for role in restored_roles]) if restored_roles else "None"
                    embed.add_field(name="Restored Subscription Roles", value=roles_text, inline=False)
                
                embed.set_footer(text=f"Guild: {guild.name}")
                
                try:
                    await logs_channel.send(embed=embed)
                except Exception as e:
                    logging.error(f"Failed to send log message: {e}")

class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Register persistent views for all open tickets
        try:
            with open(UNVERIFIED_FILE, 'r') as f:
                unverified = json.load(f)
        except Exception:
            unverified = {}
        for user_id in unverified:
            bot.add_view(PersistentConfirmBookingView(int(user_id), None))

async def setup(bot):
    await bot.add_cog(Verification(bot))