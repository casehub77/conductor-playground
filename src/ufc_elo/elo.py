from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from typing import Any

from .models import Fight, RatingState
from .overrides import OverrideData
from .util import identity_key, slugify


def default_state(initial_rating: float) -> RatingState:
    return RatingState(rating=initial_rating, peak=initial_rating)


def expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def fight_scores(outcome: str) -> tuple[float | None, float | None]:
    if outcome == "red_win":
        return 1.0, 0.0
    if outcome == "blue_win":
        return 0.0, 1.0
    if outcome == "draw":
        return 0.5, 0.5
    return None, None


def system_key(gender: str, weight_class: str) -> str:
    return f"{gender}:{weight_class}"


WEIGHT_ORDER = {
    "Atomweight": 105,
    "Strawweight": 115,
    "Flyweight": 125,
    "Bantamweight": 135,
    "Featherweight": 145,
    "Lightweight": 155,
    "Welterweight": 170,
    "Middleweight": 185,
    "Light Heavyweight": 205,
    "Heavyweight": 265,
    "Open Weight": 300,
}


def weight_rank(weight_class: str) -> int | None:
    return WEIGHT_ORDER.get(weight_class)


def catchweight_multipliers(
    red_weight: int | None,
    blue_weight: int | None,
    outcome: str,
    lighter_win: float,
    lighter_loss: float,
    heavier_win: float,
    heavier_loss: float,
) -> tuple[float, float]:
    if red_weight is None or blue_weight is None or red_weight == blue_weight:
        return 1.0, 1.0
    red_is_lighter = red_weight < blue_weight
    if outcome == "red_win":
        return (lighter_win, heavier_loss) if red_is_lighter else (heavier_win, lighter_loss)
    if outcome == "blue_win":
        return (lighter_loss, heavier_win) if red_is_lighter else (heavier_loss, lighter_win)
    return 1.0, 1.0


def _empty_profile(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "slug": slugify(name),
        "nicknames": Counter(),
        "genders": Counter(),
        "weight_classes": Counter(),
        "latest_gender": "",
        "latest_weight_class": "",
        "fight_count": 0,
        "last_fight_date": None,
        "first_fight_date": None,
    }


def _update_profile_counters(
    profile: dict[str, Any],
    nickname: str,
    gender: str,
    weight_class: str,
    event_date: date,
) -> None:
    if nickname:
        profile["nicknames"][nickname] += 1
    profile["genders"][gender] += 1
    profile["weight_classes"][weight_class] += 1
    profile["latest_gender"] = gender
    if weight_class not in {"Catch Weight", "Unknown"}:
        profile["latest_weight_class"] = weight_class
    profile["fight_count"] += 1
    profile["last_fight_date"] = event_date
    profile["first_fight_date"] = profile["first_fight_date"] or event_date


def _current_rating(
    ratings: dict[str, dict[str, "RatingState"]],
    system: str,
    fighter_name: str,
    initial: float,
) -> float:
    state = ratings.get(system, {}).get(fighter_name)
    return state.rating if state else initial


def _division_entry_rating(
    ratings: dict[str, dict[str, "RatingState"]],
    system: str,
    fighter_name: str,
    initial: float,
    overall_before: float,
    config: dict[str, Any],
) -> float:
    state = ratings.get(system, {}).get(fighter_name)
    if state:
        return state.rating

    transfer = config.get("division_transfer", {})
    if not transfer.get("enabled", True):
        return initial

    overall_weight = float(transfer.get("overall_weight", 1.0))
    max_seed_delta = float(transfer.get("max_seed_delta", 350))
    seeded = initial + ((overall_before - initial) * overall_weight)
    return max(initial - max_seed_delta, min(initial + max_seed_delta, seeded))


def _apply_rating_update(
    ratings: dict[str, dict[str, "RatingState"]],
    system: str,
    fighter_name: str,
    division_members: dict[str, set[str]],
    score: float | None,
    self_before: float,
    opponent_before: float,
    k_factor: float,
    result_mult: float,
    k_mult: float,
    max_delta: float,
    event_date: date,
) -> tuple[float, float]:
    state = ratings[system].setdefault(fighter_name, default_state(self_before))
    state.rating = self_before
    state.peak = max(state.peak, self_before)
    division_members[system].add(fighter_name)
    delta = 0.0
    if score is not None:
        delta = k_factor * result_mult * k_mult * (score - expected_score(self_before, opponent_before))
        delta = max(-max_delta, min(max_delta, delta))
        state.rating += delta
        state.peak = max(state.peak, state.rating)
    state.last_fight_date = event_date
    state.fights += 1
    return delta, state.rating


