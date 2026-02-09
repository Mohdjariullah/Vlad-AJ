import logging
from discord.ext import commands
import importlib

from .help_admin import setup as setup_help_admin
from .force_verify import setup as setup_force_verify
from .test_member_join import setup as setup_test_member_join
from .setup_permissions import setup as setup_setup_permissions
from .restore_permissions import setup as setup_restore_permissions
from .refresh_welcome import setup as setup_refresh_welcome
from .userinfo import setup as setup_userinfo
from .debug_logs import setup as setup_debug_logs
from .check_pending import setup as setup_check_pending

async def setup(bot: commands.Bot) -> None:
    """Add admin commands to the bot."""
    logger = logging.getLogger(__name__)
    msg = "Loaded commands.{}"
    await setup_help_admin(bot)
    logger.debug(msg.format("help_admin"))
    await setup_force_verify(bot)
    logger.debug(msg.format("force_verify"))
    await setup_test_member_join(bot)
    logger.debug(msg.format("test_member_join"))
    await setup_setup_permissions(bot)
    logger.debug(msg.format("setup_permissions"))
    await setup_restore_permissions(bot)
    logger.debug(msg.format("restore_permissions"))
    await setup_refresh_welcome(bot)
    logger.debug(msg.format("refresh_welcome"))
    await setup_userinfo(bot)
    logger.debug(msg.format("userinfo"))
    await setup_debug_logs(bot)
    logger.debug(msg.format("debug_logs"))
    await setup_check_pending(bot)
    logger.debug(msg.format("check_pending"))
