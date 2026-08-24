"""Weekly rankings-update narration.

Used when :attr:`TourProfile.emphasizes_weekly_ranking_movement` is true
(ATP v1). Movement comes from the application's stored snapshots via
:func:`wta_daily.movement.compute_movement` — never from a vendor
``movement`` field. WTA daily-show wording lives in
:mod:`wta_daily.scripts_gen.phrases` and is not used here.

Run a synthetic demo (does not touch ``data/atp``)::

    python -m wta_daily.scripts_gen.weekly_rankings_narration
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from wta_daily.config import ScriptConfig
from wta_daily.models import DailyReport, Movement, PlayerReport, RankingsDeparture
from wta_daily.scripts_gen.name_utils import first_name
from wta_daily.scripts_gen.phrase_utils import PhraseCycler
from wta_daily.tour import TourProfile, profile_for

_PLACE_WORDS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
}

_POINTS_GAP_NOTEWORTHY_THRESHOLD = 100
#: Official ranking-point change between lists that's worth saying out loud.
_POINTS_DELTA_NOTEWORTHY = 100

OPENERS = [
    "Hello and welcome to the {tour} Top {n} Rankings Update for {date}.",
    "Welcome to the {tour} Top {n} Rankings Update for {date}.",
    "It's time for this week's {tour} Top {n} Rankings Update, covering the official list for {date}.",
]

CLOSERS = [
    "That's this week's {tour} Top {n}. We'll see how the rankings change when the next official list is released.",  # noqa: E501
    "That wraps up this week's {tour} Top {n}. We'll be back when the next official rankings are published.",
    "That's the latest official {tour} Top {n}. We'll check the list again after the next ranking update.",
]

BASELINE_HEADLINES = [
    "This update sets the baseline for future weekly reports — here's the current official Top {n}.",
    "There's no previous snapshot to compare against yet, so this week's show is the starting Top {n}.",
    "This is the baseline {tour} Top {n} list; later updates will cover what changes from here.",
]

STEADY_HEADLINES = [
    "The Top {n} is unusually steady this week, with all {n} players holding their positions.",
    "There is no movement in this week's Top {n} — every player holds the same ranking as last week.",
    "A quiet week at the top: all {n} players remain exactly where they were.",
]

STEADY_RANKS_POINT_SHIFTS_HEADLINES = [
    "The Top {n} positions are unchanged this week, although several players saw meaningful changes to their ranking-point totals.",  # noqa: E501
    "Every player holds the same ranking as last week, but ranking-point totals still shifted on the new list.",  # noqa: E501
    "There is no change in the Top {n} order this week, though the point totals tell a different story.",
]

STEADY_RANKS_ONE_POINT_SHIFT_HEADLINES = [
    "The Top {n} positions are unchanged this week, although {name}'s ranking-point total shifted on the new list.",  # noqa: E501
    "Every player holds the same ranking as last week, but {name} saw a meaningful change in ranking points.",
]

LITTLE_MOVEMENT_HEADLINES = [
    "There is very little movement in this week's Top {n}, with {held} of the {n} players holding their positions.",  # noqa: E501
    "This week's Top {n} is mostly unchanged, aside from a few one-place shifts.",
]

BIGGEST_UP_HEADLINES = [
    "The biggest mover this week is {name}, who climbs {places} from number {previous_rank} to number {rank}.",  # noqa: E501
    "{name} makes the biggest move in this week's Top {n}, climbing {places} from number {previous_rank} to number {rank}.",  # noqa: E501
]

NEW_NUMBER_ONE_HEADLINES = [
    "{name} is the new world number 1 this week, moving up from number {previous_rank}.",
    "The biggest headline is at the top: {name} takes over at number 1 from number {previous_rank}.",
]

ENTRANT_HEADLINES = [
    "The biggest change this week is {name} moving into the Top {n} at number {rank}.",
]

PLAYER_UP = [
    "{name} climbs {places} from number {previous_rank} to number {rank} with {points} points.",
    "{name} moves up {places} to number {rank} with {points} points.",
    "{name} gains {places}, rising from number {previous_rank} to number {rank} with {points} points.",
    "{name} jumps {places} to number {rank} and now sits at {points} points.",
]

PLAYER_DOWN = [
    "{name} slips from number {previous_rank} to number {rank} with {points} points.",
    "{name} drops {places} to number {rank} with {points} points.",
    "{name} falls {places} to number {rank} with {points} points.",
    "{name} moves down {places} from number {previous_rank} to number {rank} with {points} points.",
]

PLAYER_SAME = [
    "{name} holds at number {rank} with {points} points.",
    "{name} remains number {rank} with {points} points.",
    "{name} stays at number {rank} with {points} points.",
    "{name} holds the number {rank} spot with {points} points.",
    "{name} remains in the number {rank} position with {points} points.",
]

#: Used when the headline already told this player's full movement story.
PLAYER_HEADLINE_FOLLOWUP = [
    "{name} is now number {rank} with {points} points.",
    "{name} now sits at number {rank} with {points} points.",
]

PLAYER_NUMBER_ONE_HOLD = [
    "{name} holds the number 1 ranking for another week with {points} points.",
    "{name} remains world number 1 with {points} points.",
    "{name} stays at number 1 this week with {points} points.",
]

PLAYER_ENTRANT = [
    "{name} moves into the Top {n} this week at number {rank} with {points} points.",
    "{name} enters the Top {n} at number {rank} with {points} points.",
]

PLAYER_BASELINE = [
    "{name} is number {rank} with {points} ranking points.",
    "{name} sits at number {rank} with {points} ranking points.",
    "{name} is ranked number {rank} with {points} ranking points.",
    "{name} comes in at number {rank} with {points} ranking points.",
]

DEPARTURE_LINES = [
    "{name} drops out of the Top {n} this week.",
    "Leaving the Top {n} this week is {name}.",
    "{name} is out of the Top {n} this week, last ranked number {previous_rank}.",
]

MULTI_DEPARTURE_LINES = [
    "Leaving the Top {n} this week: {names}.",
    "{names} drop out of the Top {n} this week.",
]

POINT_GAP_LINES = [
    "That keeps {object} just {gap} points behind {above_name} at number {rank_above}.",
    "It's a tight race: only {gap} points separate {object} from number {rank_above}.",
]

POINT_GAIN_CLAUSES = [
    ", gaining {delta} ranking points since last week's list",
    ", up {delta} points from the previous rankings",
    ", an increase of {delta} points from last week",
]

POINT_LOSS_CLAUSES = [
    ", losing {delta} ranking points since last week",
    ", down {delta} points from last week",
    ", a drop of {delta} points from last week's list",
]

POINT_UNCHANGED_CLAUSES = [
    ", unchanged from last week",
    ", {possessive} ranking-point total unchanged from last week",
]


@dataclass(frozen=True)
class WeeklyMovementSummary:
    """Facts derived from one rankings-only report's snapshot comparison."""

    is_baseline: bool
    movers_up: tuple[PlayerReport, ...]
    movers_down: tuple[PlayerReport, ...]
    unchanged: tuple[PlayerReport, ...]
    entrants: tuple[PlayerReport, ...]
    departed: tuple[RankingsDeparture, ...]
    biggest_up: PlayerReport | None
    biggest_down: PlayerReport | None
    number_one_changed: bool
    held_count: int
    tracked_n: int
    biggest_points_gain: PlayerReport | None
    biggest_points_loss: PlayerReport | None
    meaningful_point_changes: tuple[PlayerReport, ...]


