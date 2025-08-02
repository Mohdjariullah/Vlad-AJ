import discord
from discord import app_commands
from discord.ext import commands
import typing
from datetime import datetime, timezone
from cogs.member_management import MemberManagement
from cogs.calendly import check_email_booked
import os
import random

OWNER_USER_IDS = {890323443252351046, 879714530769391686}
GUILD_ID = int(os.getenv('GUILD_ID', 0))

def is_authorized_guild_or_owner(interaction):
    if interaction.guild and interaction.guild.id == GUILD_ID:
        return True
    if interaction.user.id in OWNER_USER_IDS:
        return True
    return False

def simulate_calendly_check(email: str) -> bool:
    """Simulate Calendly checking with random results for testing"""
    # Simulate different scenarios based on email patterns
    if "test" in email.lower():
        return True  # Test emails always have bookings
    elif "demo" in email.lower():
        return False  # Demo emails never have bookings
    elif "admin" in email.lower():
        return random.choice([True, False])  # Random for admin emails
    else:
        # For other emails, simulate realistic booking probability (70% chance)
        return random.random() < 0.7

@app_commands.command(name="test_member_join", description="Test the member join functionality with Calendly simulation")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    user="The user to test with",
    email="Email to test Calendly checking (optional)"
)
async def test_member_join(interaction: discord.Interaction, user: discord.Member, email: str = None):
    """Test the member join functionality with simulated Calendly checking"""
    if not is_authorized_guild_or_owner(interaction):
        return await interaction.response.send_message(
            "❌ You are not authorized to use this command.", ephemeral=True
        )
    # SECURITY: Block DMs and check admin permissions
    if not interaction.guild:
        return await interaction.response.send_message("❌ This command can only be used in a server!", ephemeral=True)
    if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ You need Administrator permissions!", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True)
    
    bot = typing.cast(commands.Bot, interaction.client)
    member_cog = bot.get_cog("MemberManagement")
    if not member_cog:
        return await interaction.followup.send("❌ MemberManagement cog not loaded!", ephemeral=True)
    
    mm_cog = typing.cast(MemberManagement, member_cog)
    
    # Generate test email if not provided
    if not email:
        email = f"test.{user.name.lower()}@example.com"
    
    # Simulate Calendly check
    has_booking = simulate_calendly_check(email)
    
    # Create test log embed
    test_embed = discord.Embed(
        title="🧪 Manual Test Started",
        description=f"Testing member join functionality for {user.mention}",
        color=discord.Color.yellow(),
        timestamp=datetime.now(timezone.utc)
    )
    test_embed.add_field(name="Tested By", value=interaction.user.mention, inline=True)
    test_embed.add_field(name="Test Subject", value=user.mention, inline=True)
    test_embed.add_field(name="Test Email", value=email, inline=True)
    test_embed.add_field(name="Calendly Booking", value="✅ Found" if has_booking else "❌ Not Found", inline=True)
    test_embed.add_field(name="Current Roles", value=", ".join([role.name for role in user.roles]) if user.roles else "None", inline=False)
    test_embed.set_footer(text="Manual Test with Calendly Simulation")
    
    # Send to logs
    if hasattr(mm_cog, "send_to_logs"):
        await mm_cog.send_to_logs(interaction.guild, test_embed)
    
    print(f"🧪 MANUAL TEST: Testing member join for {user.name} with email {email} (booking: {has_booking})")
    
    # Run the test
    try:
        # First, simulate the member join process
        await mm_cog.on_member_join(user)
        
        # Then simulate the verification process with Calendly check
        if has_booking:
            # Simulate successful verification
            if user.id in mm_cog.member_original_roles:
                # Restore roles as if verification was successful
                restored_roles = await mm_cog.restore_member_roles(user)
                
                # Create success log
                success_embed = discord.Embed(
                    title="✅ Manual Test Completed - Booking Found",
                    description=f"Member join and verification test completed for {user.mention}",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc)
                )
                success_embed.add_field(name="Email", value=email, inline=True)
                success_embed.add_field(name="Calendly Result", value="✅ Booking Confirmed", inline=True)
                success_embed.add_field(name="Verification Status", value="✅ Completed", inline=True)
                
                if restored_roles:
                    role_names = [role.name for role in restored_roles]
                    success_embed.add_field(name="Roles Restored", value=", ".join(role_names), inline=False)
                else:
                    success_embed.add_field(name="Roles Restored", value="None", inline=False)
                
                success_embed.add_field(name="Monitoring Status", value="✅ Removed from monitoring" if user.id not in mm_cog.users_awaiting_verification else "⚠️ Still monitored", inline=True)
                
            else:
                success_embed = discord.Embed(
                    title="✅ Manual Test Completed - Booking Found",
                    description=f"Member join test completed for {user.mention}",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc)
                )
                success_embed.add_field(name="Email", value=email, inline=True)
                success_embed.add_field(name="Calendly Result", value="✅ Booking Confirmed", inline=True)
                success_embed.add_field(name="Result", value="No subscription roles found - no action taken", inline=False)
        else:
            # Simulate failed verification (no booking)
            success_embed = discord.Embed(
                title="⚠️ Manual Test Completed - No Booking",
                description=f"Member join test completed for {user.mention}",
                color=discord.Color.orange(),
                timestamp=datetime.now(timezone.utc)
            )
            success_embed.add_field(name="Email", value=email, inline=True)
            success_embed.add_field(name="Calendly Result", value="❌ No Booking Found", inline=True)
            success_embed.add_field(name="Verification Status", value="⏳ Pending - Requires Booking", inline=True)
            
            # Check if user was processed
            if user.id in mm_cog.member_original_roles:
                stored_roles = []
                guild = interaction.guild
                if guild is not None:
                    for role_id in mm_cog.member_original_roles[user.id]:
                        role = guild.get_role(role_id)
                        if role:
                            stored_roles.append(role.name)
                success_embed.add_field(name="Roles Stored", value=", ".join(stored_roles) if stored_roles else "None", inline=False)
                success_embed.add_field(name="Monitoring Status", value="✅ Added to monitoring" if user.id in mm_cog.users_awaiting_verification else "❌ Not monitored", inline=True)
            else:
                success_embed.add_field(name="Result", value="No subscription roles found - no action taken", inline=False)
        
        success_embed.set_footer(text="Manual Test Result with Calendly Simulation")
        
        # Send to logs
        if hasattr(mm_cog, "send_to_logs"):
            await mm_cog.send_to_logs(interaction.guild, success_embed)
        
        await interaction.followup.send(
            f"✅ Test completed for {user.mention} with email {email}.\n"
            f"Calendly Result: {'✅ Booking Found' if has_booking else '❌ No Booking'}\n"
            f"Check logs channel for detailed results.", 
            ephemeral=True
        )
        
    except Exception as e:
        # Create error log
        error_embed = discord.Embed(
            title="❌ Manual Test Failed",
            description=f"Error during member join test for {user.mention}",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        error_embed.add_field(name="Email", value=email, inline=True)
        error_embed.add_field(name="Calendly Result", value="❌ Error occurred", inline=True)
        error_embed.add_field(name="Error", value=str(e), inline=False)
        error_embed.set_footer(text="Manual Test Error")
        
        # Send to logs
        if hasattr(mm_cog, "send_to_logs"):
            await mm_cog.send_to_logs(interaction.guild, error_embed)
        
        await interaction.followup.send(
            f"❌ Test failed for {user.mention} with email {email}.\n"
            f"Check logs channel for error details.", 
            ephemeral=True
        )

async def setup(bot: commands.Bot):
    bot.tree.add_command(test_member_join) 