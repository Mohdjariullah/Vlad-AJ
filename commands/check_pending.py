import discord
from discord import app_commands
from discord.ext import commands
import os
import logging
from datetime import datetime, timezone, timedelta
import json

OWNER_USER_IDS = {890323443252351046, 879714530769391686}
GUILD_ID = int(os.getenv('GUILD_ID', 0))

def is_authorized_guild_or_owner(interaction):
    if interaction.guild and interaction.guild.id == GUILD_ID:
        return True
    if interaction.user.id in OWNER_USER_IDS:
        return True
    return False

def load_pending_users():
    """Load pending users from file"""
    try:
        if os.path.exists('pending_users.json'):
            with open('pending_users.json', 'r') as f:
                data = json.load(f)
                pending_users = {}
                for user_id_str, timestamp_str in data.items():
                    user_id = int(user_id_str)
                    join_time = datetime.fromisoformat(timestamp_str)
                    pending_users[user_id] = join_time
                return pending_users
        return {}
    except Exception as e:
        logging.error(f"Error loading pending users: {e}")
        return {}

@app_commands.command(name="check_pending", description="Check how many users are pending for 1-hour free access")
@app_commands.default_permissions(administrator=True)
async def check_pending(interaction: discord.Interaction):
    """Check how many users are pending for 1-hour free access"""
    if not is_authorized_guild_or_owner(interaction):
        return await interaction.response.send_message(
            "❌ You are not authorized to use this command.", ephemeral=True
        )
    
    # SECURITY: Block DMs and check admin permissions
    if not interaction.guild:
        return await interaction.response.send_message(
            "❌ This command can only be used in a server, not in DMs!",
            ephemeral=True
        )
    if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "❌ You need Administrator permissions to use this command!",
            ephemeral=True
        )
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        pending_users = load_pending_users()
        current_time = datetime.now(timezone.utc)
        
        if not pending_users:
            embed = discord.Embed(
                title="📋 1-Hour Pending Users",
                description="No users are currently pending for 1-hour free access.",
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        # Calculate time remaining for each user (1 hour)
        users_with_time = []
        for user_id, join_time in pending_users.items():
            time_elapsed = current_time - join_time
            time_remaining = timedelta(minutes=60) - time_elapsed
            
            if time_remaining.total_seconds() > 0:
                hours_remaining = int(time_remaining.total_seconds() // 3600)
                minutes_remaining = int((time_remaining.total_seconds() % 3600) // 60)
                time_str = f"{hours_remaining}h {minutes_remaining}m"
            else:
                time_str = "Ready for access"
            
            users_with_time.append((user_id, join_time, time_str, time_remaining))
        
        # Sort by time remaining (soonest first)
        users_with_time.sort(key=lambda x: x[3])
        
        # Create embed
        embed = discord.Embed(
            title="📋 1-Hour Pending Users",
            description=f"**Total pending users:** {len(pending_users)}",
            color=discord.Color.blue()
        )
        
        # Show first 10 users with details
        for i, (user_id, join_time, time_str, time_remaining) in enumerate(users_with_time[:10]):
            member = interaction.guild.get_member(user_id)
            member_name = member.name if member else f"User {user_id}"
            member_mention = member.mention if member else f"<@{user_id}>"
            
            embed.add_field(
                name=f"{i+1}. {member_name}",
                value=f"**User:** {member_mention}\n**Joined:** <t:{int(join_time.timestamp())}:R>\n**Time remaining:** {time_str}",
                inline=False
            )
        
        if len(users_with_time) > 10:
            embed.add_field(
                name="...",
                value=f"And {len(users_with_time) - 10} more users",
                inline=False
            )
        
        # Add summary
        ready_users = [u for u in users_with_time if u[3].total_seconds() <= 0]
        if ready_users:
            embed.add_field(
                name="✅ Ready for Access",
                value=f"{len(ready_users)} users are ready to receive access",
                inline=False
            )
        
        embed.set_footer(text=f"Checked at {current_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
    except Exception as e:
        logging.error(f"Error checking pending users: {e}")
        await interaction.followup.send(f"❌ Error checking pending users: {e}", ephemeral=True)

async def setup(bot: commands.Bot):
    bot.tree.add_command(check_pending) 