def places_delta(player: PlayerReport) -> int | None:
    """Places gained (positive) or lost (negative) vs the previous snapshot.

    ``None`` when there is no previous rank to compare — first-run
    ``UNKNOWN`` or a genuine Top N entrant.
    """

    if player.previous_rank is None:
        return None
    return player.previous_rank - player.rank


def format_places(distance: int) -> str:
    """``4`` → ``"four places"``; ``1`` → ``"one place"``."""

    count = abs(int(distance))
    word = _PLACE_WORDS.get(count, str(count))
    unit = "place" if count == 1 else "places"
    return f"{word} {unit}"


def points_delta(player: PlayerReport) -> int | None:
    """Official ranking-point change vs the previous snapshot.

    ``None`` when there is no previous point total to compare — first-run
    ``UNKNOWN``, a genuine Top N entrant, or a missing historical value.
    This is a list-to-list delta, not points earned at a tournament.
    """

    if player.previous_points is None:
        return None
    return player.points - player.previous_points


def format_points_delta(distance: int) -> str:
    """``430`` → ``"430"``; ``1500`` → ``"1,500"``."""

    return f"{abs(int(distance)):,}"


def summarize_weekly_movement(report: DailyReport) -> WeeklyMovementSummary:
    players = list(report.players)
    n = len(players)
    is_baseline = bool(players) and all(player.movement is Movement.UNKNOWN for player in players)
    movers_up = tuple(p for p in players if p.movement is Movement.UP)
    movers_down = tuple(p for p in players if p.movement is Movement.DOWN)
    unchanged = tuple(p for p in players if p.movement is Movement.SAME)
    entrants = tuple(p for p in players if p.movement is Movement.NEW)
    departed = tuple(sorted(report.departed_players, key=lambda item: item.previous_rank))

    def _up_key(player: PlayerReport) -> tuple[int, int]:
        delta = places_delta(player)
        gained = delta if delta is not None and delta > 0 else 0
        return (gained, -player.rank)

    biggest_up = max(movers_up, key=_up_key) if movers_up else None

    def _down_key(player: PlayerReport) -> tuple[int, int]:
        delta = places_delta(player)
        lost = -delta if delta is not None and delta < 0 else 0
        return (lost, player.rank)

    biggest_down = max(movers_down, key=_down_key) if movers_down else None
    number_one = players[0] if players else None
    number_one_changed = bool(
        number_one is not None
        and number_one.rank == 1
        and number_one.previous_rank is not None
        and number_one.previous_rank != 1
        and number_one.movement is not Movement.UNKNOWN
    )

    def _gain_key(player: PlayerReport) -> tuple[int, int]:
        delta = points_delta(player) or 0
        return (delta, -player.rank)

    def _loss_key(player: PlayerReport) -> tuple[int, int]:
        delta = points_delta(player) or 0
        return (-delta, -player.rank)

    gainers = [p for p in players if (points_delta(p) or 0) > 0]
    losers = [p for p in players if (points_delta(p) or 0) < 0]
    biggest_points_gain = max(gainers, key=_gain_key) if gainers else None
    biggest_points_loss = max(losers, key=_loss_key) if losers else None
    meaningful_point_changes = tuple(
        p
        for p in players
        if (delta := points_delta(p)) is not None and abs(delta) >= _POINTS_DELTA_NOTEWORTHY
    )
    return WeeklyMovementSummary(
        is_baseline=is_baseline,
        movers_up=movers_up,
        movers_down=movers_down,
        unchanged=unchanged,
        entrants=entrants,
        departed=departed,
        biggest_up=biggest_up,
        biggest_down=biggest_down,
        number_one_changed=number_one_changed,
        held_count=len(unchanged),
        tracked_n=n,
        biggest_points_gain=biggest_points_gain,
        biggest_points_loss=biggest_points_loss,
        meaningful_point_changes=meaningful_point_changes,
    )


