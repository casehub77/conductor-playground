from __future__ import annotations

import html as html_lib
import re
import time
import urllib.error
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .ingestion import ScraperSchemaError, clean_text, clean_fighter_name, fetch_url
from .util import iso_date, parse_date, read_json, slugify, write_json

WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_REQUEST_DELAY_SECONDS = 0.25
WIKIPEDIA_MANUAL_FIELDS = [
    "red_fighter_name",
    "blue_fighter_name",
    "event_date",
    "red_fighter_result",
    "blue_fighter_result",
    "fight_outcome",
    "method",
    "round",
    "time",
    "bout_type",
    "event_name",
    "event_location",
    "source_url",
    "source_title",
]
GENERIC_SECTION_TITLES = {
    "event list",
    "events list",
    "list of events",
    "title fights",
    "see also",
    "references",
    "external links",
    "background",
    "bonus awards",
    "tournament brackets",
    "results",
}


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[dict[str, Any]]] = []
        self._current_row: list[dict[str, Any]] | None = None
        self._current_cell: dict[str, Any] | None = None
        self._current_link: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            attrs_map = dict(attrs)
            self._current_cell = {
                "tag": tag,
                "text_parts": [],
                "links": [],
                "colspan": int(attrs_map.get("colspan") or "1"),
            }
        elif tag == "a" and self._current_cell is not None:
            self._current_link = []
        elif tag == "br" and self._current_cell is not None:
            self._current_cell["text_parts"].append(" ")

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell["text_parts"].append(data)
        if self._current_link is not None:
            self._current_link.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current_cell is not None and self._current_link is not None:
            link_text = clean_text(" ".join(self._current_link))
            if link_text:
                self._current_cell["links"].append(link_text)
            self._current_link = None
        elif tag in {"td", "th"} and self._current_row is not None and self._current_cell is not None:
            text = clean_text(html_lib.unescape(" ".join(self._current_cell["text_parts"])))
            self._current_row.append(
                {
                    "tag": self._current_cell["tag"],
                    "text": text,
                    "links": self._current_cell["links"],
                    "colspan": self._current_cell["colspan"],
                }
            )
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            if any(cell["text"] or cell["links"] for cell in self._current_row):
                self.rows.append(self._current_row)
            self._current_row = None


def fetch_api_payload(
    params: dict[str, str],
    cache_dir: Path | None = None,
    cache_key: str | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    cache_path = None
    if cache_dir and cache_key:
        cache_path = cache_dir / f"{slugify(cache_key)}.json"
        if cache_path.exists() and not refresh:
            cached = read_json(cache_path, None)
            if isinstance(cached, dict):
                return cached
    query = urllib.parse.urlencode(params)
    data: dict[str, Any] | None = None
    for attempt in range(5):
        try:
            if WIKIPEDIA_REQUEST_DELAY_SECONDS > 0:
                time.sleep(WIKIPEDIA_REQUEST_DELAY_SECONDS)
            payload = fetch_url(f"{WIKIPEDIA_API_URL}?{query}")
            data = read_json_from_text(payload)
            break
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 4:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            wait_seconds = float(retry_after) if retry_after and retry_after.isdigit() else float(2 ** attempt)
            time.sleep(wait_seconds)
    if data is None:
        raise ScraperSchemaError("Wikipedia API returned no data.")
    if cache_path:
        write_json(cache_path, data)
    return data


def read_json_from_text(text: str) -> dict[str, Any]:
    import json

    return json.loads(text)


def discover_event_titles_from_links(
    payload: dict[str, Any],
    title_patterns: list[str],
    exclude_patterns: list[str] | None = None,
) -> list[str]:
    links = payload.get("parse", {}).get("links", [])
    title_re = [re.compile(pattern) for pattern in title_patterns]
    exclude_re = [re.compile(pattern) for pattern in (exclude_patterns or [])]
    titles: list[str] = []
    seen: set[str] = set()
    for link in links:
        if link.get("ns") != 0 or not link.get("exists"):
            continue
        title = clean_text(link.get("title", ""))
        if not title or title in seen:
            continue
        if not any(pattern.search(title) for pattern in title_re):
            continue
        if any(pattern.search(title) for pattern in exclude_re):
            continue
        seen.add(title)
        titles.append(title)
    return titles


def discover_event_titles(
    list_page: str,
    title_patterns: list[str],
    exclude_patterns: list[str] | None = None,
    cache_dir: Path | None = None,
    refresh: bool = False,
) -> list[str]:
    payload = fetch_api_payload(
        {
            "action": "parse",
            "page": list_page,
            "prop": "links",
            "formatversion": "2",
            "format": "json",
        },
        cache_dir=cache_dir,
        cache_key=f"links-{list_page}",
        refresh=refresh,
    )
    return discover_event_titles_from_links(payload, title_patterns, exclude_patterns)


def discover_titles_from_search(
    query: str,
    title_patterns: list[str],
    exclude_patterns: list[str] | None = None,
    cache_dir: Path | None = None,
    refresh: bool = False,
    limit: int = 50,
) -> list[str]:
    payload = fetch_api_payload(
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": str(limit),
            "format": "json",
        },
        cache_dir=cache_dir,
        cache_key=f"search-{query}",
        refresh=refresh,
    )
    links = [{"ns": 0, "title": item.get("title", ""), "exists": True} for item in payload.get("query", {}).get("search", [])]
    return discover_event_titles_from_links({"parse": {"links": links}}, title_patterns, exclude_patterns)