def compute_ratings(fights: list[Fight], config: dict[str, Any], overrides: OverrideData) -> dict[str, Any]:
    initial = float(config.get("initial_rating", 1500))
    k_overall = float(config.get("k_factor", 32))
    k_divisional = float(config.get("divisional_k_factor", k_overall))
    max_delta = float(config.get("max_delta", 60))
    title_multiplier = float(config.get("title_fight_multiplier", 1.1))
    finish_multiplier = float(config.get("finish_multiplier", 1.08))
    decision_multiplier = float(config.get("decision_multiplier", 1.0))
    recent_window_days = int(config.get("recent_window_days", 90))
    catch_cfg = config.get("catchweight", {})
    catch_lighter_win = float(catch_cfg.get("lighter_win_multiplier", 1.5))
    catch_lighter_loss = float(catch_cfg.get("lighter_loss_multiplier", 0.5))
    catch_heavier_win = float(catch_cfg.get("heavier_win_multiplier", 0.5))
    catch_heavier_loss = float(catch_cfg.get("heavier_loss_multiplier", 1.5))
    peaks_cfg = config.get("all_time_peaks", {})
    min_divisional_fights = int(peaks_cfg.get("min_divisional_fights", 0))
    min_overall_fights = int(peaks_cfg.get("min_overall_fights", 0))

    ratings: dict[str, dict[str, RatingState]] = defaultdict(dict)
    fighters: dict[str, dict[str, Any]] = {}
    fighter_logs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    histories: dict[str, list[dict[str, Any]]] = defaultdict(list)
    division_members: dict[str, set[str]] = defaultdict(set)
    title_history: list[dict[str, Any]] = []
    champion_by_system: dict[str, dict[str, Any]] = {}

    ordered = sorted(
        enumerate(fights),
        key=lambda item: (
            item[1].event_date,
            tuple(sorted([item[1].red_name, item[1].blue_name])),
            item[1].fight_id,
        ),
    )

    for _, fight in ordered:
        red_profile = fighters.setdefault(fight.red_name, _empty_profile(fight.red_name))
        blue_profile = fighters.setdefault(fight.blue_name, _empty_profile(fight.blue_name))

        red_primary_prior = primary_counter_value(red_profile["weight_classes"])
        blue_primary_prior = primary_counter_value(blue_profile["weight_classes"])

        overall_system = system_key(fight.gender, "overall")
        if fight.weight_class == "Catch Weight":
            red_divisional = system_key(fight.gender, red_primary_prior) if red_primary_prior else None
            blue_divisional = system_key(fight.gender, blue_primary_prior) if blue_primary_prior else None
            red_k_mult, blue_k_mult = catchweight_multipliers(
                weight_rank(red_primary_prior) if red_primary_prior else None,
                weight_rank(blue_primary_prior) if blue_primary_prior else None,
                fight.outcome,
                catch_lighter_win,
                catch_lighter_loss,
                catch_heavier_win,
                catch_heavier_loss,
            )
        else:
            divisional = system_key(fight.gender, fight.weight_class)
            red_divisional = divisional
            blue_divisional = divisional
            red_k_mult = 1.0
            blue_k_mult = 1.0

        red_score, blue_score = fight_scores(fight.outcome)
        result_mult = result_multiplier(fight, title_multiplier, finish_multiplier, decision_multiplier)

        fight_snapshot: dict[str, Any] = {
            "fight_id": fight.fight_id,
            "date": fight.event_date.isoformat(),
            "event_name": fight.event_name,
            "bout_type": fight.bout_type,
            "method": fight.method,
            "round": fight.round,
            "time": fight.time,
            "outcome": fight.outcome,
            "red_name": fight.red_name,
            "blue_name": fight.blue_name,
            "weight_class": fight.weight_class,
            "gender": fight.gender,
            "is_title": fight.is_title,
            "source": fight.source,
            "source_title": fight.raw.get("source_title", ""),
        }

        red_overall_before = _current_rating(ratings, overall_system, fight.red_name, initial)
        blue_overall_before = _current_rating(ratings, overall_system, fight.blue_name, initial)
        red_div_before = (
            _division_entry_rating(ratings, red_divisional, fight.red_name, initial, red_overall_before, config)
            if red_divisional else initial
        )
        blue_div_before = (
            _division_entry_rating(ratings, blue_divisional, fight.blue_name, initial, blue_overall_before, config)
            if blue_divisional else initial
        )

        red_overall_delta, red_overall_after = _apply_rating_update(
            ratings, overall_system, fight.red_name, division_members,
            red_score, red_overall_before, blue_overall_before,
            k_overall, result_mult, red_k_mult, max_delta, fight.event_date,
        )
        blue_overall_delta, blue_overall_after = _apply_rating_update(
            ratings, overall_system, fight.blue_name, division_members,
            blue_score, blue_overall_before, red_overall_before,
            k_overall, result_mult, blue_k_mult, max_delta, fight.event_date,
        )

        red_div_delta = 0.0
        red_div_after = red_div_before
        if red_divisional:
            red_div_delta, red_div_after = _apply_rating_update(
                ratings, red_divisional, fight.red_name, division_members,
                red_score, red_div_before, blue_div_before,
                k_divisional, result_mult, red_k_mult, max_delta, fight.event_date,
            )
        blue_div_delta = 0.0
        blue_div_after = blue_div_before
        if blue_divisional:
            blue_div_delta, blue_div_after = _apply_rating_update(
                ratings, blue_divisional, fight.blue_name, division_members,
                blue_score, blue_div_before, red_div_before,
                k_divisional, result_mult, blue_k_mult, max_delta, fight.event_date,
            )

        histories[fight.red_name].append({
            "date": fight.event_date.isoformat(),
            "rating": round(red_overall_after, 1),
            "system": overall_system,
            "scope": "overall",
            "fight_id": fight.fight_id,
        })
        histories[fight.blue_name].append({
            "date": fight.event_date.isoformat(),
            "rating": round(blue_overall_after, 1),
            "system": overall_system,
            "scope": "overall",
            "fight_id": fight.fight_id,
        })
        if red_divisional:
            histories[fight.red_name].append({
                "date": fight.event_date.isoformat(),
                "rating": round(red_div_after, 1),
                "system": red_divisional,
                "scope": "division",
                "fight_id": fight.fight_id,
            })
            fighter_logs[fight.red_name].append(
                fight_log_entry(fight_snapshot, fight.blue_name, red_div_before, red_div_after, red_div_delta, blue_div_before)
            )
        if blue_divisional:
            histories[fight.blue_name].append({
                "date": fight.event_date.isoformat(),
                "rating": round(blue_div_after, 1),
                "system": blue_divisional,
                "scope": "division",
                "fight_id": fight.fight_id,
            })
            fighter_logs[fight.blue_name].append(
                fight_log_entry(fight_snapshot, fight.red_name, blue_div_before, blue_div_after, blue_div_delta, red_div_before)
            )

        _update_profile_counters(red_profile, fight.red_nickname, fight.gender, fight.weight_class, fight.event_date)
        _update_profile_counters(blue_profile, fight.blue_nickname, fight.gender, fight.weight_class, fight.event_date)

        if fight.is_title and fight.outcome in {"red_win", "blue_win", "draw", "no_contest"}:
            winner = fight.red_name if fight.outcome == "red_win" else fight.blue_name if fight.outcome == "blue_win" else None
            title_entry = {
                "date": fight.event_date.isoformat(),
                "system": system_key(fight.gender, fight.weight_class),
                "gender": fight.gender,
                "weight_class": fight.weight_class,
                "fighter_name": winner,
                "red_name": fight.red_name,
                "blue_name": fight.blue_name,
                "event_name": fight.event_name,
                "bout_type": fight.bout_type,
                "method": fight.method,
                "fight_id": fight.fight_id,
                "outcome": fight.outcome,
            }
            title_history.append(title_entry)
            if winner and "interim" not in fight.bout_type.lower() and "superfight" not in fight.bout_type.lower():
                champion_by_system[title_entry["system"]] = title_entry

    as_of = max((fight.event_date for fight in fights), default=date.today())
    rankings = build_rankings(ratings, fighters, config, as_of)
    apply_champion_overrides(champion_by_system, overrides, rankings, as_of)

    profiles = build_profiles(fighters, ratings, rankings, fighter_logs, histories, overrides, config, as_of)
    return {
        "as_of": as_of.isoformat(),
        "fighters": profiles,
        "rankings": rankings,
        "champions": champions_payload(champion_by_system, rankings, profiles),
        "previous_champions": previous_champions(title_history, profiles),
        "highest_ever": highest_ever(profiles, min_fights=min_overall_fights),
        "highest_ever_by_system": highest_ever_by_system(ratings, profiles, min_fights=min_divisional_fights),
        "title_lineage": title_lineage_by_system(title_history, profiles),
        "recent_movers": recent_movers(fighter_logs, profiles, as_of, recent_window_days),
        "title_history": title_history,
        "systems": sorted(rankings.keys()),
        "fight_count": len(fights),
    }


