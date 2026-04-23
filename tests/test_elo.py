from __future__ import annotations

import unittest
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ufc_elo.elo import catchweight_multipliers, compute_ratings
from ufc_elo.ingestion import ManualRowError, detect_source_conflicts, load_manual_rows, merge_new_fights, parse_bout_type, rows_to_fights
from ufc_elo.overrides import OverrideData


BASE_CONFIG = {
    "initial_rating": 1500,
    "k_factor": 32,
    "divisional_k_factor": 36,
    "finish_multiplier": 1.0,
    "title_fight_multiplier": 1.0,
    "decision_multiplier": 1.0,
    "inactivity_decay": {"enabled": False},
}


class EloSmokeTest(unittest.TestCase):
    def test_blue_win_moves_ratings(self) -> None:
        overrides = OverrideData({}, {}, {}, set(), {})
        rows = [
            {
                "red_fighter_name": "Alpha One",
                "blue_fighter_name": "Beta Two",
                "event_date": "2020-01-01",
                "red_fighter_result": "L",
                "blue_fighter_result": "W",
                "fight_outcome": "blue_win",
                "method": "KO/TKO",
                "bout_type": "Lightweight Bout",
                "event_name": "UFC Test",
                "event_location": "Test City",
            }
        ]
        fights = rows_to_fights(rows, "test", overrides)
        output = compute_ratings(fights, BASE_CONFIG, overrides)
        profiles = {profile["name"]: profile for profile in output["fighters"]}
        self.assertLess(profiles["Alpha One"]["current_elo"], 1500)
        self.assertGreater(profiles["Beta Two"]["current_elo"], 1500)

    def test_new_division_seeds_from_overall_context(self) -> None:
        overrides = OverrideData({}, {}, {}, set(), {})
        rows = [
            {
                "red_fighter_name": "Division Mover",
                "blue_fighter_name": "Light Opp One",
                "event_date": "2020-01-01",
                "red_fighter_result": "W",
                "blue_fighter_result": "L",
                "fight_outcome": "red_win",
                "method": "Decision",
                "bout_type": "Lightweight Bout",
                "event_name": "Test 1",
                "event_location": "",
            },
            {
                "red_fighter_name": "Division Mover",
                "blue_fighter_name": "Light Opp Two",
                "event_date": "2020-06-01",
                "red_fighter_result": "W",
                "blue_fighter_result": "L",
                "fight_outcome": "red_win",
                "method": "Decision",
                "bout_type": "Lightweight Bout",
                "event_name": "Test 2",
                "event_location": "",
            },
            {
                "red_fighter_name": "Division Mover",
                "blue_fighter_name": "Welter Opp",
                "event_date": "2021-01-01",
                "red_fighter_result": "W",
                "blue_fighter_result": "L",
                "fight_outcome": "red_win",
                "method": "Decision",
                "bout_type": "Welterweight Bout",
                "event_name": "Test 3",
                "event_location": "",
            },
        ]
        fights = rows_to_fights(rows, "test", overrides)
        output = compute_ratings(fights, BASE_CONFIG, overrides)
        profiles = {profile["name"]: profile for profile in output["fighters"]}
        mover = profiles["Division Mover"]

        self.assertEqual(mover["weight_class"], "Welterweight")
        self.assertEqual(mover["systems"]["division"], "men:Welterweight")
        self.assertGreater(mover["fight_log"][0]["pre_elo"], 1500)
        self.assertGreater(mover["current_elo"], mover["fight_log"][0]["pre_elo"])


class CatchweightMultiplierTest(unittest.TestCase):
    def test_lighter_fighter_wins_gets_boost(self) -> None:
        red_mult, blue_mult = catchweight_multipliers(
            135, 145, "red_win", 1.5, 0.5, 0.5, 1.5,
        )
        self.assertEqual(red_mult, 1.5)
        self.assertEqual(blue_mult, 1.5)

    def test_heavier_fighter_wins_gets_dampened(self) -> None:
        red_mult, blue_mult = catchweight_multipliers(
            135, 145, "blue_win", 1.5, 0.5, 0.5, 1.5,
        )
        self.assertEqual(red_mult, 0.5)
        self.assertEqual(blue_mult, 0.5)

    def test_equal_weight_no_multiplier(self) -> None:
        red_mult, blue_mult = catchweight_multipliers(
            155, 155, "red_win", 1.5, 0.5, 0.5, 1.5,
        )
        self.assertEqual((red_mult, blue_mult), (1.0, 1.0))

    def test_no_history_no_multiplier(self) -> None:
        red_mult, blue_mult = catchweight_multipliers(
            None, 155, "red_win", 1.5, 0.5, 0.5, 1.5,
        )
        self.assertEqual((red_mult, blue_mult), (1.0, 1.0))


