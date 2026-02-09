"""
Refresh welcome message command: re-post welcome embed + Start Verification button.
"""
import logging
import os
import discord
from discord import app_commands
from discord.ext import commands

from cogs.welcome import (
    get_or_create_welcome_message,
    get_start_verification_view,
    WELCOME_EMBED_DESCRIPTION,
)

OWNER_USER_IDS = {890323443252351046, 879714530769391686}
GUILD_ID = int(os.getenv("GUILD_ID", 0))
DEFAULT_VITO_LOGO = "https://cdn.discordapp.com/attachments/1428075084811206716/1468365777131540522/tmp6by9gc_h.png"


def is_authorized_guild_or_owner(interaction: discord.Interaction) -> bool:
    if interaction.guild and interaction.guild.id == GUILD_ID:
        return True
    if interaction.user.id in OWNER_USER_IDS:
        return True
    return False


@app_commands.command(
    name="refresh_welcome",
    description="Manually refresh the welcome message (embed + Start Verification button)",
)
@app_commands.default_permissions(administrator=True)
async def refresh_welcome(interaction: discord.Interaction) -> None:
    if not is_authorized_guild_or_owner(interaction):
        await interaction.response.send_message(
            "You are not authorized to use this command.",
            ephemeral=True,
        )
        return
    if not interaction.guild:
        await interaction.response.send_message(
            "This command can only be used in a server.",
            ephemeral=True,
        )
        return
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message(
            "Could not resolve member.",
            ephemeral=True,
        )
        return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "You need Administrator permission.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    welcome_channel_id = os.getenv("WELCOME_CHANNEL_ID")
    if not welcome_channel_id:
        await interaction.followup.send(
            "WELCOME_CHANNEL_ID is not set.",
            ephemeral=True,
        )
        return

    welcome_channel = interaction.client.get_channel(int(welcome_channel_id))
    if not welcome_channel or not isinstance(
        welcome_channel, discord.TextChannel
    ):
        await interaction.followup.send(
            "Welcome channel not found. Check .env.",
            ephemeral=True,
        )
        return

    try:
        logo_url = os.getenv("VITO_LOGO_URL", DEFAULT_VITO_LOGO)
        embed = discord.Embed(
            title="👋 Welcome to the Server!",
            description=WELCOME_EMBED_DESCRIPTION,
            color=0xFFFFFF,
        )
        embed.set_footer(text="Welcome to Vito")
        embed.set_thumbnail(url=logo_url)
        view = get_start_verification_view()
        msg = await get_or_create_welcome_message(
            welcome_channel, embed, view
        )
        result = discord.Embed(
            title="Welcome message refreshed",
            description="Welcome message updated successfully.",
            color=discord.Color.green(),
        )
        result.add_field(
            name="Channel",
            value=welcome_channel.mention,
            inline=True,
        )
        result.add_field(
            name="Message",
            value=f"[Jump to message]({msg.jump_url})",
            inline=True,
        )
        await interaction.followup.send(embed=result, ephemeral=True)
    except Exception as e:
        logging.exception("refresh_welcome failed")
        await interaction.followup.send(
            f"Error refreshing welcome: {e}",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    bot.tree.add_command(refresh_welcome)
