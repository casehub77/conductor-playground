from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ufc_elo.ingestion import (
    discover_ufc_event_urls,
    fetch_ufc_official_recent_rows,
    is_completed_ufc_event,
    parse_ufc_official_event,
    parse_ufc_official_event_date,
)


COMPLETED_EVENT_HTML = """
<html>
<head>
  <title>UFC Fight Night: Burns vs Malott | UFC Winnipeg</title>
  <meta name="description" content="Don't Miss UFC Fight Night: Burns vs Malott, Live From Canada Life Centre In Winnipeg, Canada On April 18, 2026" />
</head>
<body>
  <div>Final Results &amp; Interviews</div>
  <div class="c-listing-fight" data-fmid="12673">
    <div class="c-listing-fight__corner-body--red">
      <div class="c-listing-fight__outcome--loss">Loss</div>
    </div>
    <div class="c-listing-fight__details">
      <div class="c-listing-fight__class-text">Welterweight Bout</div>
      <div class="c-listing-fight__names-row">
        <div class="c-listing-fight__corner-name c-listing-fight__corner-name--red">
          <a href="/athlete/gilbert-burns">
            <span class="c-listing-fight__corner-given-name">Gilbert</span>
            <span class="c-listing-fight__corner-family-name">Burns</span>
          </a>
        </div>
        <div class="c-listing-fight__corner-name c-listing-fight__corner-name--blue">
          <a href="/athlete/mike-malott">
            <span class="c-listing-fight__corner-given-name">Mike</span>
            <span class="c-listing-fight__corner-family-name">Malott</span>
          </a>
        </div>
      </div>
      <div class="c-listing-fight__result-text round">3</div>
      <div class="c-listing-fight__result-text time">2:08</div>
      <div class="c-listing-fight__result-text method">KO/TKO</div>
    </div>
    <div class="c-listing-fight__corner-body--blue">
      <div class="c-listing-fight__outcome--win">Win</div>
    </div>
  </div>
</body>
</html>
"""


UPCOMING_EVENT_HTML = """
<html>
<head>
  <title>UFC Fight Night: Sterling vs Zalal | UFC</title>
  <meta name="description" content="Don't Miss A Moment Of UFC Fight Night: Sterling vs Zalal, Live From Meta APEX In Las Vegas, Nevada On April 25, 2026" />
</head>
<body>
  <div class="c-listing-fight" data-fmid="12720">
    <div class="c-listing-fight__details">
      <div class="c-listing-fight__class-text">Featherweight Bout</div>
      <div class="c-listing-fight__names-row">
        <div class="c-listing-fight__corner-name c-listing-fight__corner-name--red">
          <a href="/athlete/aljamain-sterling">
            <span class="c-listing-fight__corner-given-name">Aljamain</span>
            <span class="c-listing-fight__corner-family-name">Sterling</span>
          </a>
        </div>
        <div class="c-listing-fight__corner-name c-listing-fight__corner-name--blue">
          <a href="/athlete/youssef-zalal">
            <span class="c-listing-fight__corner-given-name">Youssef</span>
            <span class="c-listing-fight__corner-family-name">Zalal</span>
          </a>
        </div>
      </div>
      <div class="c-listing-fight__result-text round"></div>
      <div class="c-listing-fight__result-text time"></div>
      <div class="c-listing-fight__result-text method"></div>
    </div>
    <div class="c-listing-fight__corner-body--red">
      <div class="c-listing-fight__outcome"></div>
    </div>
    <div class="c-listing-fight__corner-body--blue">
      <div class="c-listing-fight__outcome"></div>
    </div>
  </div>
</body>
</html>
"""


EVENTS_PAGE_HTML = """
<html><body>
<div>Upcoming</div>
<a href="/event/ufc-fight-night-april-25-2026">Sterling vs Zalal</a>
<div>Past</div>
<h3 class="c-card-event--result__headline"><a href="/event/ufc-fight-night-april-18-2026">Burns vs Malott</a></h3>
<a href="/event/ufc-fight-night-april-18-2026">Sat, Apr 18 / 8:00 PM EDT / Main Card</a>
<h3 class="c-card-event--result__headline"><a href="/event/ufc-327">Prochazka vs Ulberg</a></h3>
<a href="/event/ufc-327">Sat, Apr 11 / 9:00 PM EDT / Main Card</a>
</body></html>
"""


class OfficialUfcFallbackTest(unittest.TestCase):
    def test_completed_event_detection(self) -> None:
        self.assertTrue(is_completed_ufc_event(COMPLETED_EVENT_HTML))
        self.assertFalse(is_completed_ufc_event(UPCOMING_EVENT_HTML))

    def test_parse_official_event_date(self) -> None:
        self.assertEqual(parse_ufc_official_event_date(COMPLETED_EVENT_HTML).isoformat(), "2026-04-18")

    def test_parse_official_event_rows(self) -> None:
        rows = parse_ufc_official_event(COMPLETED_EVENT_HTML, "https://www.ufc.com/event/ufc-fight-night-april-18-2026", parse_ufc_official_event_date(COMPLETED_EVENT_HTML))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_name"], "UFC Fight Night: Burns vs Malott")
        self.assertEqual(rows[0]["red_fighter_name"], "Gilbert Burns")
        self.assertEqual(rows[0]["blue_fighter_name"], "Mike Malott")
        self.assertEqual(rows[0]["fight_outcome"], "blue_win")
        self.assertEqual(rows[0]["method"], "KO/TKO")
        self.assertEqual(rows[0]["round"], "3")
        self.assertEqual(rows[0]["time"], "2:08")
        self.assertEqual(rows[0]["bout_type"], "Welterweight Bout")

    def test_discover_event_urls_prefers_past_events(self) -> None:
        with patch("ufc_elo.ingestion.fetch_url", return_value=EVENTS_PAGE_HTML):
            urls = discover_ufc_event_urls(max_pages=1, max_events=3)
        self.assertEqual(
            urls,
            [
                "https://www.ufc.com/event/ufc-fight-night-april-18-2026",
                "https://www.ufc.com/event/ufc-327",
            ],
        )

    def test_fetch_official_recent_rows_skips_upcoming_cards(self) -> None:
        def fake_fetch(url: str, timeout: int = 30) -> str:
            if "events" in url:
                return EVENTS_PAGE_HTML
            if "april-18-2026" in url:
                return COMPLETED_EVENT_HTML
            return UPCOMING_EVENT_HTML

        with patch("ufc_elo.ingestion.fetch_url", side_effect=fake_fetch):
            rows = fetch_ufc_official_recent_rows(days_back=30, max_events=2, max_pages=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_date"], "2026-04-18")


if __name__ == "__main__":
    unittest.main()