def result_multiplier(fight: Fight, title_multiplier: float, finish_multiplier: float, decision_multiplier: float) -> float:
    multiplier = title_multiplier if fight.is_title else 1.0
    method = fight.method.lower()
    if "decision" in method:
        multiplier *= decision_multiplier
    elif fight.outcome in {"red_win", "blue_win"}:
        multiplier *= finish_multiplier
    return multiplier


def fight_log_entry(
    snapshot: dict[str, Any],
    opponent: str,
    before: float,
    after: float,
    delta: float,
    opponent_before: float,
) -> dict[str, Any]:
    entry = dict(snapshot)
    entry.update(
        {
            "opponent": opponent,
            "pre_elo": round(before, 1),
            "post_elo": round(after, 1),
            "elo_delta": round(delta, 1),
            "opponent_elo": round(opponent_before, 1),
        }
    )
    return entry


def build_rankings(
    ratings: dict[str, dict[str, RatingState]],
    fighters: dict[str, dict[str, Any]],
    config: dict[str, Any],
    as_of: date,
) -> dict[str, list[dict[str, Any]]]:
    rankings: dict[str, list[dict[str, Any]]] = {}
    for key, states in ratings.items():
        rows = []
        for fighter_name, state in states.items():
            current = apply_inactivity_decay(state.rating, state.last_fight_date, as_of, config)
            rows.append(
                {
                    "rank": 0,
                    "name": fighter_name,
                    "slug": slugify(fighter_name),
                    "rating": round(current, 1),
                    "raw_rating": round(state.rating, 1),
                    "peak": round(state.peak, 1),
                    "fights": state.fights,
                    "last_fight_date": state.last_fight_date.isoformat() if state.last_fight_date else None,
                    "primary_weight_class": profile_weight_class(fighters[fighter_name]),
                    "gender": profile_gender(fighters[fighter_name]),
                }
            )
        rows.sort(key=lambda row: (-row["rating"], -row["peak"], row["name"]))
        for index, row in enumerate(rows, 1):
            row["rank"] = index
        rankings[key] = rows
    return rankings