def discover_titles_from_allpages_prefix(
    prefix: str,
    title_patterns: list[str],
    exclude_patterns: list[str] | None = None,
    cache_dir: Path | None = None,
    refresh: bool = False,
    limit: int = 500,
) -> list[str]:
    payload = fetch_api_payload(
        {
            "action": "query",
            "list": "allpages",
            "apprefix": prefix,
            "aplimit": str(limit),
            "format": "json",
        },
        cache_dir=cache_dir,
        cache_key=f"allpages-{prefix}",
        refresh=refresh,
    )
    links = [{"ns": 0, "title": item.get("title", ""), "exists": True} for item in payload.get("query", {}).get("allpages", [])]
    return discover_event_titles_from_links({"parse": {"links": links}}, title_patterns, exclude_patterns)


def fetch_event_payload(title: str, cache_dir: Path | None = None, refresh: bool = False) -> dict[str, Any]:
    return fetch_api_payload(
        {
            "action": "parse",
            "page": title,
            "prop": "text|tocdata",
            "redirects": "1",
            "formatversion": "2",
            "format": "json",
        },
        cache_dir=cache_dir,
        cache_key=f"event-{title}",
        refresh=refresh,
    )


def fetch_page_payload(title: str, cache_dir: Path | None = None, refresh: bool = False) -> dict[str, Any]:
    return fetch_api_payload(
        {
            "action": "parse",
            "page": title,
            "prop": "text|tocdata",
            "redirects": "1",
            "formatversion": "2",
            "format": "json",
        },
        cache_dir=cache_dir,
        cache_key=f"page-{title}",
        refresh=refresh,
    )


def resolve_fighter_page_title(name: str, cache_dir: Path | None = None, refresh: bool = False) -> str | None:
    title = clean_text(name)
    if not title:
        return None
    exact = fetch_api_payload(
        {
            "action": "query",
            "titles": title,
            "redirects": "1",
            "formatversion": "2",
            "format": "json",
        },
        cache_dir=cache_dir,
        cache_key=f"fighter-title-{title}",
        refresh=refresh,
    )
    pages = exact.get("query", {}).get("pages", [])
    if pages and not pages[0].get("missing"):
        resolved = clean_text(pages[0].get("title", ""))
        if resolved:
            return resolved

    search = fetch_api_payload(
        {
            "action": "query",
            "list": "search",
            "srsearch": f'intitle:"{title}" "mixed martial artist"',
            "srlimit": "5",
            "format": "json",
        },
        cache_dir=cache_dir,
        cache_key=f"fighter-search-{title}",
        refresh=refresh,
    )
    candidates = [clean_text(item.get("title", "")) for item in search.get("query", {}).get("search", [])]
    normalized = clean_text(name).lower()
    for candidate in candidates:
        if candidate.lower() == normalized:
            return candidate
    for candidate in candidates:
        lowered = candidate.lower()
        if normalized in lowered and "list of" not in lowered:
            return candidate
    return None


