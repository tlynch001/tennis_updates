"""Maps ElevenLabs' character-level TTS alignment onto the report's
structure (intro / each Top N player / featured player / sign-off), so the
video assembler can size each slide to the actual spoken duration of its
corresponding narration instead of a fixed guess.

## Where the alignment comes from

:class:`~wta_daily.voice.elevenlabs_provider.ElevenLabsVoiceSynthesizer`
uses ElevenLabs' ``.../with-timestamps`` endpoint (see the README's "Slide
timing synchronization" section for the full investigation of available
options) - the *same* text-to-speech request already being made, just
requesting the timed variant of it, so this never costs an extra API call
or extra credits. That response includes a ``characters`` array and
matching ``character_start_times_seconds``/``character_end_times_seconds``
arrays for the exact text ElevenLabs was asked to speak - i.e. exactly
``script.txt``'s own characters, in order.

## What this module does with it

:func:`compute_segment_timings` splits ``script.txt`` into its paragraphs,
matches each non-intro/non-closer paragraph to the player (or featured
player) whose name it mentions, in the same order they appear in the
report, and returns one :class:`NarrationSegment` per visual the video
should show - never per raw paragraph, since an unmatched paragraph (e.g.
the template generator's length-padding filler sentence) is folded into
the segment before it rather than becoming its own cut.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wta_daily.models import DailyReport

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NarrationSegment:
    """One contiguous stretch of narration mapped to one visual.

    ``kind`` is one of ``"intro"``, ``"player"``, ``"featured"``, or
    ``"closer"``. ``rank`` is only set for ``kind == "player"``.
    """

    kind: str
    label: str
    start_seconds: float
    end_seconds: float
    rank: int | None = None

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "rank": self.rank,
            "start_seconds": round(self.start_seconds, 3),
            "end_seconds": round(self.end_seconds, 3),
            "duration_seconds": round(self.duration_seconds, 3),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NarrationSegment:
        return cls(
            kind=str(data["kind"]),
            label=str(data["label"]),
            start_seconds=float(data["start_seconds"]),
            end_seconds=float(data["end_seconds"]),
            rank=data.get("rank"),
        )


def _character_time(
    offset: int, start_times: list[float], end_times: list[float], *, is_end: bool
) -> float:
    """Look up the start/end time of the character at ``offset``, clamping
    to the nearest available character for an offset at or past the end of
    the alignment (e.g. the very last paragraph's closing offset)."""

    times = end_times if is_end else start_times
    if not times:
        return 0.0
    index = min(max(offset, 0), len(times) - 1)
    return times[index]


def _split_paragraphs(script_text: str) -> list[tuple[int, int, str]]:
    """Return ``(start_offset, end_offset, text)`` for every non-blank,
    blank-line-separated paragraph in ``script_text``, in order.

    Offsets are computed by direct arithmetic (not a text search), since
    ``"\\n\\n".join(script_text.split("\\n\\n")) == script_text`` always
    holds - each piece immediately follows the previous one plus the
    2-character separator, so this is exact regardless of repeated or
    empty paragraph text.
    """

    paragraphs: list[tuple[int, int, str]] = []
    cursor = 0
    for raw_paragraph in script_text.split("\n\n"):
        start = cursor
        stripped = raw_paragraph.strip()
        if stripped:
            # Point at the stripped text's real position, not the raw
            # (possibly newline-padded) slice.
            inner_start = start + (len(raw_paragraph) - len(raw_paragraph.lstrip()))
            paragraphs.append((inner_start, inner_start + len(stripped), stripped))
        cursor = start + len(raw_paragraph) + 2  # skip the "\n\n" separator
    return paragraphs


def compute_segment_timings(
    report: DailyReport,
    script_text: str,
    alignment_characters: list[str],
    alignment_start_times: list[float],
    alignment_end_times: list[float],
) -> list[NarrationSegment]:
    """Compute one :class:`NarrationSegment` per visual, from ElevenLabs'
    character alignment for ``script_text``.

    Returns an empty list - never raises - if ``script_text`` doesn't look
    like it has the expected paragraph structure (fewer than 2 paragraphs),
    so a caller can treat "no usable timing" as a simple, uniform fallback
    condition alongside "no timing file at all".
    """

    paragraphs = _split_paragraphs(script_text)
    if len(paragraphs) < 2:
        return []

    # Expected labels in the exact order the template/openai generators are
    # instructed to produce them: every Top N player, then the featured
    # player if present - see wta_daily/scripts_gen/template_generator.py
    # and wta_daily/scripts_gen/openai_generator.py's system prompt.
    expected: list[tuple[str, str, int | None]] = [
        ("player", p.name, p.rank) for p in report.players
    ]
    if report.featured_player is not None and report.featured_player.rank is not None:
        expected.append(("featured", report.featured_player.name, None))

    def _char_offset_seconds(offset: int, *, is_end: bool) -> float:
        return _character_time(offset, alignment_start_times, alignment_end_times, is_end=is_end)

    segments: list[NarrationSegment] = []
    expected_index = 0
    # The first paragraph is always the intro/greeting; the last is always
    # the sign-off - true for both the template generator (see its
    # module docstring) and the LLM prompt used by the openai generator.
    intro_start, intro_end, _ = paragraphs[0]
    segments.append(
        NarrationSegment(
            kind="intro",
            label="intro",
            start_seconds=_char_offset_seconds(intro_start, is_end=False),
            end_seconds=_char_offset_seconds(intro_end, is_end=True),
        )
    )

    for start, end, text in paragraphs[1:-1]:
        if expected_index < len(expected) and expected[expected_index][1] in text:
            kind, label, rank = expected[expected_index]
            end_seconds = _char_offset_seconds(end, is_end=True)
            if segments and segments[-1].kind in ("player", "featured"):
                # Consecutive matched segments are contiguous - the
                # previous one's end is this one's start, so there's no
                # gap even if the alignment has a tiny inter-paragraph
                # pause that would otherwise show up as a hole.
                start_seconds = segments[-1].end_seconds
            else:
                start_seconds = _char_offset_seconds(start, is_end=False)
            segments.append(
                NarrationSegment(
                    kind=kind,
                    label=label,
                    rank=rank,
                    start_seconds=start_seconds,
                    end_seconds=end_seconds,
                )
            )
            expected_index += 1
        elif segments:
            # An unmatched middle paragraph (e.g. the template generator's
            # length-padding filler sentence) - extend the previous
            # segment to cover it rather than inventing a new visual.
            segments[-1] = NarrationSegment(
                kind=segments[-1].kind,
                label=segments[-1].label,
                rank=segments[-1].rank,
                start_seconds=segments[-1].start_seconds,
                end_seconds=_char_offset_seconds(end, is_end=True),
            )

    closer_start, closer_end, _ = paragraphs[-1]
    closer_start_seconds = (
        segments[-1].end_seconds if segments else _char_offset_seconds(closer_start, is_end=False)
    )
    # Extend the very last segment to the true end of the audio (the last
    # aligned character's end time), not just this paragraph's own text
    # offset, so the video never falls short of the narration - see
    # ffmpeg_assembler.py's docstring for why a short silent video would
    # otherwise truncate the audio.
    total_duration = alignment_end_times[-1] if alignment_end_times else closer_start_seconds
    segments.append(
        NarrationSegment(
            kind="closer",
            label="closer",
            start_seconds=closer_start_seconds,
            end_seconds=max(total_duration, _char_offset_seconds(closer_end, is_end=True)),
        )
    )

    return [s for s in segments if s.duration_seconds >= 0]


def write_timing_file(path: Path, segments: list[NarrationSegment]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"segments": [s.to_dict() for s in segments]}
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    tmp_path.replace(path)


def read_timing_file(path: Path) -> list[NarrationSegment] | None:
    """Read a previously-written timing file, or ``None`` if it's missing,
    empty, or unreadable - never raises, since falling back to fixed-
    duration slides is always a safe, valid alternative."""

    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        segments = [NarrationSegment.from_dict(s) for s in payload.get("segments", [])]
    except (json.JSONDecodeError, OSError, KeyError, ValueError, TypeError) as exc:
        logger.warning("Could not read narration timing file %s: %s", path, exc)
        return None
    return segments or None
