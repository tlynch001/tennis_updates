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

    intro = rng.choice(fp.AMERICA_FAVORITE_INTROS)
    label = rng.choice(fp.AMERICA_FAVORITE_LABELS)
    intro_sentence = f"{intro} {label}, {featured.name}."

    status_sentence = _status_sentence(featured, top_n, rng)

    parts = [_finish(intro_sentence), _finish(status_sentence)]

    match_sentence = _match_sentence(featured, top_n, rng)
    if match_sentence:
        parts.append(_finish(match_sentence))

    if featured.rank != 1 and rng.random() < _HEARTS_JOKE_PROBABILITY:
        hearts = rng.choice(fp.AMERICA_FAVORITE_HEARTS).format(rank=featured.rank)
        parts.append(_finish(f"And {hearts}"))

    return " ".join(parts)


def _status_sentence(featured: FeaturedPlayerReport, top_n: int, rng: random.Random) -> str:
    assert featured.rank is not None  # guarded by build_segment

    if featured.rank == 1:
        tier_phrase = rng.choice(fp.AMERICA_FAVORITE_NUMBER_ONE)
        return f"{featured.name} sits at the very top of the rankings at world number one - {tier_phrase}"

    movement_pool = _MOVEMENT_FRAGMENTS.get(featured.movement, fp.AMERICA_FAVORITE_MOVEMENT_UNKNOWN)  # type: ignore[arg-type]
    movement_fragment = rng.choice(movement_pool).format(rank=featured.rank)

    if featured.rank <= top_n:
        tier_phrase = rng.choice(fp.AMERICA_FAVORITE_ARRIVED).format(n=top_n)
    else:
        tier_phrase = rng.choice(fp.AMERICA_FAVORITE_PURSUIT).format(n=top_n)

    return f"{featured.name} is {movement_fragment}, and {tier_phrase}"


def _match_sentence(featured: FeaturedPlayerReport, top_n: int, rng: random.Random) -> str | None:
    favorite = rng.choice(fp.AMERICA_FAVORITE_LABELS)

    if featured.match_error:
        return rng.choice(fp.AMERICA_FAVORITE_MATCH_UNKNOWN)

    if featured.match is None:
        return rng.choice(fp.AMERICA_FAVORITE_NO_MATCH).format(favorite=favorite, name=featured.name)

    match = featured.match
    if match.won:
        return rng.choice(fp.AMERICA_FAVORITE_WIN).format(
            favorite=favorite,
            name=featured.name,
            opponent=match.opponent,
            score=match.score,
            tournament=match.tournament,
            round=match.round,
        )

    base = rng.choice(fp.AMERICA_FAVORITE_LOSS).format(
        favorite=favorite,
        name=featured.name,
        opponent=match.opponent,
        score=match.score,
        tournament=match.tournament,
        round=match.round,
    )
    support = rng.choice(fp.AMERICA_FAVORITE_LOSS_SUPPORT).format(favorite=favorite, n=top_n)
    return f"{_finish(base)} {support}"