class BoutTypeParsingTest(unittest.TestCase):
    def test_parse_catchweight_with_numeric_limit(self) -> None:
        self.assertEqual(parse_bout_type("Catchweight (165 lb) Bout"), ("men", "Catch Weight"))

    def test_parse_womens_numeric_weight_class(self) -> None:
        self.assertEqual(parse_bout_type("Women's 115-pound Bout"), ("women", "Strawweight"))

    def test_parse_generic_numeric_weight_class(self) -> None:
        self.assertEqual(parse_bout_type("145 lb Bout"), ("men", "Featherweight"))

    def test_parse_atomweight_kg_label(self) -> None:
        self.assertEqual(parse_bout_type("Female Atomweight 48 kg Bout"), ("women", "Atomweight"))

    def test_parse_super_atomweight_label(self) -> None:
        self.assertEqual(parse_bout_type("W.Super Atomweight 49 kg Bout"), ("women", "Atomweight"))

    def test_parse_strawweight_muay_thai_label(self) -> None:
        self.assertEqual(parse_bout_type("Strawweight Muay Thai Bout"), ("men", "Strawweight"))

    def test_parse_womens_atomweight_submission_grappling_label(self) -> None:
        self.assertEqual(parse_bout_type("Women's Atomweight Submission Grappling Bout"), ("women", "Atomweight"))

    def test_parse_common_weight_class_typos(self) -> None:
        self.assertEqual(parse_bout_type("Stawweight Muay Thai Bout"), ("men", "Strawweight"))
        self.assertEqual(parse_bout_type("Weltererweight Bout"), ("men", "Welterweight"))

    def test_parse_nearby_womens_numeric_weight_class(self) -> None:
        self.assertEqual(parse_bout_type("Women's (127 lb) Bout"), ("women", "Flyweight"))


class CatchweightIntegrationTest(unittest.TestCase):
    def test_catchweight_without_history_skips_divisional(self) -> None:
        overrides = OverrideData({}, {}, {}, set(), {})
        rows = [
            {
                "red_fighter_name": "Debut A",
                "blue_fighter_name": "Debut B",
                "event_date": "2020-01-01",
                "red_fighter_result": "W",
                "blue_fighter_result": "L",
                "fight_outcome": "red_win",
                "method": "KO/TKO",
                "bout_type": "Catch Weight Bout",
                "event_name": "UFC Catch",
                "event_location": "",
            }
        ]
        fights = rows_to_fights(rows, "test", overrides)
        output = compute_ratings(fights, BASE_CONFIG, overrides)
        self.assertFalse(any(system.endswith(":Catch Weight") for system in output["systems"]))

    def test_catchweight_uses_primary_divisions_when_known(self) -> None:
        overrides = OverrideData({}, {}, {}, set(), {})
        rows = [
            # Establish primary divisions first
            {
                "red_fighter_name": "Bantam Champ",
                "blue_fighter_name": "Bantam Opp",
                "event_date": "2019-01-01",
                "red_fighter_result": "W",
                "blue_fighter_result": "L",
                "fight_outcome": "red_win",
                "method": "KO/TKO",
                "bout_type": "Bantamweight Bout",
                "event_name": "UFC 1",
                "event_location": "",
            },
            {
                "red_fighter_name": "Feather Champ",
                "blue_fighter_name": "Feather Opp",
                "event_date": "2019-02-01",
                "red_fighter_result": "W",
                "blue_fighter_result": "L",
                "fight_outcome": "red_win",
                "method": "KO/TKO",
                "bout_type": "Featherweight Bout",
                "event_name": "UFC 2",
                "event_location": "",
            },
            # Bantamweight moves up to catchweight against Featherweight
            {
                "red_fighter_name": "Bantam Champ",
                "blue_fighter_name": "Feather Champ",
                "event_date": "2020-01-01",
                "red_fighter_result": "W",
                "blue_fighter_result": "L",
                "fight_outcome": "red_win",
                "method": "KO/TKO",
                "bout_type": "Catch Weight Bout",
                "event_name": "UFC 3",
                "event_location": "",
            },
        ]
        fights = rows_to_fights(rows, "test", overrides)
        output = compute_ratings(fights, BASE_CONFIG, overrides)
        self.assertIn("men:Bantamweight", output["systems"])
        self.assertIn("men:Featherweight", output["systems"])
        self.assertNotIn("men:Catch Weight", output["systems"])
        bantam_ranking = {row["name"]: row for row in output["rankings"]["men:Bantamweight"]}
        feather_ranking = {row["name"]: row for row in output["rankings"]["men:Featherweight"]}
        self.assertIn("Bantam Champ", bantam_ranking)
        self.assertIn("Feather Champ", feather_ranking)