def apply_inactivity_decay(rating: float, last_fight_date: date | None, as_of: date, config: dict[str, Any]) -> float:
    decay = config.get("inactivity_decay", {})
    if not decay.get("enabled", True) or not last_fight_date:
        return rating
    after_days = int(decay.get("after_days", 545))
    points_per_year = float(decay.get("points_per_year", 25))
    floor = float(decay.get("floor", config.get("initial_rating", 1500)))
    inactive_days = max(0, (as_of - last_fight_date).days - after_days)
    penalty = (inactive_days / 365.25) * points_per_year
    if rating >= floor:
        return max(floor, rating - penalty)
    return min(floor, rating + penalty)


def inactivity_summary(last_fight_date: date | None, as_of: date, config: dict[str, Any]) -> dict[str, Any]:
    decay = config.get("inactivity_decay", {})
    after_days = int(decay.get("after_days", 545))
    if not last_fight_date:
        return {
            "status": "unknown",
            "days_since_last_fight": None,
            "inactive_after_days": after_days,
        }
    days_since = max(0, (as_of - last_fight_date).days)
    return {
        "status": "inactive" if days_since > after_days else "active",
        "days_since_last_fight": days_since,
        "inactive_after_days": after_days,
    }


def build_profiles(
    fighters: dict[str, dict[str, Any]],
    ratings: dict[str, dict[str, RatingState]],
    rankings: dict[str, list[dict[str, Any]]],
    fighter_logs: dict[str, list[dict[str, Any]]],
    histories: dict[str, list[dict[str, Any]]],
    overrides: OverrideData,
    config: dict[str, Any],
    as_of: date,
) -> list[dict[str, Any]]:
    rank_lookup = {(system, row["name"]): row["rank"] for system, rows in rankings.items() for row in rows}
    profiles: list[dict[str, Any]] = []
    for name, base in fighters.items():
        gender = profile_gender(base)
        weight_class = profile_weight_class(base)
        overall_system = system_key(gender, "overall")
        division_system = system_key(gender, weight_class)
        overall_state = ratings.get(overall_system, {}).get(name)
        division_state = ratings.get(division_system, {}).get(name)
        current_overall = apply_inactivity_decay(overall_state.rating, overall_state.last_fight_date, as_of, config) if overall_state else None
        current_division = apply_inactivity_decay(division_state.rating, division_state.last_fight_date, as_of, config) if division_state else None
        raw_overall = overall_state.rating if overall_state else None
        raw_division = division_state.rating if division_state else None
        inactivity = inactivity_summary(base["last_fight_date"], as_of, config)
        profile = {
            "name": name,
            "slug": slugify(name),
            "nickname": primary_counter_value(base["nicknames"]),
            "gender": gender,
            "weight_class": weight_class,
            "systems": {
                "overall": overall_system,
                "division": division_system,
            },
            "current_elo": round(current_division if current_division is not None else current_overall or 1500, 1),
            "raw_current_elo": round(raw_division if raw_division is not None else raw_overall or 1500, 1),
            "overall_elo": round(current_overall, 1) if current_overall is not None else None,
            "raw_overall_elo": round(raw_overall, 1) if raw_overall is not None else None,
            "inactivity_adjusted": bool(
                (current_division is not None and raw_division is not None and round(current_division, 1) != round(raw_division, 1))
                or (current_division is None and current_overall is not None and raw_overall is not None and round(current_overall, 1) != round(raw_overall, 1))
            ),
            "activity_status": inactivity["status"],
            "days_since_last_fight": inactivity["days_since_last_fight"],
            "inactive_after_days": inactivity["inactive_after_days"],
            "peak_elo": round(max([state.peak for systems in ratings.values() for fighter, state in systems.items() if fighter == name] or [1500]), 1),
            "divisional_rank": rank_lookup.get((division_system, name)),
            "fight_count": base["fight_count"],
            "first_fight_date": base["first_fight_date"].isoformat() if base["first_fight_date"] else None,
            "last_fight_date": base["last_fight_date"].isoformat() if base["last_fight_date"] else None,
            "instagram": instagram_url(name, overrides),
            "history": sorted(histories[name], key=lambda item: (item["date"], item["scope"])),
            "fight_log": list(reversed(fighter_logs[name])),
        }
        profiles.append(profile)
    profiles.sort(key=lambda row: row["name"])
    return profiles


