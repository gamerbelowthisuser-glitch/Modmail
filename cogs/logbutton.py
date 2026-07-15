"""
Modmail addon: replaces the "Log link" URL button on the thread-closed
embed (sent to the log channel) with an interactive "Request Message Log"
button. Clicking it shows just the plain conversation (no system messages,
no internal notes) directly in Discord, instead of linking out to the
external logviewer.

INSTALL
-------
1. Place this file at:  cogs/logbutton.py
2. Edit bot.py and add "cogs.logbutton" to self.loaded_cogs:

    self.loaded_cogs = [
        "cogs.modmail",
        "cogs.plugins",
        "cogs.utility",
        "cogs.threadmenu",
        "cogs.logbutton",
    ]

3. Apply the accompanying change to core/thread.py's `_close` method (the
   block that currently builds the "Log link" URL button needs to be
   swapped for a button with a matching custom_id — see the diff provided
   alongside this file).
4. Restart the bot.

WHY DynamicItem
---------------
The view carrying this button is built once inside Thread._close() and
never kept around afterward — there's no persistent object to re-register
each button against on restart. `discord.ui.DynamicItem` solves this: it
matches on a regex pattern against the button's `custom_id` whenever ANY
interaction comes in, and reconstructs itself on the fly. That means the
button keeps working correctly forever, across restarts, without
core/thread.py needing to import this cog or know anything about it — it
only needs to set a custom_id like "logrequest:<channel_id>" on the button
it sends.

THINGS TO DOUBLE-CHECK
-----------------------
- `self.bot.api.get_log(channel_id)` — inferred read-method name; if
  core/clients.py names it differently, update the one line below that
  calls it.
- Log message `type` values: this keeps entries typed "thread_message" or
  "anonymous" (real conversation) and drops "note"/"internal"/system
  entries, matching the type_ values used elsewhere in this codebase's
  api.append_log calls.
"""

import discord
from discord.ext import commands


class LogRequestButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"logrequest:(?P<channel_id>[0-9]+)",
):
    """A button whose custom_id encodes which thread's log to pull.
    Reconstructed automatically by discord.py whenever a matching
    interaction comes in — no need to keep the original View alive."""

    def __init__(self, channel_id: int):
        super().__init__(
            discord.ui.Button(
                label="Request Message Log",
                style=discord.ButtonStyle.blurple,
                emoji="📜",
                custom_id=f"logrequest:{channel_id}",
            )
        )
        self.channel_id = channel_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["channel_id"]))

    async def callback(self, interaction: discord.Interaction):
        bot = interaction.client
        await interaction.response.defer(ephemeral=True, thinking=True)

        log_data = await bot.api.get_log(self.channel_id)
        if not log_data:
            return await interaction.followup.send(
                "No log data found for this thread.", ephemeral=True
            )

        lines = []
        for entry in log_data.get("messages", []):
            # Keep only genuine conversation turns; drop system messages,
            # internal notes, moves/closes, etc.
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
                "No messages were exchanged in this thread.", ephemeral=True
            )

        full_text = "\n".join(lines)

        # Manually paginate in case the transcript is long.
        chunk_size = 3900
        chunks = [full_text[i : i + chunk_size] for i in range(0, len(full_text), chunk_size)]

        for i, chunk in enumerate(chunks):
            embed = discord.Embed(
                title="Message Log" + (" (cont.)" if i else ""),
                description=chunk,
                color=bot.main_color,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)


class LogButton(commands.Cog):
    """Registers the dynamic button pattern with the bot so it keeps
    working across restarts without needing to track individual messages."""

    def __init__(self, bot):
        self.bot = bot
        self.bot.add_dynamic_items(LogRequestButton)


async def setup(bot):
    await bot.add_cog(LogButton(bot))
