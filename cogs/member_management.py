import discord
from discord.ext import commands
from discord import app_commands
import logging
import os
import asyncio
from typing import Dict, List, Set, Optional, Any
from datetime import datetime, timezone, timedelta
from .security_utils import (
    security_check, log_admin_action, safe_int_convert, 
    validate_input, check_rate_limit, safe_audit_log_check,
    SecureLogger, sanitize_log_message
)
from .bypass_manager import bypass_manager
import json
import io
import json as pyjson

UNVERIFIED_ROLE_ID = int(os.getenv('UNVERIFIED_ROLE_ID', 0))
WELCOME_CHANNEL_ID = int(os.getenv('WELCOME_CHANNEL_ID', 0))

def get_env_role_id(var_name: str) -> int:
    env_value = os.getenv(var_name)
    if env_value is None:
        raise ValueError(f"Environment variable '{var_name}' is not set")
    val = safe_int_convert(env_value, min_val=1, max_val=2**63-1)
    if val is None:
        raise ValueError(f"Environment variable '{var_name}' is not a valid int")
    return val


def _parse_role_id(env_var: str, default: int = 0) -> int:
    """Parse role ID from env: strip whitespace, empty/invalid -> default. Safe for optional env vars."""
    raw = os.getenv(env_var)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default

class MemberManagement(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pending_users: Dict[int, datetime] = {}  # user_id: join_time
        self.load_pending_users()
        SecureLogger.info("MemberManagement cog initialized (Vito: 1-hour auto-access, no verification)")

    def load_pending_users(self):
        """Load pending users from file"""
        try:
            if os.path.exists('pending_users.json'):
                with open('pending_users.json', 'r') as f:
                    data = json.load(f)
                    for user_id_str, timestamp_str in data.items():
                        user_id = int(user_id_str)
                        join_time = datetime.fromisoformat(timestamp_str)
                        self.pending_users[user_id] = join_time
                SecureLogger.info(f"Loaded {len(self.pending_users)} pending users")
        except Exception as e:
            SecureLogger.error(f"Error loading pending users: {e}")

    def save_pending_users(self):
        """Save pending users to file"""
        try:
            data = {}
            for user_id, join_time in self.pending_users.items():
                data[str(user_id)] = join_time.isoformat()
            with open('pending_users.json', 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            SecureLogger.error(f"Error saving pending users: {e}")

    async def check_1_hour_access(self):
        """Check for users who should get access after 1 hour"""
        current_time = datetime.now(timezone.utc)
        users_to_grant_access = []
        
        for user_id, join_time in self.pending_users.items():
            if current_time - join_time >= timedelta(minutes=60):
                users_to_grant_access.append(user_id)
        
        for user_id in users_to_grant_access:
            await self.grant_1_hour_access(user_id)
            del self.pending_users[user_id]
        
        if users_to_grant_access:
            self.save_pending_users()

    async def grant_1_hour_access(self, user_id: int):
        """Grant free member access to a user after 1 hour"""
        try:
            guild_id = int(os.getenv('GUILD_ID', 0))
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return
            
            member = guild.get_member(user_id)
            if not member:
                return
            
            # Free members role (MEMBER_ROLE_ID)
            member_role_id = int(os.getenv('MEMBER_ROLE_ID', 0))
            if member_role_id:
                member_role = guild.get_role(member_role_id)
                if member_role and member_role not in member.roles:
                    await member.add_roles(member_role, reason="1-hour auto-access granted")
                    
                    unverified_role_id = int(os.getenv('UNVERIFIED_ROLE_ID', 0))
                    if unverified_role_id:
                        unverified_role = guild.get_role(unverified_role_id)
                        if unverified_role and unverified_role in member.roles:
                            await member.remove_roles(unverified_role, reason="1-hour auto-access granted")
                    
                    await self.log_member_event(
                        guild,
                        "⏰ 1-Hour Free Access",
                        f"{member.mention} was granted free member access after 1 hour",
                        member,
                        discord.Color.orange()
                    )
                    SecureLogger.info(f"Granted 1-hour free access to {member.name}")
            
        except Exception as e:
            SecureLogger.error(f"Error granting 1-hour access to user {user_id}: {e}")

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Called when the cog is ready."""
        SecureLogger.info("MemberManagement cog is ready!")
        # Start the 1-hour check task
        self.bot.loop.create_task(self.periodic_1_hour_check())

    async def periodic_1_hour_check(self):
        """Periodically check for users who should get 1-hour free access"""
        while True:
            try:
                await self.check_1_hour_access()
                await asyncio.sleep(60)  # Check every minute
            except Exception as e:
                SecureLogger.error(f"Error in periodic 1-hour check: {e}")
                await asyncio.sleep(60)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Handle new member joins: add unverified role first, then welcome DM with Go to Server button (no booking link in DM)."""
        try:
            SecureLogger.info(f"Member {member.name} joined server {member.guild.name}")

            # Ensure we have a full member object (avoids cache issues)
            try:
                member = await member.fetch()
            except Exception:
                pass  # use existing member if fetch fails

            unverified_role_id = _parse_role_id("UNVERIFIED_ROLE_ID", 0)
            if not unverified_role_id:
                logging.warning("UNVERIFIED_ROLE_ID is not set or invalid in .env — new members will not get the unverified role")
            else:
                unverified_role = member.guild.get_role(unverified_role_id)
                if not unverified_role:
                    logging.warning(
                        "Unverified role not found in guild (id=%s). Check UNVERIFIED_ROLE_ID in .env and that the role exists.",
                        unverified_role_id,
                    )
                elif unverified_role in member.roles:
                    pass  # already has it
                else:
                    try:
                        await member.add_roles(unverified_role, reason="User joined, pending verification")
                        logging.info("Added Unverified role to %s (id=%s)", member.name, member.id)
                    except discord.Forbidden:
                        logging.warning(
                            "Cannot add Unverified role to %s: bot lacks permission or bot role is below Unverified in Server Settings → Roles. Move the bot role above Unverified.",
                            member.name,
                        )
                    except Exception as e:
                        logging.warning("Could not add Unverified role to %s: %s", member.name, e)

            try:
                embed = discord.Embed(
                    title="👋 Welcome to Vito",
                    description=(
                        "You made it this far.\n"
                        "Access isn't automatic and that's on purpose.\n\n"
                        "This server is locked until you verify.\n"
                        "One step. Thats it\n\n"
                        "Hit verify.\n\n"
                        "Welcome to Vito."
                    ),
                    color=0xF00000
                )
                embed.set_footer(text="Welcome to Vito")
                welcome_channel_id = os.getenv("WELCOME_CHANNEL_ID")
                if welcome_channel_id:
                    welcome_channel = member.guild.get_channel(int(welcome_channel_id))
                    if welcome_channel:
                        view = discord.ui.View()
                        view.add_item(discord.ui.Button(
                            label="Go to Server",
                            style=discord.ButtonStyle.link,
                            url=welcome_channel.jump_url,
                        ))
                        await member.send(embed=embed, view=view)
                    else:
                        await member.send(embed=embed)
                else:
                    await member.send(embed=embed)
            except Exception as e:
                logging.warning(f"Could not send welcome DM to {member.name}: {e}")

            if bypass_manager.has_bypass_role(member):
                bypass_role_names = bypass_manager.get_bypass_role_names(member.guild)
                await self.log_member_event(
                    member.guild,
                    "🎯 Bypass",
                    f"{member.mention} joined with bypass roles: {', '.join(bypass_role_names)}",
                    member,
                    discord.Color.gold()
                )
                logging.info(f"User {member.name} has bypass roles: {bypass_role_names}")
                return
            
            self.pending_users[member.id] = datetime.now(timezone.utc)
            self.save_pending_users()
            
            await self.log_member_event(
                member.guild,
                "👋 User Joined",
                f"{member.mention} joined. Welcome DM sent. Added to 1-hour timer for free access.",
                member,
                discord.Color.blue()
            )
            
        except Exception as e:
            logging.error(f"Error in on_member_join for {member.name}: {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Handle member leaves - log the event."""
        try:
            guild_id = member.guild.id if getattr(member, 'guild', None) is not None else 'unknown'
            logging.info(f"[MemberManagement] Member {member.name} ({member.id}) left server {guild_id}")
            
            if member.guild:
                await self.log_member_event(
                    member.guild,
                    "👋 User Left",
                    f"{member.mention} left the server.",
                    member,
                    discord.Color.orange(),
                    None
                )
        except Exception as e:
            logging.error(f"Error in on_member_remove for {member.name}: {e}")

    async def log_member_event(self, guild, title, description, user, color, roles=None):
        """Log member events to the logs channel"""
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
                
                if roles:
                    roles_text = ", ".join([role.name for role in roles]) if roles else "None"
                    embed.add_field(name="Roles", value=roles_text, inline=False)
                
                embed.set_footer(text=f"Guild: {guild.name}")
                
                try:
                    await logs_channel.send(embed=embed)
                except Exception as e:
                    logging.error(f"Failed to send log message: {e}")

async def setup(bot):
    await bot.add_cog(MemberManagement(bot))