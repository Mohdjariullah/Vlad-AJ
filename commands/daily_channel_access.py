import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set
import asyncio
import pytz

# File to store channel schedules
SCHEDULE_FILE = 'daily_channel_schedules.json'

def load_schedules() -> Dict:
    """Load channel schedules from file"""
    try:
        with open(SCHEDULE_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_schedules(schedules: Dict) -> None:
    """Save channel schedules to file"""
    with open(SCHEDULE_FILE, 'w') as f:
        json.dump(schedules, f, indent=2)

class DailyChannelAccess(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.schedules = load_schedules()
        self.channel_schedules: Dict[str, Dict] = {}
        
        # Convert string keys to int for channel IDs
        for channel_id_str, schedule in self.schedules.items():
            self.channel_schedules[int(channel_id_str)] = schedule
        
        # Start the background task
        self.update_channel_permissions.start()
        logging.info("DailyChannelAccess cog initialized")

    def cog_unload(self):
        """Clean up when cog is unloaded"""
        self.update_channel_permissions.cancel()

    @tasks.loop(minutes=1)  # Check every minute
    async def update_channel_permissions(self):
        """Background task to update channel permissions based on schedule"""
        current_time = datetime.now(timezone.utc)
        
        for channel_id, schedule in self.channel_schedules.items():
            try:
                # Find the channel
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    continue
                
                guild = channel.guild
                if not guild:
                    continue
                
                # Get the role ID from schedule
                role_id = schedule.get('role_id')
                if not role_id:
                    continue
                
                role = guild.get_role(role_id)
                if not role:
                    continue
                
                # Get timezone and convert current time
                tz_name = schedule.get('timezone', 'UTC')
                try:
                    tz = pytz.timezone(tz_name)
                    local_time = current_time.astimezone(tz)
                except Exception as e:
                    logging.warning(f"Failed to convert timezone {tz_name}: {e}")
                    local_time = current_time
                
                current_day = local_time.strftime('%A').lower()  # monday, tuesday, etc.
                current_hour = local_time.hour
                
                # Check if today is in the allowed days
                allowed_days = schedule.get('days', [])
                if not allowed_days:
                    continue
                
                # Check if current time is within the allowed hours
                start_hour = schedule.get('start_hour', 0)
                end_hour = schedule.get('end_hour', 23)
                
                is_allowed_day = current_day in [day.lower() for day in allowed_days]
                is_allowed_time = start_hour <= current_hour <= end_hour
                
                # Get current permissions for the role
                current_overwrites = channel.overwrites_for(role)
                
                # Always allow viewing and reading, but control sending messages
                if not current_overwrites.view_channel or current_overwrites.view_channel is False:
                    # Enable viewing and reading (always)
                    await channel.set_permissions(role, view_channel=True, read_messages=True)
                    logging.info(f"Enabled viewing access to {channel.name} for role {role.name}")
                
                if is_allowed_day and is_allowed_time:
                    # Channel should be writable
                    if current_overwrites.send_messages is False:
                        # Enable sending messages
                        await channel.set_permissions(role, send_messages=True)
                        logging.info(f"Enabled sending messages in {channel.name} for role {role.name}")
                        
                        # Send notification if enabled
                        if schedule.get('notifications', False):
                            try:
                                embed = discord.Embed(
                                    title="📢 Channel Now Open for Chat",
                                    description=f"The channel {channel.mention} is now open for chatting for {role.mention}",
                                    color=discord.Color.green(),
                                    timestamp=current_time
                                )
                                embed.add_field(name="Schedule", value=f"Days: {', '.join(allowed_days)}\nTime: {start_hour}:00 - {end_hour}:00 ({tz_name})", inline=False)
                                
                                # Try to send to a logs channel or the channel itself
                                logs_channel_id = os.getenv('LOGS_CHANNEL_ID')
                                if logs_channel_id:
                                    logs_channel = guild.get_channel(int(logs_channel_id))
                                    if logs_channel:
                                        await logs_channel.send(embed=embed)
                            except Exception as e:
                                logging.error(f"Failed to send channel open notification: {e}")
                
                else:
                    # Channel should be read-only
                    if current_overwrites.send_messages is True:
                        # Disable sending messages
                        await channel.set_permissions(role, send_messages=False)
                        logging.info(f"Disabled sending messages in {channel.name} for role {role.name}")
                        
                        # Send notification if enabled
                        if schedule.get('notifications', False):
                            try:
                                embed = discord.Embed(
                                    title="🔒 Channel Now Read-Only",
                                    description=f"The channel {channel.mention} is now read-only for {role.mention}",
                                    color=discord.Color.orange(),
                                    timestamp=current_time
                                )
                                embed.add_field(name="Schedule", value=f"Days: {', '.join(allowed_days)}\nTime: {start_hour}:00 - {end_hour}:00 ({tz_name})", inline=False)
                                
                                # Try to send to a logs channel
                                logs_channel_id = os.getenv('LOGS_CHANNEL_ID')
                                if logs_channel_id:
                                    logs_channel = guild.get_channel(int(logs_channel_id))
                                    if logs_channel:
                                        await logs_channel.send(embed=embed)
                            except Exception as e:
                                logging.error(f"Failed to send channel read-only notification: {e}")
            
            except Exception as e:
                logging.error(f"Error updating permissions for channel {channel_id}: {e}")

    @update_channel_permissions.before_loop
    async def before_update_permissions(self):
        """Wait until bot is ready before starting the task"""
        await self.bot.wait_until_ready()

async def timezone_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for timezone choices"""
    timezone_choices = [
        app_commands.Choice(name="US East (EST/EDT)", value="America/New_York"),
        app_commands.Choice(name="US West (PST/PDT)", value="America/Los_Angeles"),
        app_commands.Choice(name="London (GMT/BST)", value="Europe/London"),
        app_commands.Choice(name="Asia (IST)", value="Asia/Kolkata"),
        app_commands.Choice(name="Tokyo (JST)", value="Asia/Tokyo"),
        app_commands.Choice(name="UTC", value="UTC")
    ]
    
    if not current:
        return timezone_choices[:5]
    
    filtered = [choice for choice in timezone_choices if current.lower() in choice.name.lower()]
    return filtered[:5]

async def days_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for days choices with multiple day options"""
    days_choices = [
        # Single days
        app_commands.Choice(name="Monday", value="monday"),
        app_commands.Choice(name="Tuesday", value="tuesday"),
        app_commands.Choice(name="Wednesday", value="wednesday"),
        app_commands.Choice(name="Thursday", value="thursday"),
        app_commands.Choice(name="Friday", value="friday"),
        app_commands.Choice(name="Saturday", value="saturday"),
        app_commands.Choice(name="Sunday", value="sunday"),
        
        # Common combinations
        app_commands.Choice(name="Weekdays (Mon-Fri)", value="monday,tuesday,wednesday,thursday,friday"),
        app_commands.Choice(name="Weekends (Sat-Sun)", value="saturday,sunday"),
        app_commands.Choice(name="All Days", value="monday,tuesday,wednesday,thursday,friday,saturday,sunday"),
        
        # Business week combinations
        app_commands.Choice(name="Mon-Wed", value="monday,tuesday,wednesday"),
        app_commands.Choice(name="Wed-Fri", value="wednesday,thursday,friday"),
        app_commands.Choice(name="Mon-Thu", value="monday,tuesday,wednesday,thursday"),
        app_commands.Choice(name="Tue-Fri", value="tuesday,wednesday,thursday,friday"),
        
        # Weekend combinations
        app_commands.Choice(name="Fri-Sun", value="friday,saturday,sunday"),
        app_commands.Choice(name="Sat-Mon", value="saturday,sunday,monday"),
        
        # Custom combinations
        app_commands.Choice(name="Mon, Wed, Fri", value="monday,wednesday,friday"),
        app_commands.Choice(name="Tue, Thu, Sat", value="tuesday,thursday,saturday"),
        app_commands.Choice(name="Mon, Tue, Thu", value="monday,tuesday,thursday"),
        app_commands.Choice(name="Wed, Fri, Sun", value="wednesday,friday,sunday")
    ]
    
    if not current:
        return days_choices[:15]  # Show first 15 options when no search
    
    # Filter based on current input
    filtered = [choice for choice in days_choices if current.lower() in choice.name.lower()]
    
    # If no matches, show some default options
    if not filtered:
        return days_choices[:8]
    
    return filtered[:15]  # Return up to 15 filtered results

    @app_commands.command(name="daily_access_channel", description="Set up daily chat access for a channel - users can always see but only chat on specified days")
    @app_commands.describe(
        channel="The Discord channel to schedule",
        role="The role that will have access",
        timezone_name="Timezone for the schedule",
        days="Days of the week when channel should be open (use autocomplete or type: monday,tuesday,wednesday)",
        start_hour="Hour when access begins (0-23)",
        end_hour="Hour when access ends (0-23)"
    )
    @app_commands.autocomplete(timezone_name=timezone_autocomplete, days=days_autocomplete)
    @app_commands.default_permissions(administrator=True)
    async def daily_access_channel(
        self, 
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        role: discord.Role,
        timezone_name: str,
        days: str,
        start_hour: int = 9,
        end_hour: int = 17
    ):
        """
        Set up daily chat access for a channel - users can always see the channel but only chat on specified days
        
        Examples:
        - /daily_access_channel #daily-bias @Members "US East" "Weekdays" 9 17
        - /daily_access_channel #weekend @VIP "London" "Weekends" 0 23
        - /daily_access_channel #business @Employees "Tokyo" "Monday" 8 18
        """
        
        # Check permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need Administrator permissions to use this command!", ephemeral=True)
            return
        
        # Validate hours
        if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23):
            await interaction.response.send_message("❌ Hours must be between 0 and 23!", ephemeral=True)
            return
        
        if start_hour >= end_hour:
            await interaction.response.send_message("❌ Start hour must be before end hour!", ephemeral=True)
            return
        
        # Parse days
        day_list = [day.strip().lower() for day in days.split(',')]
        valid_days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        
        invalid_days = [day for day in day_list if day not in valid_days]
        if invalid_days:
            await interaction.response.send_message(
                f"❌ Invalid days: {', '.join(invalid_days)}\nValid days: {', '.join(valid_days)}", 
                ephemeral=True
            )
            return
        
        # Create schedule
        schedule_data = {
            'role_id': role.id,
            'days': day_list,
            'start_hour': start_hour,
            'end_hour': end_hour,
            'timezone': timezone_name,
            'notifications': True,  # Default to true for better UX
            'created_by': interaction.user.id,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        
        # Save to memory and file
        self.channel_schedules[channel.id] = schedule_data
        self.schedules[str(channel.id)] = schedule_data
        save_schedules(self.schedules)
        
        # Get current time in the specified timezone
        tz = pytz.timezone(timezone_name)
        current_time = datetime.now(timezone.utc).astimezone(tz)
        
        # Create embed response
        embed = discord.Embed(
            title="✅ Daily Chat Access Configured",
            description=f"Channel {channel.mention} will be open for chatting by {role.mention} on the specified schedule.\n\n**Note:** Users can always see the channel, but can only send messages during the scheduled times.",
            color=discord.Color.green()
        )
        embed.add_field(name="Days", value=", ".join(day_list), inline=True)
        embed.add_field(name="Time", value=f"{start_hour:02d}:00 - {end_hour:02d}:00", inline=True)
        embed.add_field(name="Timezone", value=timezone_name, inline=True)
        embed.add_field(name="Current Time", value=f"{current_time.strftime('%H:%M')} {timezone_name}", inline=True)
        embed.add_field(name="Notifications", value="✅ Enabled", inline=True)
        embed.set_footer(text=f"Configured by {interaction.user.name}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
        # Log the action
        logging.info(f"Daily chat access configured for {channel.name} by {interaction.user.name}")

    @app_commands.command(name="remove_daily_channel", description="Remove daily access schedule from a channel")
    @app_commands.default_permissions(administrator=True)
    async def remove_daily_channel(
        self, 
        interaction: discord.Interaction,
        channel: discord.TextChannel
    ):
        """Remove daily access schedule from a channel"""
        
        # Check permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need Administrator permissions to use this command!", ephemeral=True)
            return
        
        # Check if schedule exists
        if channel.id not in self.channel_schedules:
            await interaction.response.send_message(f"❌ No daily schedule found for {channel.mention}!", ephemeral=True)
            return
        
        # Get schedule info for response
        schedule = self.channel_schedules[channel.id]
        role = interaction.guild.get_role(schedule['role_id'])
        role_name = role.name if role else "Unknown Role"
        
        # Remove from memory and file
        del self.channel_schedules[channel.id]
        del self.schedules[str(channel.id)]
        save_schedules(self.schedules)
        
        # Create embed response
        embed = discord.Embed(
            title="🗑️ Daily Chat Access Removed",
            description=f"Daily chat access schedule removed from {channel.mention}",
            color=discord.Color.orange()
        )
        embed.add_field(name="Role", value=role_name, inline=True)
        embed.add_field(name="Days", value=", ".join(schedule['days']), inline=True)
        embed.add_field(name="Time", value=f"{schedule['start_hour']:02d}:00 - {schedule['end_hour']:02d}:00", inline=True)
        embed.add_field(name="Timezone", value=schedule.get('timezone', 'UTC'), inline=True)
        embed.set_footer(text=f"Removed by {interaction.user.name}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
        # Log the action
        logging.info(f"Daily chat access removed from {channel.name} by {interaction.user.name}")

    @app_commands.command(name="list_daily_channels", description="List all channels with daily access schedules")
    @app_commands.default_permissions(administrator=True)
    async def list_daily_channels(self, interaction: discord.Interaction):
        """List all channels with daily access schedules"""
        
        # Check permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need Administrator permissions to use this command!", ephemeral=True)
            return
        
        if not self.channel_schedules:
            await interaction.response.send_message("📋 No daily channel schedules configured.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="📋 Daily Chat Schedules",
            description="Channels with configured daily chat access schedules:",
            color=discord.Color.blue()
        )
        
        for channel_id, schedule in self.channel_schedules.items():
            channel = interaction.guild.get_channel(channel_id)
            role = interaction.guild.get_role(schedule['role_id'])
            
            if channel and role:
                # Get current time in the schedule's timezone
                tz_name = schedule.get('timezone', 'UTC')
                try:
                    tz = pytz.timezone(tz_name)
                    current_time = datetime.now(timezone.utc).astimezone(tz)
                    current_day = current_time.strftime('%A').lower()
                    current_hour = current_time.hour
                except Exception:
                    current_time = datetime.now(timezone.utc)
                    current_day = current_time.strftime('%A').lower()
                    current_hour = current_time.hour
                
                is_allowed_day = current_day in [day.lower() for day in schedule['days']]
                is_allowed_time = schedule['start_hour'] <= current_hour <= schedule['end_hour']
                
                status = "🟢 Chat Open" if (is_allowed_day and is_allowed_time) else "🔴 Read-Only"
                
                embed.add_field(
                    name=f"{status} {channel.name}",
                    value=f"**Role:** {role.mention}\n**Days:** {', '.join(schedule['days'])}\n**Time:** {schedule['start_hour']:02d}:00 - {schedule['end_hour']:02d}:00\n**Timezone:** {tz_name}\n**Notifications:** {'✅' if schedule.get('notifications', False) else '❌'}",
                    inline=False
                )
        
        embed.set_footer(text=f"Total schedules: {len(self.channel_schedules)} | Users can always see channels, but only chat during scheduled times")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="test_daily_channel", description="Test the current status of a channel's daily access")
    @app_commands.default_permissions(administrator=True)
    async def test_daily_channel(
        self, 
        interaction: discord.Interaction,
        channel: discord.TextChannel
    ):
        """Test the current status of a channel's daily access"""
        
        # Check permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need Administrator permissions to use this command!", ephemeral=True)
            return
        
        if channel.id not in self.channel_schedules:
            await interaction.response.send_message(f"❌ No daily schedule found for {channel.mention}!", ephemeral=True)
            return
        
        schedule = self.channel_schedules[channel.id]
        role = interaction.guild.get_role(schedule['role_id'])
        
        if not role:
            await interaction.response.send_message("❌ Role not found!", ephemeral=True)
            return
        
        # Get current time in the schedule's timezone
        tz_name = schedule.get('timezone', 'UTC')
        try:
            tz = pytz.timezone(tz_name)
            current_time = datetime.now(timezone.utc).astimezone(tz)
            current_day = current_time.strftime('%A').lower()
            current_hour = current_time.hour
        except Exception:
            current_time = datetime.now(timezone.utc)
            current_day = current_time.strftime('%A').lower()
            current_hour = current_time.hour
        
        is_allowed_day = current_day in [day.lower() for day in schedule['days']]
        is_allowed_time = schedule['start_hour'] <= current_hour <= schedule['end_hour']
        
        # Check actual permissions
        overwrites = channel.overwrites_for(role)
        has_access = overwrites.view_channel is True
        
        embed = discord.Embed(
            title="🧪 Daily Chat Access Test",
            description=f"Testing chat access for {channel.mention}",
            color=discord.Color.blue()
        )
        
        embed.add_field(name="Role", value=role.mention, inline=True)
        embed.add_field(name="Current Day", value=current_day.title(), inline=True)
        embed.add_field(name="Current Hour", value=f"{current_hour:02d}:00", inline=True)
        embed.add_field(name="Timezone", value=tz_name, inline=True)
        embed.add_field(name="Allowed Days", value=", ".join(schedule['days']), inline=True)
        embed.add_field(name="Allowed Time", value=f"{schedule['start_hour']:02d}:00 - {schedule['end_hour']:02d}:00", inline=True)
        embed.add_field(name="Schedule Status", value="✅ Chat Allowed" if (is_allowed_day and is_allowed_time) else "❌ Read-Only", inline=True)
        embed.add_field(name="Actual Chat Access", value="✅ Can Send Messages" if has_access else "❌ Read-Only", inline=True)
        
        if (is_allowed_day and is_allowed_time) != has_access:
            embed.color = discord.Color.red()
            embed.add_field(name="⚠️ Status Mismatch", value="Schedule and actual chat permissions don't match!", inline=False)
        else:
            embed.color = discord.Color.green()
            embed.add_field(name="✅ Status Match", value="Schedule and actual chat permissions match!", inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    """Add the daily channel access cog to the bot."""
    await bot.add_cog(DailyChannelAccess(bot)) 