class UnknownWeightInferenceTest(unittest.TestCase):
    def test_unknown_weight_infers_shared_division_from_nearest_history(self) -> None:
        overrides = OverrideData({}, {}, {}, set(), {})
        rows = [
            {
                "red_fighter_name": "Shared A",
                "blue_fighter_name": "Shared B",
                "event_date": "2020-01-01",
                "red_fighter_result": "W",
                "blue_fighter_result": "L",
                "fight_outcome": "red_win",
                "method": "Decision",
                "bout_type": "Lightweight Bout",
                "event_name": "Known 1",
                "event_location": "",
            },
            {
                "red_fighter_name": "Shared A",
                "blue_fighter_name": "Shared B",
                "event_date": "2020-06-01",
                "red_fighter_result": "W",
                "blue_fighter_result": "L",
                "fight_outcome": "red_win",
                "method": "Decision",
                "bout_type": "Bout",
                "event_name": "Unknown",
                "event_location": "",
            },
        ]
        fights = rows_to_fights(rows, "test", overrides)
        inferred = next(f for f in fights if f.event_name == "Unknown")
        self.assertEqual(inferred.weight_class, "Lightweight")
        self.assertEqual(inferred.bout_type, "Lightweight Bout")
        self.assertEqual(inferred.raw.get("weight_class_inferred"), "true")

    def test_unknown_weight_becomes_catchweight_when_fighters_have_different_divisions(self) -> None:
        overrides = OverrideData({}, {}, {}, set(), {})
        rows = [
            {
                "red_fighter_name": "Light Guy",
                "blue_fighter_name": "Light Opp",
                "event_date": "2020-01-01",
                "red_fighter_result": "W",
                "blue_fighter_result": "L",
                "fight_outcome": "red_win",
                "method": "Decision",
                "bout_type": "Lightweight Bout",
                "event_name": "Known Light",
                "event_location": "",
            },
            {
                "red_fighter_name": "Welter Guy",
                "blue_fighter_name": "Welter Opp",
                "event_date": "2020-01-15",
                "red_fighter_result": "W",
                "blue_fighter_result": "L",
                "fight_outcome": "red_win",
                "method": "Decision",
                "bout_type": "Welterweight Bout",
                "event_name": "Known Welter",
                "event_location": "",
            },
            {
                "red_fighter_name": "Light Guy",
                "blue_fighter_name": "Welter Guy",
                "event_date": "2020-02-01",
                "red_fighter_result": "W",
                "blue_fighter_result": "L",
                "fight_outcome": "red_win",
                "method": "Decision",
                "bout_type": "Bout",
                "event_name": "Unknown Cross",
                "event_location": "",
            },
        ]
        fights = rows_to_fights(rows, "test", overrides)
        inferred = next(f for f in fights if f.event_name == "Unknown Cross")
        self.assertEqual(inferred.weight_class, "Catch Weight")
        self.assertEqual(inferred.bout_type, "Catch Weight Bout")

    def test_unknown_weight_uses_single_fighter_history_when_only_one_side_is_known(self) -> None:
        overrides = OverrideData({}, {}, {}, set(), {})
        rows = [
            {
                "red_fighter_name": "Known Guy",
                "blue_fighter_name": "Known Opp",
                "event_date": "2020-01-01",
                "red_fighter_result": "W",
                "blue_fighter_result": "L",
                "fight_outcome": "red_win",
                "method": "Decision",
                "bout_type": "Featherweight Bout",
                "event_name": "Known Feather",
                "event_location": "",
            },
            {
                "red_fighter_name": "Known Guy",
                "blue_fighter_name": "Debut Opp",
                "event_date": "2020-02-01",
                "red_fighter_result": "W",
                "blue_fighter_result": "L",
                "fight_outcome": "red_win",
                "method": "Decision",
                "bout_type": "Bout",
                "event_name": "Unknown Partial",
                "event_location": "",
            },
        ]
        fights = rows_to_fights(rows, "test", overrides)
        inferred = next(f for f in fights if f.event_name == "Unknown Partial")
        self.assertEqual(inferred.weight_class, "Featherweight")
        self.assertEqual(inferred.bout_type, "Featherweight Bout")


