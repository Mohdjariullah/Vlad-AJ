import discord
from discord.ext import commands
# from discord import app_commands  # unused
from discord.ui import View, Button, Modal, TextInput
import os
import logging
import asyncio
from datetime import datetime, timezone
# from datetime import timedelta  # unused
# from typing import Dict, Set  # unused
# import json  # unused
# from cogs.security_utils import safe_int_convert, security_check  # unused
# Calendly booking check (commented out – re-enable to use Calendly verification)
# from cogs.calendly import check_email_booked_specific_events

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

# UNVERIFIED_FILE = 'unverified_users.json'  # unused (was for legacy unverified list)

# Booking links (optional; used only if Calendly flow is re-enabled)
# GAMEPLAN_LINK = os.getenv('GAMEPLAN_LINK')
# MASTERMIND_LINK = os.getenv('MASTERMIND_LINK')


def _get_verified_role_ids():
    """Parse comma-separated VERIFIED_ROLE_IDS from env. Add more role IDs in .env to assign all on verify."""
    raw = os.getenv("VERIFIED_ROLE_IDS", "").strip()
    if not raw:
        return []
    ids = []
    for part in raw.replace(" ", "").split(","):
        part = part.strip()
        if part and part.isdigit():
            ids.append(int(part))
    return ids


def _get_verification_cooldown_seconds():
    """Cooldown for verification button (seconds). Env VERIFICATION_BUTTON_COOLDOWN_SECONDS, default 10."""
    try:
        raw = os.getenv("VERIFICATION_BUTTON_COOLDOWN_SECONDS", "10").strip()
        return max(1, int(raw)) if raw else 10
    except (ValueError, TypeError):
        return 10

# Unused (only referenced in commented Calendly block below)
# def get_env_role_id(var_name):
#     value = os.getenv(var_name)
#     try:
#         return int(value) if value is not None else None
#     except Exception:
#         return None

# def require_guild_admin(interaction: discord.Interaction) -> bool:
#     """Security check for admin commands"""
#     if not interaction.guild:
#         return False
#     if not isinstance(interaction.user, discord.Member):
#         return False
#     return interaction.user.guild_permissions.administrator

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
            "🔍 **Checking...**\n\n"
            f"📧 Email: `{encrypt_email(email)}`\n"
            "⏳ Please wait...",
            ephemeral=True
        )
        
        try:
            # --- Calendly booking check (commented out – uncomment to re-enable) ---
            # has_booked, event_type = check_email_booked_specific_events(email)
            # if has_booked and event_type:
            #     await self.verification_view.assign_role_based_on_booking(interaction, email, event_type)
            # else:
            #     embed = discord.Embed(
            #         title="📅 Book Your Onboarding Call Below",
            #         description=(
            #             "• **Free Onboarding Call** - For strategic planning\n"
            #             f"👉 [**FREE ONBOARDING CALL**]({MASTERMIND_LINK}) 👈\n"
            #             "After booking, return here and try again with the same email address."
            #         ),
            #         color=discord.Color.red()
            #     )
            #     embed.add_field(name="📧 Email Checked", value=f"`{encrypt_email(email)}`", inline=False)
            #     await interaction.followup.send(embed=embed, ephemeral=True)
            # --- End Calendly block ---
            # Assign roles from env VERIFIED_ROLE_IDS (add more IDs in .env to assign all)
            await self.verification_view.assign_roles_from_env(interaction, email)
        except Exception as e:
            logging.error(f"Error during verification for {email}: {e}")
            await interaction.followup.send(
                "❌ Error during verification. Please try again or contact support.",
                ephemeral=True
            )