def parse_event_payload(payload: dict[str, Any], requested_title: str) -> list[dict[str, str]]:
    parse = payload.get("parse", {})
    html = parse.get("text", "")
    if not html:
        raise ScraperSchemaError(f"Wikipedia page missing HTML for {requested_title}.")

    redirects = parse.get("redirects", [])
    fragment = clean_text((redirects[0].get("tofragment") if redirects else "") or "")
    event_html = extract_event_section_html(html, fragment) if fragment else html
    if not event_html:
        raise ScraperSchemaError(f"Could not isolate event section for {requested_title}.")

    rows = parse_event_section(event_html, requested_title, requested_title, fragment)
    if not rows:
        raise ScraperSchemaError(f"No Wikipedia fight rows parsed for {requested_title}.")
    return rows


def parse_year_page_payload(payload: dict[str, Any], requested_title: str) -> list[dict[str, str]]:
    parse = payload.get("parse", {})
    html = parse.get("text", "")
    toc = parse.get("tocdata", {})
    sections = toc.get("sections", []) if isinstance(toc, dict) else []
    if not html or not sections:
        raise ScraperSchemaError(f"Wikipedia year page missing sections for {requested_title}.")

    event_sections = [section for section in sections if is_event_section(section, sections)]
    metadata_by_event = parse_year_page_event_metadata(html, event_sections)
    rows: list[dict[str, str]] = []
    errors: list[str] = []
    for section in event_sections:
        anchor = section.get("anchor", "")
        line = clean_text(section.get("line", ""))
        if not anchor or not line:
            continue
        event_html = extract_section_html_by_anchor(html, anchor)
        if not event_html:
            continue
        try:
            rows.extend(parse_event_section(event_html, requested_title, requested_title, line, anchor, metadata_by_event.get(line)))
        except ScraperSchemaError as exc:
            errors.append(f"{line}: {exc}")
    if not rows:
        detail = f" Errors: {'; '.join(errors[:3])}" if errors else ""
        raise ScraperSchemaError(f"No Wikipedia event sections parsed for {requested_title}.{detail}")
    return rows


def parse_fighter_page_payload(payload: dict[str, Any], requested_title: str, fighter_name: str) -> list[dict[str, str]]:
    parse = payload.get("parse", {})
    html = parse.get("text", "")
    if not html:
        raise ScraperSchemaError(f"Wikipedia fighter page missing HTML for {requested_title}.")

    section_html = extract_mma_record_section(html, parse.get("tocdata", {}))
    if not section_html:
        raise ScraperSchemaError(f"Mixed martial arts record section missing for {requested_title}.")
    table_html = extract_record_history_table(section_html)
    if not table_html:
        raise ScraperSchemaError(f"Professional MMA record table missing for {requested_title}.")
    rows = parse_fighter_record_table(table_html, fighter_name, requested_title)
    if not rows:
        raise ScraperSchemaError(f"No fighter record rows parsed for {requested_title}.")
    return rows


def parse_event_section(
    event_html: str,
    requested_title: str,
    source_title: str,
    fragment: str = "",
    anchor: str = "",
    fallback_metadata: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    event_name = parse_event_name(event_html, requested_title, fragment)
    infobox_html = extract_first_table_by_class(event_html, "infobox")
    infobox = parse_infobox_fields(infobox_html) if infobox_html else {}

    event_date_raw = infobox.get("date") or infobox.get("first date") or (fallback_metadata or {}).get("date", "")
    if not event_date_raw:
        raise ScraperSchemaError(f"Wikipedia date missing for {requested_title}.")
    event_date = parse_date(normalize_date_text(event_date_raw))

    venue = infobox.get("venue", "") or (fallback_metadata or {}).get("venue", "")
    city = infobox.get("city", "") or (fallback_metadata or {}).get("location", "")
    location = ", ".join(part for part in [venue, city] if part)

    results_html = extract_results_table(event_html)
    rows = parse_results_table(results_html, event_name, iso_date(event_date), location, source_title)
    if anchor:
        anchor_url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(source_title.replace(' ', '_'))}#{urllib.parse.quote(anchor)}"
        for row in rows:
            row["source_url"] = anchor_url
    return rows