def generate_weekly_rankings_script(
    report: DailyReport,
    script_config: ScriptConfig | None = None,
    profile: TourProfile | None = None,
) -> str:
    """Build a movement-centric weekly rankings script from ``report``."""

    config = script_config or ScriptConfig()
    resolved_profile = profile or profile_for(report.tour)
    rng = random.Random(f"{report.report_date.isoformat()}:{report.tour}:weekly")
    phrase_rng = random.Random(f"{report.report_date.isoformat()}:{report.tour}:weekly:phrases")
    n = len(report.players)
    title_date = report.ranking_date or report.report_date
    date_str = f"{title_date:%A, %B} {title_date.day}, {title_date.year}"
    summary = summarize_weekly_movement(report)

    opener = resolved_profile.format(rng.choice(OPENERS), n=n, date=date_str)
    headline = _headline(summary, resolved_profile, rng)
    featured = _headline_featured_player(summary)
    cyclers = {
        "same": PhraseCycler(PLAYER_SAME, phrase_rng),
        "up": PhraseCycler(PLAYER_UP, phrase_rng),
        "down": PhraseCycler(PLAYER_DOWN, phrase_rng),
        "followup": PhraseCycler(PLAYER_HEADLINE_FOLLOWUP, phrase_rng),
        "entrant": PhraseCycler(PLAYER_ENTRANT, phrase_rng),
        "number_one_hold": PhraseCycler(PLAYER_NUMBER_ONE_HOLD, phrase_rng),
        "points_gain": PhraseCycler(POINT_GAIN_CLAUSES, phrase_rng),
        "points_loss": PhraseCycler(POINT_LOSS_CLAUSES, phrase_rng),
        "points_same": PhraseCycler(POINT_UNCHANGED_CLAUSES, phrase_rng),
    }
    player_lines: list[str] = []
    previous_verb: str | None = None
    for index, player in enumerate(report.players):
        line = _player_sentence(
            player,
            report,
            index,
            summary,
            resolved_profile,
            cyclers,
            featured,
            previous_verb,
        )
        player_lines.append(line)
        previous_verb = _leading_verb(line, player.name)
    departure = _departure_sentence(summary, resolved_profile, rng)
    closer = resolved_profile.format(rng.choice(CLOSERS), n=n)

    paragraphs = [opener]
    if headline:
        paragraphs.append(headline)
    paragraphs.extend(player_lines)
    if departure:
        paragraphs.append(departure)
    body = "\n\n".join(paragraphs)
    body = _pad_if_short(body, config, resolved_profile, rng)
    return f"{body}\n\n{closer}"


