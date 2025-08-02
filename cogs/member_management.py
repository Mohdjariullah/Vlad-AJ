import discord
from discord.ext import commands
from discord import app_commands
import logging
import os
import asyncio
from typing import Dict, List, Set, Optional, Any
from datetime import datetime, timezone
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

class MemberManagement(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        SecureLogger.info("MemberManagement cog initialized with simplified DM-based verification")

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Called when the cog is ready."""
        SecureLogger.info("MemberManagement cog is ready!")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Handle new member joins - Send welcome DM with verification button."""
        try:
            SecureLogger.info(f"Member {member.name} joined server {member.guild.name}")
            
            # Send welcome DM with verification button
            try:
                embed = discord.Embed(
                    title="👋 Welcome to the Server!",
                    description=(
                        "To access your subscription and the community, please complete the verification process.\n\n"
                        "Click the button below to start verifying!\n\n"
                        "We're excited to have you with us!"
                    ),
                    color=0x5865F2
                )
                embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1370122090631532655/1386775344631119963/65fe71ca-e301-40a0-b69b-de77def4f57e.jpeg")
                embed.set_footer(text="Join our community today!")
                # Try to add a button to the welcome channel if possible
                welcome_channel_id = os.getenv('WELCOME_CHANNEL_ID')
                if welcome_channel_id:
                    welcome_channel = member.guild.get_channel(int(welcome_channel_id))
                    if welcome_channel:
                        view = discord.ui.View()
                        view.add_item(discord.ui.Button(
                            label="Go to Verification",
                            style=discord.ButtonStyle.link,
                            url=welcome_channel.jump_url
                        ))
                        await member.send(embed=embed, view=view)
                    else:
                        await member.send(embed=embed)
                else:
                    await member.send(embed=embed)
            except Exception as e:
                logging.warning(f"Could not send welcome DM to {member.name}: {e}")
            
            # Add unverified role if configured
            unverified_role = member.guild.get_role(UNVERIFIED_ROLE_ID)
            if unverified_role and unverified_role not in member.roles:
                try:
                    await member.add_roles(unverified_role, reason="User joined, pending verification")
                except Exception as e:
                    logging.warning(f"Could not add Unverified role to {member.name}: {e}")
            
            # Check for bypass roles
            if bypass_manager.has_bypass_role(member):
                bypass_role_names = bypass_manager.get_bypass_role_names(member.guild)
                await self.log_member_event(
                    member.guild,
                    "🎯 Verification Bypassed",
                    f"{member.mention} joined with bypass roles: {', '.join(bypass_role_names)} - no verification required",
                    member,
                    discord.Color.gold()
                )
                logging.info(f"User {member.name} bypassed verification with roles: {bypass_role_names}")
                return
            
            # Log the member join
            await self.log_member_event(
                member.guild,
                "👋 User Joined",
                f"{member.mention} joined the server. Welcome DM sent with verification button.",
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