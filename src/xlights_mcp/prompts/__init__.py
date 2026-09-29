"""MCP prompt templates; the text lives in Markdown files next to this module."""

from __future__ import annotations

from pathlib import Path

_SEQUENCE_SONG = Path(__file__).with_name("sequence_song.md")

_WITH_REFERENCE = (
    "Call `profile_sequence` with `xsq_path` = `{reference}`, a hand-made sequence from this show. "
    "Use it as the target style:\n"
    "- `lit_at_once`: how many elements are lit together;\n"
    "- `dark_share`: how often the show goes dark;\n"
    "- `parent_lit_with_contained`: how often a parent group is a base under its children;\n"
    "- per-element layers and effect lengths: whether groups or single props carry the effects."
)
_WITHOUT_REFERENCE = (
    "This show has no hand-made sequence to learn from (check `list_sequences` for one with "
    "`generated: false` if the user names one). Aim for what hand-made sequences typically do:\n"
    "- a median of 2–5 elements lit at once;\n"
    "- under 5% of the song fully dark;\n"
    "- groups carrying most effects, with single props only for accents;\n"
    "- no overlaps within a layer."
)


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" if line.strip() else ">" for line in text.strip().splitlines())


def render_sequence_song(mp3_path: str, reference: str | None, show_notes: str | None) -> str:
    """The sequence_song playbook for a song, a reference sequence and the show's notes."""
    notes = (
        f"\n### Show notes\n\nThe show folder's `.claude/CLAUDE.md` says the following; follow it:\n\n{_quote(show_notes)}\n"
        if show_notes and show_notes.strip() else ""
    )
    return (
        _SEQUENCE_SONG.read_text(encoding="utf-8")
        .replace("{{mp3_path}}", mp3_path)
        .replace("{{reference_step}}", _WITH_REFERENCE.format(reference=reference) if reference else _WITHOUT_REFERENCE)
        .replace("{{show_notes}}", notes)
    )