def _headline(summary: WeeklyMovementSummary, profile: TourProfile, rng: random.Random) -> str:
    n = summary.tracked_n
    if summary.is_baseline:
        return profile.format(rng.choice(BASELINE_HEADLINES), n=n)
    if (
        not summary.movers_up
        and not summary.movers_down
        and not summary.entrants
        and not summary.departed
    ):
        if len(summary.meaningful_point_changes) >= 2:
            return profile.format(rng.choice(STEADY_RANKS_POINT_SHIFTS_HEADLINES), n=n)
        if len(summary.meaningful_point_changes) == 1:
            changed = summary.meaningful_point_changes[0]
            return profile.format(
                rng.choice(STEADY_RANKS_ONE_POINT_SHIFT_HEADLINES),
                n=n,
                name=changed.name,
            )
        return profile.format(rng.choice(STEADY_HEADLINES), n=n)

    biggest = summary.biggest_up
    biggest_gain = places_delta(biggest) if biggest is not None else None
    if summary.number_one_changed and report_player_is_number_one_mover(summary):
        number_one = next(player for player in (summary.movers_up + summary.unchanged) if player.rank == 1)
        if number_one.previous_rank is not None:
            return profile.format(
                rng.choice(NEW_NUMBER_ONE_HEADLINES),
                name=number_one.name,
                previous_rank=number_one.previous_rank,
                n=n,
            )
    if biggest is not None and biggest_gain is not None and biggest_gain >= 2:
        return profile.format(
            rng.choice(BIGGEST_UP_HEADLINES),
            name=biggest.name,
            places=format_places(biggest_gain),
            previous_rank=biggest.previous_rank,
            rank=biggest.rank,
            n=n,
        )
    if summary.entrants and not summary.movers_up:
        entrant = summary.entrants[0]
        return profile.format(
            rng.choice(ENTRANT_HEADLINES),
            name=entrant.name,
            rank=entrant.rank,
            n=n,
        )
    return profile.format(
        rng.choice(LITTLE_MOVEMENT_HEADLINES),
        n=n,
        held=summary.held_count,
    )


