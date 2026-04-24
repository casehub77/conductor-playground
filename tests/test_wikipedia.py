from __future__ import annotations

import unittest

from ufc_elo.wikipedia import (
    discover_event_titles_from_links,
    parse_event_payload,
    parse_fighter_page_payload,
    parse_year_page_payload,
)


STANDALONE_EVENT_HTML = """
<div class="mw-parser-output">
<table class="infobox"><tbody>
<tr><th class="infobox-above">Strikeforce: Fedor vs. Henderson</th></tr>
<tr><th>Date</th><td>July 30, 2011</td></tr>
<tr><th>Venue</th><td>Sears Centre</td></tr>
<tr><th>City</th><td>Hoffman Estates, Illinois, United States</td></tr>
</tbody></table>
<h2 id="Results">Results</h2>
<table class="toccolours"><tbody>
<tr>
<th>Weight class</th><th></th><th></th><th></th><th>Method</th><th>Round</th><th>Time</th><th>Notes</th>
</tr>
<tr>
<td>Heavyweight</td>
<td><a href="/wiki/Dan_Henderson">Dan Henderson</a></td>
<td>def.</td>
<td><a href="/wiki/Fedor_Emelianenko">Fedor Emelianenko</a></td>
<td>TKO (punches)</td>
<td>1</td>
<td>4:12</td>
<td></td>
</tr>
</tbody></table>
</div>
"""

REDIRECTED_EVENT_HTML = """
<div class="mw-parser-output">
<h2 id="Pride_1">Pride 1</h2>
<table class="infobox"><tbody>
<tr><th class="infobox-above">Pride 1</th></tr>
<tr><th>Date</th><td>October 11, 1997</td></tr>
<tr><th>Venue</th><td>Tokyo Dome</td></tr>
<tr><th>City</th><td>Tokyo, Japan</td></tr>
</tbody></table>
<h3 id="Results">Results</h3>
<table class="toccolours"><tbody>
<tr>
<th>Weight class</th><th></th><th></th><th></th><th>Method</th><th>Round</th><th>Time</th><th>Notes</th>
</tr>
<tr>
<td></td>
<td><a href="/wiki/Rickson_Gracie">Rickson Gracie</a></td>
<td>def.</td>
<td><a href="/wiki/Nobuhiko_Takada">Nobuhiko Takada</a></td>
<td>Submission (armbar)</td>
<td>1</td>
<td>4:47</td>
<td></td>
</tr>
</tbody></table>
<h2 id="See_also">See also</h2>
</div>
"""

YEAR_PAGE_HTML = """
<div class="mw-parser-output">
<table class="infobox"><tbody>
<tr><th class="infobox-above">2010 in Cage Warriors</th></tr>
<tr><th>First date</th><td>May 22, 2010</td></tr>
<tr><th>Last date</th><td>November 27, 2010</td></tr>
</tbody></table>
<h2 id="Cage_Warriors_37:_Right_to_Fight">Cage Warriors 37: Right to Fight</h2>
<table class="infobox"><tbody>
<tr><th class="infobox-above">Cage Warriors 37: Right to Fight</th></tr>
<tr><th>Date</th><td>May 22, 2010</td></tr>
<tr><th>Venue</th><td>The Helix</td></tr>
<tr><th>City</th><td>Dublin, Ireland</td></tr>
</tbody></table>
<h3 id="Results">Results</h3>
<table class="toccolours"><tbody>
<tr>
<th>Weight class</th><th></th><th></th><th></th><th>Method</th><th>Round</th><th>Time</th><th>Notes</th>
</tr>
<tr>
<td>Welterweight</td>
<td><a href="/wiki/Fighter_A">Fighter A</a></td>
<td>def.</td>
<td><a href="/wiki/Fighter_B">Fighter B</a></td>
<td>Decision (unanimous)</td>
<td>3</td>
<td>5:00</td>
<td></td>
</tr>
</tbody></table>
<h2 id="See_also">See also</h2>
</div>
"""

