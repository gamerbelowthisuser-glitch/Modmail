"""
Modmail plugin: adds a button inside each thread channel that lets staff
pull up ONLY the actual conversation (user + staff messages), stripped of
system messages, internal notes, and embed clutter.

INSTALL
-------
Drop this file into your bot's `cogs/` folder (or wherever you keep custom
plugins/cogs for this fork), then load it like any other cog, e.g.:

    bot.load_extension("cogs.logbutton")

or if this fork uses the plugin manager, package it as a plugin with an
info.json and load via `?plugins add <path>`.

NOTES / THINGS TO DOUBLE-CHECK FOR YOUR FORK
---------------------------------------------
This fork (gamerbelowthisuser-glitch/Modmail) has custom additions on top of
upstream modmail-dev/Modmail (e.g. thread_creation_menu), so a couple of
names below may need small adjustments to match your codebase exactly:

1. `self.bot.threads.find(channel=...)` — this is the standard modmail-dev
   API for resolving a Thread object from a channel. If your fork renamed
   `bot.threads` or `Thread`, adjust accordingly.
2. `self.bot.api.get_log(channel.id)` — standard modmail-dev log API call
   that returns the raw log document (dict) for a thread, including a
   `messages` list. Each message dict has `type`, `content`, and `author`.
   If your log schema stores things differently, adjust the `entry.get(...)`
   calls in `request_log` to match your document shape.
3. `on_thread_ready` — the event fired once a modmail thread channel is
   fully created. If your fork uses a different event name (check bot.py /
   core/thread.py for `self.bot.dispatch(...)` calls), update the listener
   name to match, or just rely on the `?logbutton` command below instead.
4. `PermissionLevel.SUPPORTER` — swap for whatever permission tier you want
   able to run the manual command (e.g. `MODERATOR`).
"""

import discord
from discord.ext import commands

from core.models import PermissionLevel
from core import checks


class LogRequestView(discord.ui.View):
    """A persistent button that shows just the plain conversation for
    the thread it's posted in."""

    def __init__(self, bot):
        super().__init__(timeout=None)  # persistent across restarts
        self.bot = bot

    @discord.ui.button(
        label="Request Message Log",
        style=discord.ButtonStyle.blurple,
        emoji="📜",
        custom_id="modmail:request_message_log",
    )
    async def request_log(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)

        channel = interaction.channel
        thread = await self.bot.threads.find(channel=channel)
        if thread is None:
            return await interaction.followup.send(
                "This isn't a Modmail thread channel.", ephemeral=True
            )

        log_data = await self.bot.api.get_log(channel.id)
        if not log_data:
            return await interaction.followup.send(
                "No log data found for this thread yet.", ephemeral=True
            )

        lines = []
        for entry in log_data.get("messages", []):
            # Keep only genuine conversation turns. Drop system messages,
            # internal notes, closes, moves, etc.
            if entry.get("type") not in ("thread_message", "anonymous"):
                continue

            content = (entry.get("content") or "").strip()
            if not content:
                continue

            author = entry.get("author", {})
            name = author.get("name", "Unknown")
            tag = "Staff" if author.get("mod") else "User"
            lines.append(f"**{name}** ({tag}): {content}")

        if not lines:
            return await interaction.followup.send(
                "No messages have been exchanged in this thread yet.",
                ephemeral=True,
            )

        full_text = "\n".join(lines)

        # Manually paginate in case the transcript is long.
        chunk_size = 3900
        chunks = [full_text[i : i + chunk_size] for i in range(0, len(full_text), chunk_size)]

        for i, chunk in enumerate(chunks):
            embed = discord.Embed(
                title="Message Log" + (" (cont.)" if i else ""),
                description=chunk,
                color=self.bot.main_color,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)


class LogButton(commands.Cog):
    """Posts / re-registers the log-request button for thread channels."""

    def __init__(self, bot):
        self.bot = bot
        # Re-register the persistent view on bot restart so old buttons
        # posted before a reboot still work.
        self.bot.add_view(LogRequestView(bot))

    @commands.Cog.listener()
    async def on_thread_ready(self, thread, *args, **kwargs):
        """Fires once a new Modmail thread channel is fully set up.
        Adjust the event name here if your fork dispatches a differently
        named event for thread creation."""
        try:
            await thread.channel.send(
                "Staff can click below to pull just the message content "
                "from this thread (no notes, no system messages).",
                view=LogRequestView(self.bot),
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

    @checks.has_permissions(PermissionLevel.SUPPORTER)
    @commands.command(name="logbutton")
    async def logbutton_cmd(self, ctx):
        """Manually post the log-request button in the current thread channel,
        useful for threads that existed before this plugin was installed."""
        thread = await self.bot.threads.find(channel=ctx.channel)
        if thread is None:
            return await ctx.send("This command must be used inside a thread channel.")
        await ctx.send(
            "Click below to pull just the conversation from this thread.",
            view=LogRequestView(self.bot),
        )


async def setup(bot):
    await bot.add_cog(LogButton(bot))