class IngestionSafetyTest(unittest.TestCase):
    def test_merge_new_fights_dedupes_different_corner_order(self) -> None:
        overrides = OverrideData({}, {}, {}, set(), {})
        primary = rows_to_fights(
            [
                {
                    "red_fighter_name": "Red Corner",
                    "blue_fighter_name": "Blue Corner",
                    "event_date": "2026-01-01",
                    "red_fighter_result": "L",
                    "blue_fighter_result": "W",
                    "fight_outcome": "blue_win",
                    "method": "Decision",
                    "bout_type": "Lightweight Bout",
                    "event_name": "UFC Same",
                    "event_location": "",
                }
            ],
            "primary",
            overrides,
        )
        fallback = rows_to_fights(
            [
                {
                    "red_fighter_name": "Blue Corner",
                    "blue_fighter_name": "Red Corner",
                    "event_date": "2026-01-01",
                    "red_fighter_result": "W",
                    "blue_fighter_result": "L",
                    "fight_outcome": "red_win",
                    "method": "Decision",
                    "bout_type": "Lightweight Bout",
                    "event_name": "UFC Same",
                    "event_location": "",
                }
            ],
            "fallback",
            overrides,
        )

        new_fights, duplicates = merge_new_fights(primary, fallback)

        self.assertEqual(new_fights, [])
        self.assertEqual(duplicates, 1)

    def test_conflict_detection_compares_winner_identity(self) -> None:
        overrides = OverrideData({}, {}, {}, set(), {})
        primary = rows_to_fights(
            [
                {
                    "red_fighter_name": "Alpha",
                    "blue_fighter_name": "Beta",
                    "event_date": "2026-01-01",
                    "red_fighter_result": "W",
                    "blue_fighter_result": "L",
                    "fight_outcome": "red_win",
                    "method": "Decision",
                    "bout_type": "Lightweight Bout",
                    "event_name": "UFC Conflict",
                    "event_location": "",
                }
            ],
            "primary",
            overrides,
        )
        fallback = rows_to_fights(
            [
                {
                    "red_fighter_name": "Beta",
                    "blue_fighter_name": "Alpha",
                    "event_date": "2026-01-01",
                    "red_fighter_result": "W",
                    "blue_fighter_result": "L",
                    "fight_outcome": "red_win",
                    "method": "Decision",
                    "bout_type": "Lightweight Bout",
                    "event_name": "UFC Conflict",
                    "event_location": "",
                }
            ],
            "fallback",
            overrides,
        )

        conflicts = detect_source_conflicts([("primary", primary), ("fallback", fallback)])

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["winner_a"], "alpha")
        self.assertEqual(conflicts[0]["winner_b"], "beta")

    def test_same_source_same_event_rematch_is_not_a_conflict(self) -> None:
        overrides = OverrideData({}, {}, {}, set(), {})
        primary = rows_to_fights(
            [
                {
                    "red_fighter_name": "Kazushi Sakuraba",
                    "blue_fighter_name": "Marcus Silveira",
                    "event_date": "1997-12-21",
                    "red_fighter_result": "NC",
                    "blue_fighter_result": "NC",
                    "fight_outcome": "no_contest",
                    "method": "Overturned",
                    "bout_type": "Heavyweight Bout",
                    "event_name": "UFC Ultimate Japan",
                    "event_location": "",
                },
                {
                    "red_fighter_name": "Kazushi Sakuraba",
                    "blue_fighter_name": "Marcus Silveira",
                    "event_date": "1997-12-21",
                    "red_fighter_result": "W",
                    "blue_fighter_result": "L",
                    "fight_outcome": "red_win",
                    "method": "Submission",
                    "bout_type": "Heavyweight Bout",
                    "event_name": "UFC Ultimate Japan",
                    "event_location": "",
                },
            ],
            "primary",
            overrides,
        )

        conflicts = detect_source_conflicts([("primary", primary)])

        self.assertEqual(conflicts, [])

    def test_manual_rows_require_a_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manual_dir = Path(tmp)
            (manual_dir / "event.csv").write_text(
                "event_date,red_fighter_name,blue_fighter_name,bout_type,event_name\n"
                "2026-01-01,Alpha,Beta,Lightweight Bout,UFC Manual\n",
                encoding="utf-8",
            )

            with self.assertRaises(ManualRowError):
                load_manual_rows(manual_dir)

    def test_manual_rows_reject_invalid_result_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manual_dir = Path(tmp)
            (manual_dir / "event.csv").write_text(
                "event_date,red_fighter_name,blue_fighter_name,bout_type,event_name,red_fighter_result,blue_fighter_result\n"
                "2026-01-01,Alpha,Beta,Lightweight Bout,UFC Manual,BAD,TOKEN\n",
                encoding="utf-8",
            )

            with self.assertRaises(ManualRowError):
                load_manual_rows(manual_dir)


if __name__ == "__main__":
    unittest.main()