def parse_event_name(event_html: str, requested_title: str, fragment: str) -> str:
    infobox_html = extract_first_table_by_class(event_html, "infobox")
    if infobox_html:
        parser = TableParser()
        parser.feed(infobox_html)
        for row in parser.rows:
            if len(row) == 1 and row[0]["tag"] == "th":
                title = clean_text(row[0]["text"])
                if title:
                    return title
    return fragment or requested_title


def extract_event_section_html(html: str, fragment: str) -> str:
    anchor = fragment.replace(" ", "_")
    return extract_section_html_by_anchor(html, anchor)


def extract_section_html_by_anchor(html: str, anchor: str) -> str:
    match = re.search(rf'<h([1-6])\b[^>]*\bid="{re.escape(anchor)}"[^>]*>', html)
    if not match:
        return ""
    level = int(match.group(1))
    start = match.start()
    heading_re = re.compile(r'<h([1-6])\b[^>]*\bid="[^"]+"[^>]*>')
    end = len(html)
    for later in heading_re.finditer(html, match.end()):
        if int(later.group(1)) <= level:
            end = later.start()
            break
    return html[start:end]


def extract_results_table(event_html: str) -> str:
    match = re.search(r"<h[1-6]\b[^>]*>.*?Results.*?</h[1-6]>", event_html, re.I | re.S)
    if not match:
        match = re.search(r"<p\b[^>]*>\s*(?:<b>)?\s*Results\s*(?:</b>)?\s*</p>", event_html, re.I | re.S)
    if not match:
        raise ScraperSchemaError("Wikipedia results heading missing.")
    for class_name in ("toccolours", "wikitable"):
        table_html = extract_first_table_by_class(event_html, class_name, start_index=match.end())
        if table_html:
            return table_html
    table_html = extract_first_table(event_html, start_index=match.end())
    if not table_html:
        raise ScraperSchemaError("Wikipedia results table missing.")
    return table_html


def extract_first_table(event_html: str, start_index: int = 0) -> str:
    match = re.search(r"<table\b", event_html[start_index:], re.I)
    if not match:
        return ""
    return extract_balanced_table(event_html, start_index + match.start())


def extract_first_table_by_class(event_html: str, class_name: str, start_index: int = 0) -> str:
    match = re.search(rf'<table\b[^>]*class="[^"]*\b{re.escape(class_name)}\b[^"]*"[^>]*>', event_html[start_index:], re.I)
    if not match:
        return ""
    return extract_balanced_table(event_html, start_index + match.start())


def extract_balanced_table(html: str, start: int) -> str:
    token_re = re.compile(r"</?table\b", re.I)
    depth = 0
    end = start
    for token in token_re.finditer(html, start):
        close = html[token.start() + 1] == "/"
        if not close:
            depth += 1
        else:
            depth -= 1
        end = html.find(">", token.start())
        if end == -1:
            break
        end += 1
        if depth == 0:
            return html[start:end]
    return ""


def parse_infobox_fields(infobox_html: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    parser = TableParser()
    parser.feed(infobox_html)
    for row in parser.rows:
        if len(row) < 2:
            continue
        label = clean_text(row[0]["text"]).lower()
        value = clean_text(row[1]["text"])
        if label and value:
            fields[label] = value
    return fields


def parse_results_table(
    table_html: str,
    event_name: str,
    event_date: str,
    event_location: str,
    source_title: str,
) -> list[dict[str, str]]:
    parser = TableParser()
    parser.feed(table_html)
    rows: list[dict[str, str]] = []
    for row in parser.rows:
        if not is_result_row(row):
            continue
        cells = expand_row(row)
        parsed = parse_result_row(cells)
        if not parsed:
            continue
        rows.append(
            {
                **parsed,
                "event_date": event_date,
                "event_name": event_name,
                "event_location": event_location,
                "source_url": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(source_title.replace(' ', '_'))}",
                "source_title": source_title,
            }
        )
    return rows


