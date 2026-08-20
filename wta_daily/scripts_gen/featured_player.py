"""Builds the narration paragraph for the recurring featured-player segment.

Kept separate from :mod:`wta_daily.scripts_gen.template_generator`'s main
Top N loop so "who is this about and what's the running joke" (this module)
stays decoupled from "how do we assemble a full narration script" (the
generator, which just calls :func:`build_segment` once, after the Top N
coverage and before the sign-off). See
:mod:`wta_daily.scripts_gen.featured_player_phrases` for the actual wording
and the README's "Featured player" section for the tone this is aiming for:
a short (1-3 sentence), affectionate inside joke, not a comedy routine -
and every number in it is real.
"""

from __future__ import annotations

import logging
import random

from wta_daily.models import FeaturedPlayerReport, Movement
from wta_daily.scripts_gen import featured_player_phrases as fp
from wta_daily.scripts_gen.name_utils import first_name as _first_name
from wta_daily.scripts_gen.phrase_utils import format_score_for_narration
from wta_daily.scripts_gen.tournament_status_narration import (
    build_tournament_status_sentence,
    supersedes_inactivity_narration,
)

logger = logging.getLogger(__name__)

#: How often the "#1 in our hearts" bit surfaces - deliberately well under
#: half the time, so it reads as an occasional callback rather than a daily
#: refrain (see the phrase module's docstring). Never used once she's
#: genuinely reached No. 1, where the joke's premise no longer applies.
_HEARTS_JOKE_PROBABILITY = 0.3

_MOVEMENT_FRAGMENTS: dict[Movement, list[str]] = {
    Movement.UP: fp.AMERICA_FAVORITE_MOVEMENT_UP,
    Movement.DOWN: fp.AMERICA_FAVORITE_MOVEMENT_DOWN,
    Movement.SAME: fp.AMERICA_FAVORITE_MOVEMENT_SAME,
    Movement.NEW: fp.AMERICA_FAVORITE_MOVEMENT_NEW,
    Movement.UNKNOWN: fp.AMERICA_FAVORITE_MOVEMENT_UNKNOWN,
}

#: Personalities this module actually knows how to narrate. A config with
#: an unrecognized `tagline` still gets a segment (falls back to this one,
#: with a logged warning) rather than silently producing nothing.
_KNOWN_TAGLINES = {"america_favorite"}


def _finish(sentence: str) -> str:
    """Ensure a sentence-final period and a capitalized first letter.

    Several phrase pools (e.g. the "favorite" labels) are written in
    lowercase because they're normally used mid-sentence, but some
    templates also start a *new* sentence with one - capitalizing here
    once, in the one place every sentence passes through, is simpler than
    tracking case per phrase pool.
    """

    finished = sentence if sentence.endswith((".", "!", "?")) else f"{sentence}."
    return finished[:1].upper() + finished[1:] if finished else finished


def _pick_unused_favorite_label(rng: random.Random, used: set[str]) -> str:
    """Draw an ``AMERICA_FAVORITE_LABELS`` phrase not already used
    elsewhere in this segment.

    Regression fix: this pool is drawn from independently for the intro
    sentence and (potentially twice more) for the match sentence, and a
    plain ``rng.choice`` per call had no memory of earlier picks - a real
    production script once said "the reigning champion of this show's
    affections" twice in three sentences purely by chance. Falls back to
    allowing a repeat only if every label has genuinely already been used
    (the pool has 9 entries; a segment never needs more than 3), so this
    can never raise even in a pathologically small/patched pool.
    """

    available = [label for label in fp.AMERICA_FAVORITE_LABELS if label not in used]
    choice = rng.choice(available or fp.AMERICA_FAVORITE_LABELS)
    used.add(choice)
    return choice


