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
from cogs.calendly import check_email_booked_specific_events

def encrypt_email(email: str) -> str:
    """Encrypt email for privacy in DMs - shows first 2 and last 2 characters"""
    if not email or '@' not in email:
        return "***@***"
    
    parts = email.split('@')
    if len(parts) != 2:
        return "***@***"
    
    username, domain = parts
    
    # Show first 2 and last 2 characters of username
    if len(username) <= 4:
        encrypted_username = "*" * len(username)
    else:
        encrypted_username = username[:2] + "*" * (len(username) - 4) + username[-2:]
    
    # Show first 2 and last 2 characters of domain
    if len(domain) <= 4:
        encrypted_domain = "*" * len(domain)
    else:
        encrypted_domain = domain[:2] + "*" * (len(domain) - 4) + domain[-2:]
    
    return f"{encrypted_username}@{encrypted_domain}"

UNVERIFIED_FILE = 'unverified_users.json'

# Get booking links from environment
GAMEPLAN_LINK = os.getenv('GAMEPLAN_LINK')
MASTERMIND_LINK = os.getenv('MASTERMIND_LINK')

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
            # Check Calendly for specific event bookings (ROBUST METHOD)
            has_booked, event_type = check_email_booked_specific_events(email)
            
            if has_booked and event_type:
                # User has booked a specific event, assign the corresponding role
                await self.verification_view.assign_role_based_on_booking(interaction, email, event_type)
            else:
                # User hasn't booked any of the required events
                embed = discord.Embed(
                    title="📅 Booking Required",
                    description=(
                        "❌ **No booking found for this email address.**\n\n"
                        "You must book one of our calls before gaining access:\n\n"
                        "**📅 Available Calls:**\n"
                        "• **Mastermind Call** - For strategic planning\n"
                        "• **Game Plan Call** - For tactical guidance\n\n"
                        "**Please book your call first:**\n"
                        f"👉 [**MASTERMIND CALL**]({MASTERMIND_LINK}) 👈\n"
                        f"👉 [**GAME PLAN CALL**]({GAMEPLAN_LINK}) 👈\n\n"
                        "After booking, return here and try again with the same email address."
                    ),
                    color=discord.Color.red()
                )
                embed.add_field(
                    name="📧 Email Checked", 
                    value=f"`{encrypt_email(email)}`", 
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

class VerificationView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.ticket_cooldowns = {}  # user_id: timestamp

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
        
        # Show email collection modal immediately
        modal = EmailCollectionModal(self)
        await interaction.response.send_modal(modal)

    async def assign_role_based_on_booking(self, interaction: discord.Interaction, email: str, event_type: str):
        """Assign the appropriate role based on the booking type"""
        try:
            # Get role IDs from environment variables
            mastermind_role_id = get_env_role_id('MASTERMIND_ROLE_ID')
            gameplan_role_id = get_env_role_id('GAMEPLAN_ROLE_ID')
            
            role_to_assign = None
            role_name = ""
            
            if event_type == "mastermind" and mastermind_role_id:
                role_to_assign = interaction.guild.get_role(mastermind_role_id)
                role_name = "Mastermind"
            elif event_type == "gameplan" and gameplan_role_id:
                role_to_assign = interaction.guild.get_role(gameplan_role_id)
                role_name = "Game Plan"
            
            if not role_to_assign:
                await interaction.followup.send(
                    "❌ Error: Role not found. Please contact an administrator.",
                    ephemeral=True
                )
                return

            # Check if user already has the role
            if role_to_assign in interaction.user.roles:
                await interaction.followup.send(
                    f"✅ You already have the {role_name} role!",
                    ephemeral=True
                )
                return
            
            # Assign the role
            await interaction.user.add_roles(role_to_assign, reason=f"Calendly booking verified - {event_type} call")
            
            # Remove unverified role if present
            unverified_role_id = int(os.getenv('UNVERIFIED_ROLE_ID', 0))
            if unverified_role_id and interaction.guild:
                unverified_role = interaction.guild.get_role(unverified_role_id)
                if unverified_role and unverified_role in interaction.user.roles:
                    await interaction.user.remove_roles(unverified_role, reason="Verification complete")
                    
                    # Success embed
                    embed = discord.Embed(
                        title="🎉 **Verification Complete!**",
                        description=(
                            "✅ **Your booking has been confirmed and your access has been granted!**\n\n"
                            f"**📧 Email:** `{encrypt_email(email)}`\n"
                    f"**🎯 Call Type:** {role_name} Call\n"
                    f"**🔑 Role Assigned:** {role_to_assign.name}\n\n"
                    "Welcome to the server! Enjoy your access."
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
                            "Your booking has been confirmed and your access has been granted!\n\n"
                                    f"**📧 Email:** `{encrypt_email(email)}`\n"
                            f"**🎯 Call Type:** {role_name} Call\n"
                            f"**🔑 Role:** {role_to_assign.name}\n\n"
                                    "Welcome to the server! Enjoy your stay."
                                ),
                                color=discord.Color.green()
                            )
                            dm_embed.set_footer(text=f"Server: {getattr(interaction.guild, 'name', 'Unknown')}")
                            await interaction.user.send(embed=dm_embed)
                        except Exception as e:
                            logging.warning(f"Could not send verification DM to {interaction.user.name}: {e}")
                    
                    asyncio.create_task(send_verified_dm())
                    
            # Log the verification event
            await self.log_verification_event(
                interaction.guild,
                "🎫 Role Assignment (Calendly Verified)",
                f"{interaction.user.mention} received {role_to_assign.name} role after {role_name} call verification\n📧 Email: {email}\n✅ Event Type: {event_type}",
                interaction.user,
                discord.Color.green()
            )
            
        except Exception as e:
            logging.error(f"Error in role assignment for {interaction.user.name}: {e}")
            await interaction.followup.send(
                "❌ Error during role assignment. Please contact support.",
                ephemeral=True
            )
            await self.log_verification_event(
                interaction.guild,
                "❌ Role Assignment Failed",
                f"Error during role assignment for {interaction.user.mention}: {str(e)}",
                interaction.user,
                discord.Color.red()
            )

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

class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

async def setup(bot):
    await bot.add_cog(Verification(bot))