class VerificationView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.ticket_cooldowns = {}  # user_id: timestamp

    @discord.ui.button(
        label="Book Your Onboarding Call",
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
        cooldown = _get_verification_cooldown_seconds()
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

    async def assign_roles_from_env(self, interaction: discord.Interaction, email: str):
        """Assign all roles from env VERIFIED_ROLE_IDS (comma-separated). Add more IDs in .env to assign more roles."""
        try:
            role_ids = _get_verified_role_ids()
            if not role_ids:
                await interaction.followup.send(
                    "❌ No roles configured. Set VERIFIED_ROLE_IDS in .env (comma-separated role IDs).",
                    ephemeral=True
                )
                return
            guild = interaction.guild
            roles_to_add = []
            for rid in role_ids:
                r = guild.get_role(rid)
                if r and r not in interaction.user.roles:
                    roles_to_add.append(r)
            if not roles_to_add:
                await interaction.followup.send(
                    "✅ You already have all verified roles!",
                    ephemeral=True
                )
                return
            for r in roles_to_add:
                await interaction.user.add_roles(r, reason="Verification – roles from VERIFIED_ROLE_IDS")
            role_names = [r.name for r in roles_to_add]
            unverified_role_id = int(os.getenv("UNVERIFIED_ROLE_ID", 0))
            if unverified_role_id and guild:
                unverified_role = guild.get_role(unverified_role_id)
                if unverified_role and unverified_role in interaction.user.roles:
                    await interaction.user.remove_roles(unverified_role, reason="Verification complete")
            embed = discord.Embed(
                title="🎉 Verification Complete!",
                description=(
                    "✅ Your access has been granted.\n\n"
                    f"**📧 Email:** `{encrypt_email(email)}`\n"
                    f"**🔑 Roles assigned:** {', '.join(role_names)}\n\n"
                    "Welcome to the server!"
                ),
                color=discord.Color.green()
            )
            embed.set_footer(text="Verification complete!")
            await interaction.followup.send(embed=embed, ephemeral=True)
            async def send_verified_dm():
                await asyncio.sleep(2)
                try:
                    dm_embed = discord.Embed(
                        title="🎉 You Are Verified!",
                        description=(
                            "Your access has been granted.\n\n"
                            f"**📧 Email:** `{encrypt_email(email)}`\n"
                            f"**🔑 Roles:** {', '.join(role_names)}\n\n"
                            "Welcome to the server!"
                        ),
                        color=discord.Color.green()
                    )
                    dm_embed.set_footer(text=f"Server: {getattr(guild, 'name', 'Unknown')}")
                    await interaction.user.send(embed=dm_embed)
                except Exception as e:
                    logging.warning(f"Could not send verification DM to {interaction.user.name}: {e}")
            asyncio.create_task(send_verified_dm())
            try:
                from cogs.member_management import MemberManagement
                member_cog = interaction.client.get_cog("MemberManagement")
                if member_cog and hasattr(member_cog, "pending_users") and interaction.user.id in member_cog.pending_users:
                    del member_cog.pending_users[interaction.user.id]
                    member_cog.save_pending_users()
            except Exception:
                pass
            await self.log_verification_event(
                interaction.guild,
                "🎫 Roles Assigned",
                f"{interaction.user.mention} received: {', '.join(role_names)}\n📧 {encrypt_email(email)}",
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
                f"Error for {interaction.user.mention}: {str(e)}",
                interaction.user,
                discord.Color.red()
            )

    # --- Calendly-based role assignment (commented out – use assign_roles_from_env + VERIFIED_ROLE_IDS) ---
    # async def assign_role_based_on_booking(self, interaction: discord.Interaction, email: str, event_type: str):
    #     """Assign the appropriate role based on the booking type (mastermind/gameplan)."""
    #     mastermind_role_id = get_env_role_id('MASTERMIND_ROLE_ID')
    #     gameplan_role_id = get_env_role_id('GAMEPLAN_ROLE_ID')
    #     role_to_assign = None
    #     role_name = ""
    #     if event_type == "mastermind" and mastermind_role_id:
    #         role_to_assign = interaction.guild.get_role(mastermind_role_id)
    #         role_name = "Mastermind"
    #     elif event_type == "gameplan" and gameplan_role_id:
    #         role_to_assign = interaction.guild.get_role(gameplan_role_id)
    #         role_name = "Game Plan"
    #     if not role_to_assign: ...
    #     await interaction.user.add_roles(role_to_assign, reason=f"Calendly booking verified - {event_type} call")
    #     ... (rest of success embed, DM, log)

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