def is_result_row(row: list[dict[str, Any]]) -> bool:
    texts = [cell["text"].lower() for cell in row]
    if len(row) < 7:
        return False
    if any("weight class" in text for text in texts):
        return False
    if len([cell for cell in row if cell["tag"] == "th"]) >= len(row) - 1:
        return False
    return True


def expand_row(row: list[dict[str, Any]]) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for cell in row:
        expanded.extend([cell] * max(1, int(cell.get("colspan") or 1)))
    return expanded


def parse_result_row(cells: list[dict[str, Any]]) -> dict[str, str] | None:
    if len(cells) < 7:
        return None
    weight_class = normalize_weight_class(cells[0]["text"])
    red_name = extract_fighter_name(cells[1])
    separator = clean_text(cells[2]["text"]).lower()
    blue_name = extract_fighter_name(cells[3])
    method = clean_text(cells[4]["text"])
    round_value = clean_text(cells[5]["text"])
    time_value = clean_text(cells[6]["text"])
    if not red_name or not blue_name or not method or not round_value or not time_value:
        return None
    outcome, red_result, blue_result = parse_outcome(separator, method)
    if outcome == "unknown":
        return None
    return {
        "red_fighter_name": red_name,
        "blue_fighter_name": blue_name,
        "red_fighter_result": red_result,
        "blue_fighter_result": blue_result,
        "fight_outcome": outcome,
        "method": method,
        "round": round_value,
        "time": time_value,
        "bout_type": f"{weight_class} Bout",
    }


def extract_fighter_name(cell: dict[str, Any]) -> str:
    candidate = cell["links"][-1] if cell.get("links") else cell.get("text", "")
    candidate = re.sub(r"\s+\(c\)$", "", candidate)
    return clean_fighter_name(candidate)


def parse_outcome(separator: str, method: str) -> tuple[str, str, str]:
    method_lower = method.lower()
    if separator.startswith("def"):
        return ("red_win", "W", "L")
    if "draw" in separator or "draw" in method_lower:
        return ("draw", "D", "D")
    if "no contest" in separator or "no contest" in method_lower:
        return ("no_contest", "NC", "NC")
    if separator in {"vs.", "vs", ""} and "split draw" in method_lower:
        return ("draw", "D", "D")
    return ("unknown", "", "")


def normalize_weight_class(value: str) -> str:
    weight_class = clean_text(value)
    if not weight_class:
        return "Open Weight"
    if weight_class.lower() in {"openweight", "open weight"}:
        return "Open Weight"
    return weight_class


def is_event_section(section: dict[str, Any], sections: list[dict[str, Any]]) -> bool:
    line = clean_text(section.get("line", "")).lower()
    if not line or line in GENERIC_SECTION_TITLES or line.startswith("results"):
        return False
    level = int(section.get("tocLevel") or 0)
    number = str(section.get("number", ""))
    prefix = f"{number}."
    for candidate in sections:
        child_number = str(candidate.get("number", ""))
        if candidate is section or not child_number.startswith(prefix):
            continue
        child_level = int(candidate.get("tocLevel") or 0)
        if child_level <= level:
            continue
        child_line = clean_text(candidate.get("line", "")).lower()
        if child_line.startswith("results"):
            return True
    return False