def instagram_url(name: str, overrides: OverrideData) -> str | None:
    handle = overrides.instagram.get(identity_key(name))
    if not handle:
        return None
    return f"https://www.instagram.com/{handle}/"


def primary_counter_value(counter: Counter) -> str:
    if not counter:
        return ""
    return counter.most_common(1)[0][0]


def profile_gender(profile: dict[str, Any]) -> str:
    return profile.get("latest_gender") or primary_counter_value(profile["genders"])


def profile_weight_class(profile: dict[str, Any]) -> str:
    return profile.get("latest_weight_class") or primary_counter_value(profile["weight_classes"])


def apply_champion_overrides(
    champion_by_system: dict[str, dict[str, Any]],
    overrides: OverrideData,
    rankings: dict[str, list[dict[str, Any]]],
    as_of: date,
) -> None:
    for key, fighter_name in overrides.champion_overrides.items():
        gender, _, weight_class = key.partition(":")
        champion_by_system[key] = {
            "date": as_of.isoformat(),
            "system": key,
            "gender": gender,
            "weight_class": weight_class,
            "fighter_name": fighter_name,
            "event_name": "Manual champion override",
            "bout_type": "Manual champion override",
            "method": "",
            "fight_id": "manual",
        }


def champions_payload(champions: dict[str, dict[str, Any]], rankings: dict[str, list[dict[str, Any]]], profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    profile_by_name = {profile["name"]: profile for profile in profiles}
    rating_lookup = {(system, row["name"]): row for system, rows in rankings.items() for row in rows}
    payload = []
    for key, entry in sorted(champions.items()):
        name = entry.get("fighter_name")
        if not name:
            continue
        rank_row = rating_lookup.get((key, name), {})
        profile = profile_by_name.get(name, {})
        payload.append(
            {
                **entry,
                "slug": profile.get("slug", slugify(name)),
                "current_elo": rank_row.get("rating", profile.get("current_elo")),
                "rank": rank_row.get("rank"),
            }
        )
    return sorted(payload, key=lambda row: (row["gender"], row["weight_class"]))


def previous_champions(title_history: list[dict[str, Any]], profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    profile_by_name = {profile["name"]: profile for profile in profiles}
    rows = []
    seen: set[tuple[str, str, str]] = set()
    for entry in title_history:
        name = entry.get("fighter_name")
        if not name:
            continue
        key = (entry["system"], name, entry["date"])
        if key in seen:
            continue
        seen.add(key)
        profile = profile_by_name.get(name, {})
        rows.append({**entry, "slug": profile.get("slug", slugify(name)), "current_elo": profile.get("current_elo")})
    return list(reversed(rows))


def highest_ever(profiles: list[dict[str, Any]], limit: int = 30, min_fights: int = 0) -> list[dict[str, Any]]:
    rows = [
        {
            "name": profile["name"],
            "slug": profile["slug"],
            "peak_elo": profile["peak_elo"],
            "current_elo": profile["current_elo"],
            "weight_class": profile["weight_class"],
            "gender": profile["gender"],
            "fights": profile.get("fight_count", 0),
        }
        for profile in profiles
        if profile.get("fight_count", 0) >= min_fights
    ]
    return sorted(rows, key=lambda row: (-row["peak_elo"], row["name"]))[:limit]


def highest_ever_by_system(
    ratings: dict[str, dict[str, "RatingState"]],
    profiles: list[dict[str, Any]],
    limit: int = 25,
    min_fights: int = 0,
) -> dict[str, list[dict[str, Any]]]:
    profile_by_name = {profile["name"]: profile for profile in profiles}
    output: dict[str, list[dict[str, Any]]] = {}
    for system, states in ratings.items():
        rows = []
        for name, state in states.items():
            if state.fights < min_fights:
                continue
            profile = profile_by_name.get(name, {})
            rows.append({
                "name": name,
                "slug": profile.get("slug", slugify(name)),
                "peak_elo": round(state.peak, 1),
                "current_elo": profile.get("current_elo"),
                "fights": state.fights,
                "last_fight_date": state.last_fight_date.isoformat() if state.last_fight_date else None,
            })
        rows.sort(key=lambda row: (-row["peak_elo"], row["name"]))
        output[system] = rows[:limit]
    return output


def title_lineage_by_system(title_history: list[dict[str, Any]], profiles: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    profile_by_name = {profile["name"]: profile for profile in profiles}
    by_system: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in title_history:
        system = entry.get("system")
        if not system:
            continue
        profile = profile_by_name.get(entry.get("fighter_name") or "", {})
        by_system[system].append({
            **entry,
            "slug": profile.get("slug"),
            "current_elo": profile.get("current_elo"),
        })
    for system in by_system:
        by_system[system].sort(key=lambda row: row["date"])
    return dict(by_system)


def recent_movers(
    fighter_logs: dict[str, list[dict[str, Any]]],
    profiles: list[dict[str, Any]],
    as_of: date,
    window_days: int,
    limit: int = 30,
) -> list[dict[str, Any]]:
    profile_by_name = {profile["name"]: profile for profile in profiles}
    rows = []
    for name, logs in fighter_logs.items():
        total = 0.0
        fights = 0
        for log in logs:
            try:
                fight_date = date.fromisoformat(log["date"])
            except ValueError:
                continue
            if (as_of - fight_date).days <= window_days:
                total += float(log["elo_delta"])
                fights += 1
        if fights:
            profile = profile_by_name[name]
            rows.append(
                {
                    "name": name,
                    "slug": profile["slug"],
                    "change": round(total, 1),
                    "fights": fights,
                    "current_elo": profile["current_elo"],
                    "weight_class": profile["weight_class"],
                    "gender": profile["gender"],
                }
            )
    return sorted(rows, key=lambda row: (-abs(row["change"]), row["name"]))[:limit]