def report_player_is_number_one_mover(summary: WeeklyMovementSummary) -> bool:
    return any(player.rank == 1 and player.movement is Movement.UP for player in summary.movers_up)


def _headline_featured_player(summary: WeeklyMovementSummary) -> PlayerReport | None:
    """The player whose full movement story the headline already told, if any."""

    if summary.is_baseline:
        return None
    if (
        not summary.movers_up
        and not summary.movers_down
        and not summary.entrants
        and not summary.departed
    ):
        return None
    if summary.number_one_changed and report_player_is_number_one_mover(summary):
        return next(player for player in summary.movers_up if player.rank == 1)
    biggest = summary.biggest_up
    biggest_gain = places_delta(biggest) if biggest is not None else None
    if biggest is not None and biggest_gain is not None and biggest_gain >= 2:
        return biggest
    if summary.entrants and not summary.movers_up:
        return summary.entrants[0]
    return None


def _leading_verb(sentence: str, full_name: str) -> str:
    """First spoken verb after the player's name, for adjacent-line variety."""

    for prefix in (full_name, first_name(full_name)):
        if sentence.startswith(prefix + " "):
            rest = sentence[len(prefix) + 1 :]
            return rest.split()[0].lower() if rest.split() else ""
    return ""


def _next_phrase(cycler: PhraseCycler, *, avoid_verb: str | None, pool_size: int) -> str:
    phrase = cycler.next()
    if not avoid_verb:
        return phrase
    for _ in range(pool_size - 1):
        verb = phrase.removeprefix("{name} ").split()[0].lower()
        if verb != avoid_verb:
            return phrase
        phrase = cycler.next()
    return phrase


def _should_narrate_points_delta(player: PlayerReport, summary: WeeklyMovementSummary) -> bool:
    """Whether this rundown line should mention the week-to-week point change."""

    if summary.is_baseline or player.movement is Movement.UNKNOWN:
        return False
    delta = points_delta(player)
    if delta is None:
        return False
    if player.rank == 1 and delta == 0:
        return True
    if player.movement in (Movement.UP, Movement.DOWN) and delta != 0:
        return True
    if player.movement is Movement.SAME and abs(delta) >= _POINTS_DELTA_NOTEWORTHY:
        return True
    if (
        summary.biggest_points_gain is not None
        and summary.biggest_points_gain.player_id == player.player_id
        and delta >= _POINTS_DELTA_NOTEWORTHY
    ):
        return True
    if (
        summary.biggest_points_loss is not None
        and summary.biggest_points_loss.player_id == player.player_id
        and delta <= -_POINTS_DELTA_NOTEWORTHY
    ):
        return True
    return False


def _points_clause_conflicts(sentence: str, clause: str) -> bool:
    lowered_sentence = sentence.lower()
    lowered_clause = clause.lower()
    if "gain" in lowered_sentence and "gain" in lowered_clause:
        return True
    if "increas" in lowered_sentence and "increas" in lowered_clause:
        return True
    if any(word in lowered_sentence for word in ("drop", "drops", "losing", "lost")) and any(
        word in lowered_clause for word in ("drop", "losing")
    ):
        return True
    return False