def parse_year_page_event_metadata(html: str, event_sections: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    if not event_sections:
        return {}
    start_match = re.search(r'<h[1-6]\b[^>]*\bid="(?:Events_list|Event_list|List_of_events)"[^>]*>', html)
    if not start_match:
        return {}
    first_anchor = event_sections[0].get("anchor", "")
    if not first_anchor:
        return {}
    end_match = re.search(rf'<h[1-6]\b[^>]*\bid="{re.escape(first_anchor)}"[^>]*>', html)
    if not end_match:
        return {}
    metadata_html = html[start_match.end():end_match.start()]
    table_html = extract_first_table_by_class(metadata_html, "wikitable")
    if not table_html:
        return {}
    parser = TableParser()
    parser.feed(table_html)
    rows = parser.rows
    if len(rows) < 2:
        return {}
    headers = [clean_text(cell["text"]).lower() for cell in expand_row(rows[0])]
    event_index = first_matching_index(headers, {"event", "event title"})
    date_index = first_matching_index(headers, {"date"})
    venue_index = first_matching_index(headers, {"arena", "venue"})
    location_index = first_matching_index(headers, {"location", "city"})
    if event_index is None or date_index is None:
        return {}

    metadata: dict[str, dict[str, str]] = {}
    for row in rows[1:]:
        cells = expand_row(row)
        if len(cells) <= max(event_index, date_index):
            continue
        event_name = clean_text(cells[event_index]["links"][-1] if cells[event_index].get("links") else cells[event_index]["text"])
        date_value = clean_text(cells[date_index]["text"])
        if not event_name or not date_value:
            continue
        metadata[event_name] = {
            "date": date_value,
            "venue": clean_text(cells[venue_index]["text"]) if venue_index is not None and len(cells) > venue_index else "",
            "location": clean_text(cells[location_index]["text"]) if location_index is not None and len(cells) > location_index else "",
        }
    return metadata


def first_matching_index(headers: list[str], matches: set[str]) -> int | None:
    for index, header in enumerate(headers):
        if header in matches:
            return index
    return None


def strip_html(value: str) -> str:
    text = re.sub(r"<sup\b.*?</sup>", " ", value, flags=re.S)
    text = re.sub(r"<br\s*/?>", ", ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return clean_text(html_lib.unescape(text))


def normalize_date_text(value: str) -> str:
    cleaned = clean_text(value)
    match = re.search(r"([A-Za-z]+ \d{1,2}, \d{4})", cleaned)
    if match:
        return match.group(1)
    return cleaned


def extract_mma_record_section(html: str, tocdata: dict[str, Any]) -> str:
    sections = tocdata.get("sections", []) if isinstance(tocdata, dict) else []
    for section in sections:
        line = clean_text(section.get("line", "")).lower()
        anchor = clean_text(section.get("anchor", ""))
        if line == "mixed martial arts record" and anchor:
            return extract_section_html_by_anchor(html, anchor)
    return extract_section_html_by_anchor(html, "Mixed_martial_arts_record")


def extract_record_history_table(section_html: str) -> str:
    starts = [match.start() for match in re.finditer(r"<table\b", section_html, re.I)]
    for start in starts:
        table_html = extract_balanced_table(section_html, start)
        parser = TableParser()
        parser.feed(table_html)
        if not parser.rows:
            continue
        headers = [clean_text(cell["text"]).lower().rstrip(".") for cell in expand_row(parser.rows[0])]
        if "opponent" in headers and "event" in headers and "date" in headers and ("res" in headers or "result" in headers):
            return table_html
    return ""


def parse_fighter_record_table(table_html: str, fighter_name: str, source_title: str) -> list[dict[str, str]]:
    parser = TableParser()
    parser.feed(table_html)
    if len(parser.rows) < 2:
        return []
    headers = [clean_text(cell["text"]).lower().rstrip(".") for cell in expand_row(parser.rows[0])]
    index_map = {
        "result": find_header_index(headers, {"res", "result"}),
        "opponent": find_header_index(headers, {"opponent"}),
        "method": find_header_index(headers, {"method"}),
        "event": find_header_index(headers, {"event"}),
        "date": find_header_index(headers, {"date"}),
        "round": find_header_index(headers, {"round"}),
        "time": find_header_index(headers, {"time"}),
        "location": find_header_index(headers, {"location"}),
        "notes": find_header_index(headers, {"notes"}),
    }
    required = ("result", "opponent", "method", "event", "date")
    if any(index_map[key] is None for key in required):
        return []

    rows: list[dict[str, str]] = []
    for row in parser.rows[1:]:
        cells = expand_row(row)
        parsed = parse_fighter_record_row(cells, index_map, fighter_name, source_title)
        if parsed:
            rows.append(parsed)
    return rows


def parse_fighter_record_row(
    cells: list[dict[str, Any]],
    index_map: dict[str, int | None],
    fighter_name: str,
    source_title: str,
) -> dict[str, str] | None:
    result_index = index_map["result"]
    opponent_index = index_map["opponent"]
    method_index = index_map["method"]
    event_index = index_map["event"]
    date_index = index_map["date"]
    if result_index is None or opponent_index is None or method_index is None or event_index is None or date_index is None:
        return None
    needed = [result_index, opponent_index, method_index, event_index, date_index]
    if len(cells) <= max(needed):
        return None

    result = normalize_record_result(cells[result_index]["text"])
    if not result:
        return None
    fighter = clean_fighter_name(fighter_name)
    opponent = extract_fighter_name(cells[opponent_index])
    event_name = clean_text(cells[event_index]["links"][-1] if cells[event_index].get("links") else cells[event_index]["text"])
    method = clean_text(cells[method_index]["text"])
    date_value = clean_text(cells[date_index]["text"])
    if not fighter or not opponent or not event_name or not method or not date_value:
        return None
    if event_name.lower().startswith("ufc"):
        return None
    try:
        parsed_date = parse_date(normalize_date_text(date_value))
    except ValueError:
        return None

    round_value = read_optional_cell(cells, index_map["round"])
    time_value = read_optional_cell(cells, index_map["time"])
    location = read_optional_cell(cells, index_map["location"])
    notes = read_optional_cell(cells, index_map["notes"])
    bout_type = infer_record_bout_type(notes)
    red_name, blue_name, outcome, red_result, blue_result = orient_record_fight(fighter, opponent, result)
    return {
        "red_fighter_name": red_name,
        "blue_fighter_name": blue_name,
        "event_date": iso_date(parsed_date),
        "red_fighter_result": red_result,
        "blue_fighter_result": blue_result,
        "fight_outcome": outcome,
        "method": method,
        "round": round_value,
        "time": time_value,
        "bout_type": bout_type,
        "event_name": event_name,
        "event_location": location,
        "source_url": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(source_title.replace(' ', '_'))}",
        "source_title": source_title,
    }


def normalize_record_result(value: str) -> str:
    normalized = clean_text(value).lower().rstrip(".")
    if normalized in {"win", "loss", "draw"}:
        return normalized
    if normalized in {"nc", "no contest"}:
        return "no_contest"
    return ""


def orient_record_fight(fighter: str, opponent: str, result: str) -> tuple[str, str, str, str, str]:
    if result == "win":
        return fighter, opponent, "red_win", "W", "L"
    if result == "loss":
        return opponent, fighter, "red_win", "W", "L"
    ordered = sorted([fighter, opponent], key=lambda value: value.lower())
    if result == "draw":
        return ordered[0], ordered[1], "draw", "D", "D"
    return ordered[0], ordered[1], "no_contest", "NC", "NC"


def infer_record_bout_type(notes: str) -> str:
    note = clean_text(notes)
    if not note:
        return "Unknown Bout"
    lowered = note.lower()
    match = re.search(
        r"(women's atomweight|women's strawweight|women's flyweight|women's bantamweight|women's featherweight|"
        r"atomweight|strawweight|flyweight|bantamweight|featherweight|lightweight|welterweight|middleweight|light heavyweight|heavyweight|"
        r"catchweight|catch weight|openweight|open weight)",
        lowered,
    )
    if match:
        label = match.group(1).replace("openweight", "open weight").replace("catchweight", "catch weight")
        label = " ".join(part.capitalize() for part in label.split())
        return f"{label} Bout"
    pounds = re.search(r"(\d{2,3})\s*(?:lb|lbs|pound)", lowered)
    if pounds:
        return f"{pounds.group(1)} lb Bout"
    return "Unknown Bout"


def read_optional_cell(cells: list[dict[str, Any]], index: int | None) -> str:
    if index is None or len(cells) <= index:
        return ""
    return clean_text(cells[index]["text"])


def find_header_index(headers: list[str], names: set[str]) -> int | None:
    for index, header in enumerate(headers):
        if header in names:
            return index
    return None