YEAR_PAGE_WITH_METADATA_TABLE_HTML = """
<div class="mw-parser-output">
<h2 id="Events_list">Events list</h2>
<table class="sortable wikitable succession-box"><tbody>
<tr><th>#</th><th>Event Title</th><th>Date</th><th>Arena</th><th>Location</th></tr>
<tr>
<td>37</td>
<td><a href="#Cage_Warriors_37:_Right_to_Fight">Cage Warriors 37: Right to Fight</a></td>
<td>May 22, 2010</td>
<td></td>
<td>Birmingham, England</td>
</tr>
</tbody></table>
<h2 id="Cage_Warriors_37:_Right_to_Fight">Cage Warriors 37: Right to Fight</h2>
<p><b>Results</b></p>
<table class="toccolours"><tbody>
<tr>
<th>Weight class</th><th></th><th></th><th></th><th>Method</th><th>Round</th><th>Time</th><th>Notes</th>
</tr>
<tr>
<td>Welterweight</td>
<td><a href="/wiki/Fighter_A">Fighter A</a></td>
<td>def.</td>
<td><a href="/wiki/Fighter_B">Fighter B</a></td>
<td>Decision (unanimous)</td>
<td>3</td>
<td>5:00</td>
<td></td>
</tr>
</tbody></table>
<h2 id="See_also">See also</h2>
</div>
"""

FIGHTER_PAGE_HTML = """
<div class="mw-parser-output">
<h2 id="Mixed_martial_arts_record">Mixed martial arts record</h2>
<table class="wikitable mw-collapsible">
<tbody>
<tr><td>29 matches</td><td>28 wins</td><td>1 loss</td></tr>
</tbody>
</table>
<table class="wikitable">
<tbody>
<tr>
<th>Res.</th><th>Record</th><th>Opponent</th><th>Method</th><th>Event</th><th>Date</th><th>Round</th><th>Time</th><th>Location</th><th>Notes</th>
</tr>
<tr>
<td>Win</td><td>12-1</td><td><a href="/wiki/Fighter_B">Fighter B</a></td><td>Decision (unanimous)</td><td><a href="/wiki/Cage_Warriors_1">Cage Warriors 1</a></td><td>May 1, 2014</td><td>3</td><td>5:00</td><td>London, England</td><td>Lightweight bout</td>
</tr>
<tr>
<td>Loss</td><td>11-1</td><td><a href="/wiki/Fighter_C">Fighter C</a></td><td>Submission (rear-naked choke)</td><td>Regional 10</td><td>April 1, 2013</td><td>2</td><td>3:10</td><td>Dublin, Ireland</td><td></td>
</tr>
<tr>
<td>NC</td><td>11-0</td><td><a href="/wiki/Fighter_D">Fighter D</a></td><td>No contest</td><td>Regional 9</td><td>March 1, 2013</td><td>1</td><td>1:10</td><td>Rome, Italy</td><td>Catchweight 165 lb</td>
</tr>
</tbody>
</table>
</div>
"""