def _next_points_clause(
    cycler: PhraseCycler, sentence: str, pool_size: int, profile: TourProfile, delta: int
) -> str:
    formatted_delta = format_points_delta(delta)
    phrase = cycler.next()
    for _ in range(pool_size):
        clause = profile.format(phrase, delta=formatted_delta)
        if not _points_clause_conflicts(sentence, clause):
            return clause
        phrase = cycler.next()
    return profile.format(phrase, delta=formatted_delta)


def _attach_clause(sentence: str, clause: str) -> str:
    if sentence.endswith("."):
        return sentence[:-1] + clause + "."
    return sentence + clause


def _with_points_delta(
    sentence: str,
    player: PlayerReport,
    summary: WeeklyMovementSummary,
    profile: TourProfile,
    cyclers: dict[str, PhraseCycler],
) -> str:
    if not _should_narrate_points_delta(player, summary):
        return sentence
    delta = points_delta(player)
    if delta is None:
        return sentence
    if delta > 0:
        clause = _next_points_clause(
            cyclers["points_gain"], sentence, len(POINT_GAIN_CLAUSES), profile, delta
        )
    elif delta < 0:
        clause = _next_points_clause(
            cyclers["points_loss"], sentence, len(POINT_LOSS_CLAUSES), profile, delta
        )
    else:
        clause = profile.format(cyclers["points_same"].next())
    return _attach_clause(sentence, clause)


def _player_sentence(
    player: PlayerReport,
    report: DailyReport,
    index: int,
    summary: WeeklyMovementSummary,
    profile: TourProfile,
    cyclers: dict[str, PhraseCycler],
    featured: PlayerReport | None,
    previous_verb: str | None,
) -> str:
    points = f"{player.points:,}"
    if summary.is_baseline or player.movement is Movement.UNKNOWN:
        template = PLAYER_BASELINE[index % len(PLAYER_BASELINE)]
        return profile.format(template, name=player.name, rank=player.rank, points=points)

    if featured is not None and player.player_id == featured.player_id:
        # Headline already used the full name and the movement story.
        sentence = profile.format(
            cyclers["followup"].next(),
            name=first_name(player.name),
            rank=player.rank,
            points=points,
        )
        return _with_points_delta(sentence, player, summary, profile, cyclers)

    if player.movement is Movement.NEW:
        return profile.format(
            _next_phrase(
                cyclers["entrant"],
                avoid_verb=previous_verb,
                pool_size=len(PLAYER_ENTRANT),
            ),
            name=player.name,
            rank=player.rank,
            points=points,
            n=summary.tracked_n,
        )

    place_delta = places_delta(player)
    if player.movement is Movement.UP and place_delta is not None:
        sentence = profile.format(
            _next_phrase(
                cyclers["up"],
                avoid_verb=previous_verb,
                pool_size=len(PLAYER_UP),
            ),
            name=player.name,
            places=format_places(place_delta),
            previous_rank=player.previous_rank,
            rank=player.rank,
            points=points,
        )
        return _with_points_delta(sentence, player, summary, profile, cyclers)

    if player.movement is Movement.DOWN and place_delta is not None:
        sentence = profile.format(
            _next_phrase(
                cyclers["down"],
                avoid_verb=previous_verb,
                pool_size=len(PLAYER_DOWN),
            ),
            name=player.name,
            places=format_places(place_delta),
            previous_rank=player.previous_rank,
            rank=player.rank,
            points=points,
        )
        return _with_points_delta(sentence, player, summary, profile, cyclers)

    if player.rank == 1:
        sentence = profile.format(
            _next_phrase(
                cyclers["number_one_hold"],
                avoid_verb=previous_verb,
                pool_size=len(PLAYER_NUMBER_ONE_HOLD),
            ),
            name=player.name,
            points=points,
        )
    else:
        sentence = profile.format(
            _next_phrase(
                cyclers["same"],
                avoid_verb=previous_verb,
                pool_size=len(PLAYER_SAME),
            ),
            name=player.name,
            rank=player.rank,
            points=points,
        )
    sentence = _with_points_delta(sentence, player, summary, profile, cyclers)
    gap = _points_gap_clause(player, report, index, profile)
    if gap:
        sentence += f" {gap}"
    return sentence