def build_segment(featured: FeaturedPlayerReport, *, top_n: int, rng: random.Random) -> str | None:
    """Return a short narration paragraph for ``featured``, or ``None``.

    Returns ``None`` whenever there isn't enough real information to say
    anything factual - specifically when ``featured.rank`` could not be
    determined this run. The rest of the pipeline still records that in
    ``report.json`` (via ``rank_error``); this function just declines to
    build a joke around a number it doesn't have, per the "never fabricate"
    rule that also governs the factual Top N coverage.
    """

    if featured.tagline not in _KNOWN_TAGLINES:
        logger.warning(
            "Featured player %s has an unrecognized tagline %r; using the "
            "default 'america_favorite' narration personality for her segment.",
            featured.name,
            featured.tagline,
        )

    if featured.rank is None:
        return None

    # Tracks every AMERICA_FAVORITE_LABELS phrase already used this
    # segment, so the intro and the match sentence never land on the same
    # joke twice - see _pick_unused_favorite_label's docstring.
    used_labels: set[str] = set()

    # The intro sentence is the one place her full name is used - every
    # sentence after this refers to her by first name instead, per the
    # general "introduce once, then use the first name naturally" rule
    # (see wta_daily.scripts_gen.name_utils).
    name = _first_name(featured.name)

    intro = rng.choice(fp.AMERICA_FAVORITE_INTROS)
    label = _pick_unused_favorite_label(rng, used_labels)
    intro_sentence = f"{intro} {label}, {featured.name}."

    status_sentence = _status_sentence(featured, top_n, rng, name)

    parts = [_finish(intro_sentence), _finish(status_sentence)]

    match_sentence = _match_sentence(featured, top_n, rng, used_labels, name)
    if match_sentence:
        parts.append(_finish(match_sentence))

    # Elimination/title context (see wta_daily.models.TournamentRunStatus)
    # uses exactly the same builder as the Top N narration - never a
    # duplicated or Emma-specific version of this logic - so it reads
    # like a factual aside within her otherwise lighthearted segment.
    tournament_status_sentence = build_tournament_status_sentence(
        featured.tournament_status, featured.name, rng, match=featured.match
    )
    if tournament_status_sentence:
        parts.append(tournament_status_sentence)

    if featured.rank != 1 and rng.random() < _HEARTS_JOKE_PROBABILITY:
        hearts = rng.choice(fp.AMERICA_FAVORITE_HEARTS).format(rank=featured.rank)
        parts.append(_finish(f"And {hearts}"))

    return " ".join(parts)


def _status_sentence(featured: FeaturedPlayerReport, top_n: int, rng: random.Random, name: str) -> str:
    assert featured.rank is not None  # guarded by build_segment

    if featured.rank == 1:
        tier_phrase = rng.choice(fp.AMERICA_FAVORITE_NUMBER_ONE)
        return f"{name} sits at the very top of the rankings at world number one - {tier_phrase}"

    movement_pool = _MOVEMENT_FRAGMENTS.get(featured.movement, fp.AMERICA_FAVORITE_MOVEMENT_UNKNOWN)  # type: ignore[arg-type]
    movement_fragment = rng.choice(movement_pool).format(rank=featured.rank)

    if featured.rank <= top_n:
        tier_phrase = rng.choice(fp.AMERICA_FAVORITE_ARRIVED).format(n=top_n)
    else:
        tier_phrase = rng.choice(fp.AMERICA_FAVORITE_PURSUIT).format(n=top_n)

    return f"{name} is {movement_fragment}, and {tier_phrase}"


def _match_sentence(
    featured: FeaturedPlayerReport, top_n: int, rng: random.Random, used_labels: set[str], name: str
) -> str | None:
    # Once we know her tournament run is already over (eliminated or
    # champion), generic "had the day off"/"result couldn't be
    # confirmed" filler about *yesterday specifically* reads as an odd
    # non-sequitur right next to that more important news - the
    # elimination/title context appended in build_segment takes
    # precedence instead. A genuine win/loss match result for the target
    # date is never suppressed by this - only this "nothing to say
    # either way" filler is. See
    # wta_daily.scripts_gen.tournament_status_narration.supersedes_inactivity_narration.
    superseded = supersedes_inactivity_narration(featured.tournament_status)

    if featured.match_error:
        return None if superseded else rng.choice(fp.AMERICA_FAVORITE_MATCH_UNKNOWN)

    if featured.match is None:
        if superseded:
            return None
        favorite = _pick_unused_favorite_label(rng, used_labels)
        return rng.choice(fp.AMERICA_FAVORITE_NO_MATCH).format(favorite=favorite, name=name)

    match = featured.match
    score = format_score_for_narration(match.score)
    if match.won:
        favorite = _pick_unused_favorite_label(rng, used_labels)
        return rng.choice(fp.AMERICA_FAVORITE_WIN).format(
            favorite=favorite,
            name=name,
            opponent=match.opponent,
            score=score,
            tournament=match.tournament,
            round=match.round,
        )

    # A loss sentence is composed of two clauses (the result, then a
    # supportive follow-up) that can *each* independently reference
    # AMERICA_FAVORITE_LABELS - drawing a fresh, not-yet-used label for
    # the second clause is what stops the exact same joke phrase from
    # appearing twice in two consecutive sentences (the reported
    # production bug). _finish() is applied to *both* clauses (not just
    # the first) so the seam between them is a real sentence boundary -
    # capitalized and punctuated - rather than "...7-5,6-2. a temporary
    # setback..." running two sentences together with a lowercase start.
    base_favorite = _pick_unused_favorite_label(rng, used_labels)
    base = rng.choice(fp.AMERICA_FAVORITE_LOSS).format(
        favorite=base_favorite,
        name=name,
        opponent=match.opponent,
        score=score,
        tournament=match.tournament,
        round=match.round,
    )
    support_favorite = _pick_unused_favorite_label(rng, used_labels)
    support = rng.choice(fp.AMERICA_FAVORITE_LOSS_SUPPORT).format(favorite=support_favorite, n=top_n)
    return f"{_finish(base)} {_finish(support)}"