class WikipediaParsingTests(unittest.TestCase):
    def test_discover_event_titles_filters_links(self) -> None:
        payload = {
            "parse": {
                "links": [
                    {"ns": 0, "title": "Strikeforce: Fedor vs. Henderson", "exists": True},
                    {"ns": 0, "title": "List of UFC events", "exists": True},
                    {"ns": 0, "title": "WEC 1", "exists": True},
                    {"ns": 10, "title": "Template:Strikeforce Events", "exists": True},
                ]
            }
        }
        titles = discover_event_titles_from_links(payload, [r"^Strikeforce:", r"^WEC \d+"], [r"^List of "])
        self.assertEqual(titles, ["Strikeforce: Fedor vs. Henderson", "WEC 1"])

    def test_parse_standalone_event_payload(self) -> None:
        payload = {"parse": {"title": "Strikeforce: Fedor vs. Henderson", "redirects": [], "text": STANDALONE_EVENT_HTML}}
        rows = parse_event_payload(payload, "Strikeforce: Fedor vs. Henderson")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["red_fighter_name"], "Dan Henderson")
        self.assertEqual(rows[0]["blue_fighter_name"], "Fedor Emelianenko")
        self.assertEqual(rows[0]["fight_outcome"], "red_win")
        self.assertEqual(rows[0]["bout_type"], "Heavyweight Bout")
        self.assertEqual(rows[0]["event_date"], "2011-07-30")
        self.assertEqual(rows[0]["event_location"], "Sears Centre, Hoffman Estates, Illinois, United States")

    def test_parse_redirected_event_payload(self) -> None:
        payload = {
            "parse": {
                "title": "1997 in Pride FC",
                "redirects": [{"from": "Pride 1", "to": "1997 in Pride FC", "tofragment": "Pride 1"}],
                "text": REDIRECTED_EVENT_HTML,
            }
        }
        rows = parse_event_payload(payload, "Pride 1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_name"], "Pride 1")
        self.assertEqual(rows[0]["red_fighter_name"], "Rickson Gracie")
        self.assertEqual(rows[0]["blue_fighter_name"], "Nobuhiko Takada")
        self.assertEqual(rows[0]["bout_type"], "Open Weight Bout")
        self.assertEqual(rows[0]["event_date"], "1997-10-11")

    def test_parse_year_page_payload(self) -> None:
        payload = {
            "parse": {
                "title": "2010 in Cage Warriors",
                "text": YEAR_PAGE_HTML,
                "tocdata": {
                    "sections": [
                        {"tocLevel": 1, "line": "Cage Warriors 37: Right to Fight", "number": "1", "anchor": "Cage_Warriors_37:_Right_to_Fight"},
                        {"tocLevel": 2, "line": "Results", "number": "1.1", "anchor": "Results"},
                        {"tocLevel": 1, "line": "See also", "number": "2", "anchor": "See_also"},
                    ]
                },
            }
        }
        rows = parse_year_page_payload(payload, "2010 in Cage Warriors")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_name"], "Cage Warriors 37: Right to Fight")
        self.assertEqual(rows[0]["event_date"], "2010-05-22")
        self.assertEqual(rows[0]["bout_type"], "Welterweight Bout")
        self.assertIn("#Cage_Warriors_37%3A_Right_to_Fight", rows[0]["source_url"])

    def test_parse_year_page_payload_with_metadata_table(self) -> None:
        payload = {
            "parse": {
                "title": "2010 in Cage Warriors",
                "text": YEAR_PAGE_WITH_METADATA_TABLE_HTML,
                "tocdata": {
                    "sections": [
                        {"tocLevel": 1, "line": "Events list", "number": "1", "anchor": "Events_list"},
                        {"tocLevel": 1, "line": "Cage Warriors 37: Right to Fight", "number": "2", "anchor": "Cage_Warriors_37:_Right_to_Fight"},
                        {"tocLevel": 2, "line": "Results", "number": "2.1", "anchor": "Results"},
                    ]
                },
            }
        }
        rows = parse_year_page_payload(payload, "2010 in Cage Warriors")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_date"], "2010-05-22")
        self.assertEqual(rows[0]["event_location"], "Birmingham, England")

    def test_parse_fighter_page_payload(self) -> None:
        payload = {
            "parse": {
                "title": "Example Fighter",
                "text": FIGHTER_PAGE_HTML,
                "tocdata": {
                    "sections": [
                        {"tocLevel": 1, "line": "Mixed martial arts record", "number": "1", "anchor": "Mixed_martial_arts_record"},
                    ]
                },
            }
        }
        rows = parse_fighter_page_payload(payload, "Example Fighter", "Example Fighter")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["red_fighter_name"], "Example Fighter")
        self.assertEqual(rows[0]["blue_fighter_name"], "Fighter B")
        self.assertEqual(rows[0]["fight_outcome"], "red_win")
        self.assertEqual(rows[0]["bout_type"], "Lightweight Bout")
        self.assertEqual(rows[1]["red_fighter_name"], "Fighter C")
        self.assertEqual(rows[1]["blue_fighter_name"], "Example Fighter")
        self.assertEqual(rows[1]["fight_outcome"], "red_win")
        self.assertEqual(rows[2]["fight_outcome"], "no_contest")
        self.assertEqual(rows[2]["bout_type"], "Catch Weight Bout")


if __name__ == "__main__":
    unittest.main()