def _points_gap_clause(
    player: PlayerReport,
    report: DailyReport,
    index: int,
    profile: TourProfile,
) -> str | None:
    if index == 0:
        return None
    above = report.players[index - 1]
    gap = above.points - player.points
    if gap <= 0 or gap > _POINTS_GAP_NOTEWORTHY_THRESHOLD:
        return None
    if player.movement is not Movement.SAME:
        return None
    return profile.format(
        POINT_GAP_LINES[index % len(POINT_GAP_LINES)],
        gap=f"{gap:,}",
        above_name=above.name,
        rank_above=above.rank,
    )


def _departure_sentence(
    summary: WeeklyMovementSummary, profile: TourProfile, rng: random.Random
) -> str | None:
    if not summary.departed:
        return None
    if len(summary.departed) == 1:
        left = summary.departed[0]
        return profile.format(
            rng.choice(DEPARTURE_LINES),
            name=left.name,
            previous_rank=left.previous_rank,
            n=summary.tracked_n,
        )
    names = _join_names([item.name for item in summary.departed])
    return profile.format(rng.choice(MULTI_DEPARTURE_LINES), names=names, n=summary.tracked_n)


def _join_names(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{', '.join(names[:-1])}, and {names[-1]}"


def _pad_if_short(
    body: str, config: ScriptConfig, profile: TourProfile, rng: random.Random
) -> str:
    from wta_daily.scripts_gen import phrases

    target_words = config.words_per_minute * config.target_minutes_low
    if len(body.split()) >= target_words:
        return body
    return body + "\n\n" + profile.format(rng.choice(phrases.RANKINGS_ONLY_NOTES))


def build_demo_report() -> DailyReport:
    """Synthetic movement-heavy Top 10 for local demonstration only."""

    from datetime import date

    def _player(
        rank: int,
        name: str,
        player_id: str,
        points: int,
        movement: Movement,
        previous_rank: int | None,
        previous_points: int | None = None,
    ) -> PlayerReport:
        return PlayerReport(
            rank=rank,
            name=name,
            player_id=player_id,
            country_code="USA",
            points=points,
            movement=movement,
            previous_rank=previous_rank,
            previous_points=previous_points,
        )

    players = [
        _player(1, "Jannik Sinner", "1", 13450, Movement.SAME, 1, 13450),
        _player(2, "Carlos Alcaraz", "2", 10450, Movement.SAME, 2, 10020),
        _player(3, "Alexander Zverev", "3", 10380, Movement.SAME, 3, 10700),
        _player(4, "Novak Djokovic", "4", 7830, Movement.SAME, 4, 7830),
        _player(5, "Taylor Fritz", "5", 4655, Movement.SAME, 5, 4655),
        _player(6, "Ben Shelton", "6", 3670, Movement.UP, 10, 3170),
        _player(7, "Daniil Medvedev", "7", 3580, Movement.DOWN, 6, 3900),
        _player(8, "Alex de Minaur", "8", 3485, Movement.DOWN, 7, 3300),
        _player(9, "Lorenzo Musetti", "9", 3255, Movement.SAME, 9, 3255),
        _player(10, "Jack Draper", "10", 2960, Movement.NEW, None, None),
    ]
    return DailyReport(
        report_date=date(2026, 8, 25),
        tour="atp",
        players=players,
        ranking_date=date(2026, 8, 25),
        departed_players=[
            RankingsDeparture(name="Holger Rune", player_id="11", previous_rank=8),
        ],
    )


def demo_script() -> str:
    """Return a sample movement-heavy ATP script (no live data, no disk writes)."""

    return generate_weekly_rankings_script(build_demo_report())


if __name__ == "__main__":
    print(demo_script())
