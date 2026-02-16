"""
Welcome cog for Vito: welcome message + Start Verification button.
Start Verification shows an ephemeral message only (no tickets):
- If user has a paid role (PAID_ROLE_IDS) or member role → "You're already verified."
- Else → "You'll get free member access automatically within 1 hour of joining."
Member role is granted by member_management cog after 1hr for new joiners.
"""
import asyncio
import logging
import os
import re
import time
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import discord


async def _log_start_verification(guild: discord.Guild, member: discord.Member, status: str, dm_sent: bool | None = None) -> None:
    """Send a log embed when someone presses Start Verification."""
    logs_channel_id = os.getenv("LOGS_CHANNEL_ID")
    if not logs_channel_id:
        return
    channel = guild.get_channel(int(logs_channel_id))
    if not channel or not isinstance(channel, discord.TextChannel):
        return
    embed = discord.Embed(
        title="🎫 Start Verification",
        description=f"{member.mention} pressed **Start Verification**.",
        color=discord.Color.blue(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="User", value=f"{member.mention}\n({member.name})", inline=True)
    embed.add_field(name="User ID", value=str(member.id), inline=True)
    embed.add_field(name="Status", value=status, inline=False)
    if dm_sent is not None:
        embed.add_field(name="Booking link DM", value="✅ Sent" if dm_sent else "❌ Not sent", inline=True)
    embed.set_footer(text=f"Guild: {guild.name}")
    try:
        await channel.send(embed=embed)
    except Exception as e:
        logging.warning("Failed to send Start Verification log: %s", e)
from discord.ext import commands

# Vito branding - overridable via env
DEFAULT_CALL_BOOKING_LINK = "https://app.iclosed.io/e/barracudagrowth/vito-s-concepts-intiation-call-d"
DEFAULT_VITO_LOGO = "https://cdn.discordapp.com/attachments/1428075084811206716/1468365777131540522/tmp6by9gc_h.png"

WELCOME_MESSAGE_FILE = "welcome_message.json"
VERIFICATION_TICKETS_FILE = "verification_tickets.json"
PENDING_USERS_FILE = "pending_users.json"
START_VERIFICATION_CUSTOM_ID = "vito_start_verification"


def _cooldown_seconds() -> int:
    """Cooldown for Start Verification button (seconds). From env VERIFICATION_COOLDOWN_SECONDS, default 30."""
    try:
        raw = os.getenv("VERIFICATION_COOLDOWN_SECONDS", "30").strip()
        return max(1, int(raw)) if raw else 30
    except (ValueError, TypeError):
        return 30


def _ticket_auto_close_seconds() -> int:
    """Ticket close timeout in seconds. Env TICKET_AUTO_CLOSE_SECONDS (e.g. 20 for testing), default 3600 (1hr)."""
    try:
        raw = os.getenv("TICKET_AUTO_CLOSE_SECONDS", "").strip()
        if raw:
            return max(1, int(raw))
    except (ValueError, TypeError):
        pass
    return 3600  # 1 hour default


def _get_paid_role_ids() -> set[int]:
    """Load comma-separated PAID_ROLE_IDS from env. Any role in this set counts as paid/verified."""
    raw = os.getenv("PAID_ROLE_IDS", "").strip()
    if not raw:
        return set()
    ids = set()
    for part in raw.replace(" ", "").split(","):
        part = part.strip()
        if part and part.isdigit():
            ids.add(int(part))
    return ids


def _sanitize_channel_name(name: str, max_len: int = 100) -> str:
    """Sanitize for Discord channel name (lowercase, no spaces)."""
    s = re.sub(r"[^\w\s-]", "", name).strip() or "user"
    s = re.sub(r"[-\s]+", "-", s).lower()
    return s[:max_len] if len(s) > max_len else s


def _load_tickets() -> dict:
    path = Path(VERIFICATION_TICKETS_FILE)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_tickets(data: dict) -> None:
    with open(VERIFICATION_TICKETS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _load_pending_users() -> dict:
    path = Path(PENDING_USERS_FILE)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_pending_users(data: dict) -> None:
    with open(PENDING_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _cta_view(booking_link: str) -> discord.ui.View:
    """Ticket: only the booking link button. No auto-verify; member role is granted after timeout."""
    view = discord.ui.View()
    view.add_item(
        discord.ui.Button(
            label="Book your onboarding call",
            style=discord.ButtonStyle.link,
            url=booking_link,
            emoji="📅",
        )
    )
    return view


class StartVerificationView(discord.ui.View):
    """Persistent view: Start Verification creates a private channel (ticket) per user."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        self._cooldowns: dict[int, float] = {}

    @discord.ui.button(
        label="Start Verification",
        style=discord.ButtonStyle.primary,
        custom_id=START_VERIFICATION_CUSTOM_ID,
        emoji="🎫",
    )
    async def start_verification(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This can only be used in the server.",
                ephemeral=True,
            )
            return

        user_id = interaction.user.id
        now = time.time()
        cooldown = _cooldown_seconds()
        if now - self._cooldowns.get(user_id, 0) < cooldown:
            await interaction.response.send_message(
                f"Please wait {int(cooldown - (now - self._cooldowns[user_id]))}s before trying again.",
                ephemeral=True,
            )
            return
        self._cooldowns[user_id] = now

        member = interaction.user
        guild = interaction.guild
        paid_role_ids = _get_paid_role_ids()
        member_role_id = int(os.getenv("MEMBER_ROLE_ID", 0))

        has_paid = bool(paid_role_ids) and any(r.id in paid_role_ids for r in member.roles)
        has_member = member_role_id and any(r.id == member_role_id for r in member.roles)

        if has_paid or has_member:
            await interaction.response.send_message(
                "✅ **You're already verified.** You have access to the server.",
                ephemeral=True,
            )
            await _log_start_verification(guild, member, "Already verified")
            return

        await interaction.response.defer(ephemeral=True)
        booking_link = os.getenv("CALL_BOOKING_LINK", DEFAULT_CALL_BOOKING_LINK)
        dm_sent = False
        try:
            dm_embed = discord.Embed(
                title="📅 Book your onboarding call",
                description=(
                    "Book your call using the link below to get the most out of the server.\n\n"
                    f"👉 [**Book your onboarding call**]({booking_link})"
                ),
                color=discord.Color.blue(),
            )
            dm_embed.set_footer(text="Vito")
            await member.send(embed=dm_embed)
            dm_sent = True
        except discord.Forbidden:
            pass
        except Exception as e:
            logging.warning("Could not send booking link DM to %s: %s", member.name, e)

        if dm_sent:
            await interaction.followup.send(
                "**The booking link has been sent to your DMs.**\n\n"
                "Please book your call to get access. ",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "I couldn't send you a DM. Please allow DMs from this server, or book your call here: "
                f"{booking_link}\n\n"
                "Please book your call to get access. ",
                ephemeral=True,
            )
        await _log_start_verification(guild, member, "Not verified – booking link / 1hr access", dm_sent=dm_sent)


def get_start_verification_view() -> discord.ui.View:
    return StartVerificationView()


async def get_or_create_welcome_message(
    welcome_channel: discord.TextChannel,
    embed: discord.Embed,
    view: discord.ui.View | None = None,
) -> discord.Message:
    try:
        with open(WELCOME_MESSAGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            msg_id = data.get("message_id")
            channel_id = data.get("channel_id")
    except (FileNotFoundError, json.JSONDecodeError):
        msg_id = None
        channel_id = None

    if channel_id != welcome_channel.id:
        msg_id = None

    if msg_id:
        try:
            msg = await welcome_channel.fetch_message(msg_id)
            await msg.edit(embed=embed, view=view)
            return msg
        except (discord.NotFound, discord.HTTPException):
            pass

    msg = await welcome_channel.send(embed=embed, view=view)
    with open(WELCOME_MESSAGE_FILE, "w", encoding="utf-8") as f:
        json.dump({"message_id": msg.id, "channel_id": welcome_channel.id}, f)
    return msg


WELCOME_EMBED_DESCRIPTION = """To access the server you'll need to be verified.

New members get **free member access** automatically within 1 hour of joining.
If you already have a paid role or member role, you're all set.

Click **Start Verification** below to check your status."""


class Welcome(commands.Cog):
    """Welcome channel + Start Verification (ephemeral status only). Legacy ticket auto-close loop still runs for old tickets."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(StartVerificationView())

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        try:
            guild_id = os.getenv("GUILD_ID")
            if not guild_id:
                logging.error("GUILD_ID is not set")
                return
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                logging.error("Guild %s not found", guild_id)
                return

            welcome_channel_id = os.getenv("WELCOME_CHANNEL_ID")
            if not welcome_channel_id:
                logging.error("WELCOME_CHANNEL_ID is not set")
                return
            welcome_channel = self.bot.get_channel(int(welcome_channel_id))
            if not welcome_channel or not isinstance(welcome_channel, discord.TextChannel):
                logging.error("Welcome channel %s not found", welcome_channel_id)
                return

            logo_url = os.getenv("VITO_LOGO_URL", DEFAULT_VITO_LOGO)
            embed = discord.Embed(
                title="👋 Welcome to the Server!",
                description=WELCOME_EMBED_DESCRIPTION,
                color=0xFFFFFF,
            )
            embed.set_footer(text="Welcome to Vito")
            embed.set_thumbnail(url=logo_url)
            view = get_start_verification_view()
            msg = await get_or_create_welcome_message(welcome_channel, embed, view)
            logging.info("Welcome message persistent: %s", msg.jump_url)
            self.bot.loop.create_task(self._ticket_auto_close_loop())
        except Exception as e:
            logging.exception("Welcome on_ready failed: %s", e)

    async def _ticket_auto_close_loop(self) -> None:
        """Every minute: close tickets older than 1hr; grant member role if no paid role."""
        await self.bot.wait_until_ready()
        guild_id = os.getenv("GUILD_ID")
        member_role_id = int(os.getenv("MEMBER_ROLE_ID", 0))
        unverified_role_id = int(os.getenv("UNVERIFIED_ROLE_ID", 0))
        if not guild_id or not member_role_id:
            logging.warning("GUILD_ID or MEMBER_ROLE_ID missing; ticket auto-close may not grant roles")
        while True:
            try:
                await self._close_old_tickets(
                    int(guild_id) if guild_id else 0,
                    member_role_id,
                    unverified_role_id,
                )
            except Exception as e:
                logging.exception("Ticket auto-close error: %s", e)
            await asyncio.sleep(60)

    async def _close_old_tickets(
        self,
        guild_id: int,
        member_role_id: int,
        unverified_role_id: int,
    ) -> None:
        guild = self.bot.get_guild(guild_id) if guild_id else None
        if not guild:
            return

        tickets = _load_tickets()
        if not tickets:
            return

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=_ticket_auto_close_seconds())
        paid_role_ids = _get_paid_role_ids()
        to_remove = []

        for user_id_str, data in tickets.items():
            try:
                created_at = datetime.fromisoformat(data["created_at"])
                if created_at > cutoff:
                    continue
                channel_id = data.get("channel_id")
                if not channel_id:
                    to_remove.append(user_id_str)
                    continue

                channel = guild.get_channel(int(channel_id))
                user_id = int(user_id_str)
                member = guild.get_member(user_id)

                if member:
                    has_paid = bool(paid_role_ids) and any(
                        r.id in paid_role_ids for r in member.roles
                    )
                    if not has_paid:
                        member_role = guild.get_role(member_role_id)
                        if member_role and member_role not in member.roles:
                            await member.add_roles(member_role, reason="Ticket auto-close: no paid role, grant free member")
                        if unverified_role_id:
                            unverified = guild.get_role(unverified_role_id)
                            if unverified and unverified in member.roles:
                                await member.remove_roles(unverified, reason="Ticket auto-close")

                if channel and isinstance(channel, discord.TextChannel):
                    try:
                        await channel.delete(reason="Ticket auto-close 1hr")
                    except discord.HTTPException:
                        pass

                to_remove.append(user_id_str)
            except (ValueError, KeyError) as e:
                logging.warning("Ticket entry invalid %s: %s", user_id_str, e)
                to_remove.append(user_id_str)

        for key in to_remove:
            tickets.pop(key, None)
        if to_remove:
            _save_tickets(tickets)
            pending = _load_pending_users()
            for key in to_remove:
                pending.pop(key, None)
            _save_pending_users(pending)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Welcome(bot))
