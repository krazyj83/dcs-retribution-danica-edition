"""A turn report as Discord text, for the "Copy for Discord" button.

    **Operation Danica – Turn 5**  (12 Jun 1985 14:00)
    ```
    Losses            Own  Enemy
    Aircraft            1      5
    Ground objects      0      3
    ```
    **Logistics:** 412 fuel used · 26 weapons used · 2 deliveries
    **Captures and convoys**
    - Kobuleti captured by BLUEFOR

Discord limits a message to 2,000 characters, so long reports are split into
parts at block boundaries (a table or section is never cut in half unless it
is longer than a whole message on its own).
"""

from __future__ import annotations

import re
from typing import Any, List, Optional

from game.logistics.turn_report import LOSS_LABELS, SECTIONS, TurnReport

#: Discord's message limit for normal accounts.
DISCORD_LIMIT = 2000

_MARKDOWN = re.compile(r"([\\*_~|`>])")


def _escape(text: str) -> str:
    """Stop report text from turning into Discord formatting."""
    return _MARKDOWN.sub(r"\\\1", text)


def _losses_block(report: TurnReport) -> str:
    blue = report.losses.get("blue", {})
    red = report.losses.get("red", {})
    rows = [
        (label, blue.get(label, 0), red.get(label, 0))
        for label in LOSS_LABELS.values()
        if blue.get(label, 0) or red.get(label, 0)
    ]
    if not rows:
        return "No losses on either side."
    width = max(len("Losses"), *(len(label) for label, _, _ in rows))
    lines = [f"{'Losses':<{width}}  {'Own':>4}  {'Enemy':>5}"]
    lines += [f"{label:<{width}}  {b:>4}  {r:>5}" for label, b, r in rows]
    return "```\n" + "\n".join(lines) + "\n```"


def _activity_line(stats: Any) -> Optional[str]:
    """One line from the Campaign tab's numbers for the turn, if any."""
    if stats is None:
        return None
    parts = []
    if stats.fuel_used:
        parts.append(f"{stats.fuel_used:.0f} fuel used")
    if stats.weapons_used:
        parts.append(f"{stats.weapons_used} weapons used")
    if stats.stock_lost:
        parts.append(f"{stats.stock_lost:.0f} stock lost to strikes")
    if stats.transfers_delivered:
        parts.append(f"{stats.transfers_delivered} deliveries")
    if stats.transfers_lost:
        parts.append(f"{stats.transfers_lost} transfers lost")
    if not parts:
        return None
    return "**Logistics:** " + " · ".join(parts)


def summary_blocks(
    report: TurnReport, campaign_name: str = "", stats: Any = None
) -> List[str]:
    """The summary as blocks: title, losses, logistics line, one per section."""
    title = f"Turn {report.turn}"
    if campaign_name:
        title = f"{_escape(campaign_name)} – {title}"
    head = f"**{title}**"
    if report.date:
        head += f"  ({_escape(report.date)})"
    blocks = [head, _losses_block(report)]
    activity = _activity_line(stats)
    if activity:
        blocks.append(activity)
    for key, section_title in SECTIONS.items():
        lines = report.sections.get(key)
        if lines:
            body = "\n".join(f"- {_escape(line)}" for line in lines)
            blocks.append(f"**{section_title}**\n{body}")
    return blocks


def _split_block(block: str, limit: int) -> List[str]:
    """A block longer than one message, cut at line ends."""
    pieces: List[str] = []
    current = ""
    for line in block.split("\n"):
        if len(line) > limit:  # a single giant line: hard cut
            if current:
                pieces.append(current)
                current = ""
            while len(line) > limit:
                pieces.append(line[:limit])
                line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            pieces.append(current)
            current = line
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def split_for_discord(blocks: List[str], limit: int = DISCORD_LIMIT) -> List[str]:
    """Pack blocks into as few messages as fit, keeping blocks whole."""
    messages: List[str] = []
    current = ""
    for block in blocks:
        for piece in [block] if len(block) <= limit else _split_block(block, limit):
            candidate = f"{current}\n\n{piece}" if current else piece
            if len(candidate) > limit:
                messages.append(current)
                current = piece
            else:
                current = candidate
    if current:
        messages.append(current)
    return messages


def discord_messages(
    report: TurnReport,
    campaign_name: str = "",
    stats: Any = None,
    limit: int = DISCORD_LIMIT,
) -> List[str]:
    """The report as one or more Discord messages, ready to paste."""
    return split_for_discord(summary_blocks(report, campaign_name, stats), limit)


def stats_for_turn(logistics: Any, turn: int) -> Any:
    """The Campaign tab's numbers for a turn, or None."""
    return getattr(logistics, "_turn_stats", {}).get(turn)
