from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .util import write_json


def build_site_payload(output: dict[str, Any], docs_dir: Path, site_config: dict[str, Any]) -> None:
    assets_dir = docs_dir / "assets"
    fighter_assets = assets_dir / "fighters"
    ranking_assets = assets_dir / "rankings"
    peak_assets = assets_dir / "peaks"
    fighter_pages = docs_dir / "fighters"
    fighter_assets.mkdir(parents=True, exist_ok=True)
    ranking_assets.mkdir(parents=True, exist_ok=True)
    peak_assets.mkdir(parents=True, exist_ok=True)
    fighter_pages.mkdir(parents=True, exist_ok=True)
    asset_version = datetime.now(UTC).strftime("%Y%m%d%H%M%S")

    fighters = output["fighters"]
    profiles_by_slug = {fighter["slug"]: fighter for fighter in fighters}
    home = {
        "site": site_config,
        "as_of": output["as_of"],
        "fight_count": output["fight_count"],
        "fighter_count": len(fighters),
        "champions": output["champions"],
        "highest_ever": output["highest_ever"],
        "recent_movers": output["recent_movers"],
        "previous_champions": output["previous_champions"][:80],
    }
    fighter_index = [
        {
            "name": fighter["name"],
            "slug": fighter["slug"],
            "nickname": fighter["nickname"],
            "gender": fighter["gender"],
            "weight_class": fighter["weight_class"],
            "current_elo": fighter["current_elo"],
            "peak_elo": fighter["peak_elo"],
            "divisional_rank": fighter["divisional_rank"],
            "instagram": fighter["instagram"],
        }
        for fighter in fighters
    ]
    rankings_index = {"systems": output["systems"], "as_of": output["as_of"]}
    highest_ever_by_system = output.get("highest_ever_by_system", {})
    instagram_featured = instagram_featured_names(output)
    write_json(assets_dir / "home.json", home)
    write_json(assets_dir / "fighter-index.json", fighter_index)
    write_json(assets_dir / "rankings-index.json", rankings_index)
    for system in output["systems"]:
        write_json(ranking_assets / f"{system_key(system)}.json", {"system": system, "rows": output["rankings"].get(system, [])})
        write_json(peak_assets / f"{system_key(system)}.json", {"system": system, "rows": highest_ever_by_system.get(system, [])})
    write_json(
        assets_dir / "previous-champions.json",
        {
            "previous_champions": output["previous_champions"],
            "title_lineage": output.get("title_lineage", {}),
            "systems": output["systems"],
            "as_of": output["as_of"],
        },
    )
    write_json(
        assets_dir / "all-time-peaks.json",
        {
            "by_system": output.get("highest_ever_by_system", {}),
            "overall": output["highest_ever"],
            "systems": output["systems"],
            "as_of": output["as_of"],
        },
    )

    for slug, fighter in profiles_by_slug.items():
        fighter_payload = dict(fighter)
        fighter_payload["instagram_featured"] = fighter["name"] in instagram_featured
        write_json(fighter_assets / f"{slug}.json", fighter_payload)
        page_dir = fighter_pages / slug
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "index.html").write_text(
            html_shell(
                title=f"{fighter['name']} | Track Fights",
                description=f"{fighter['name']} MMA rating history, fight log, opponent strength, and divisional rank.",
                page="fighter",
                asset_prefix="../../assets",
                fighter_slug=slug,
                asset_version=asset_version,
                site_config=site_config,
            ),
            encoding="utf-8",
        )

    (docs_dir / "index.html").write_text(
        html_shell(
            title=site_config.get("title", "Track Fights"),
            description=site_config.get("description", "Independent MMA fighter ratings and fight history tracking from full-history capable fight data."),
            page="home",
            asset_prefix="assets",
            asset_version=asset_version,
            site_config=site_config,
        ),
        encoding="utf-8",
    )
    (fighter_pages / "index.html").write_text(
        html_shell(
            title="All Fighters | Track Fights",
            description="Search every fighter in the Track Fights MMA ratings database.",
            page="fighters",
            asset_prefix="../assets",
            asset_version=asset_version,
            site_config=site_config,
        ),
        encoding="utf-8",
    )
    champions_dir = docs_dir / "champions"
    champions_dir.mkdir(exist_ok=True)
    (champions_dir / "index.html").write_text(
        html_shell(
            title="Previous Champions | Track Fights",
            description="Title fight winners and previous champions with current MMA rating context.",
            page="champions",
            asset_prefix="../assets",
            asset_version=asset_version,
            site_config=site_config,
        ),
        encoding="utf-8",
    )
    rankings_dir = docs_dir / "rankings"
    rankings_dir.mkdir(exist_ok=True)
    (rankings_dir / "index.html").write_text(
        html_shell(
            title="Rankings | Track Fights",
            description="Current MMA rankings by gender and weight class.",
            page="rankings",
            asset_prefix="../assets",
            asset_version=asset_version,
            site_config=site_config,
        ),
        encoding="utf-8",
        )


def instagram_featured_names(output: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for system, rows in output.get("rankings", {}).items():
        if system.endswith(":overall"):
            continue
        for row in rows[:10]:
            if row.get("name"):
                names.add(row["name"])
    for champion in output.get("champions", []):
        if champion.get("fighter_name"):
            names.add(champion["fighter_name"])
    return names


def clean_generated_site(docs_dir: Path) -> None:
    for path in [docs_dir / "fighters", docs_dir / "champions", docs_dir / "rankings"]:
        if path.exists():
            shutil.rmtree(path)
    for path in [docs_dir / "assets" / "fighters", docs_dir / "assets" / "rankings", docs_dir / "assets" / "peaks"]:
        if path.exists():
            shutil.rmtree(path)
    for name in ["home.json", "fighter-index.json", "rankings-index.json", "rankings.json", "previous-champions.json", "all-time-peaks.json"]:
        path = docs_dir / "assets" / name
        if path.exists():
            path.unlink()


def system_key(system: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(system or "").strip().lower())
    return normalized.strip("-") or "unknown"


def html_shell(
    title: str,
    description: str,
    page: str,
    asset_prefix: str,
    fighter_slug: str = "",
    asset_version: str = "",
    site_config: dict[str, Any] | None = None,
) -> str:
    site_payload = json.dumps(site_config or {}, ensure_ascii=False).replace("</", "<\\/")
    ad_network = (site_config or {}).get("ad_network", {})
    ad_script = render_ad_network_script(ad_network)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape_html(title)}</title>
  <meta name="description" content="{escape_html(description)}">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=VT323&family=Oswald:wght@400;600;700&family=Bebas+Neue&family=Courier+Prime:wght@400;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{asset_prefix}/styles.css?v={asset_version}">
  {ad_script}
</head>
<body data-page="{page}" data-asset-prefix="{asset_prefix}" data-fighter-slug="{fighter_slug}" data-asset-version="{asset_version}">
  <script id="site-config" type="application/json">{site_payload}</script>
  <header class="site-header">
    <div class="header-inner">
    <a class="site-logo" href="{nav_href(page, 'home')}">
      <span class="logo-badge">TRACK</span>
      <span class="logo-text">FIGHTS</span>
      <span class="live-dot">● LIVE</span>
    </a>
    <nav class="site-nav">
      <a class="nav-btn{active_class(page, 'home')}" href="{nav_href(page, 'home')}">Home</a>
      <a class="nav-btn{active_class(page, 'fighters')}" href="{nav_href(page, 'fighters')}">Fighters</a>
      <a class="nav-btn{active_class(page, 'rankings')}" href="{nav_href(page, 'rankings')}">Rankings</a>
      <a class="nav-btn{active_class(page, 'champions')}" href="{nav_href(page, 'champions')}">Champions</a>
    </nav>
    </div>
    <div class="marquee-wrap">
      <span class="marquee-inner">★ INDEPENDENT MMA RATINGS ★ CHESS-STYLE RANKINGS FROM FIGHT HISTORY ★ FULL HISTORY BUILD ★ TRACK FIGHTS IS FAN-MADE ★ FIGHT NIGHT RESULTS UPDATED BY PIPELINE ★</span>
    </div>
  </header>
  <main id="app" class="app" aria-live="polite">
    <section class="loading">Loading fight tape...</section>
  </main>
  <footer class="site-footer">
    {render_static_ad_slot("footer", site_config or {})}
    <p>INDEPENDENT RATINGS ★ DATA PIPELINE USES PUBLIC FIGHT RESULT SOURCES AND MANUAL FALLBACKS</p>
    <p class="best-viewed">BEST VIEWED IN 1024x768</p>
  </footer>
  <script src="{asset_prefix}/app.js?v={asset_version}" defer></script>
</body>
</html>
"""


def render_ad_network_script(ad_network: dict[str, Any]) -> str:
    if not ad_network.get("enabled") or not ad_network.get("script_url"):
        return ""
    script_url = str(ad_network["script_url"])
    if ad_network.get("provider") == "adsense" and ad_network.get("client"):
        joiner = "&" if "?" in script_url else "?"
        script_url = f"{script_url}{joiner}client={escape_html(str(ad_network['client']))}"
        crossorigin = ' crossorigin="anonymous"'
    else:
        crossorigin = ""
    return f'<script async src="{escape_html(script_url)}"{crossorigin}></script>'


def render_static_ad_slot(name: str, site_config: dict[str, Any]) -> str:
    slot = (site_config.get("ad_slots", {}) or {}).get(name, {})
    ad_network = site_config.get("ad_network", {}) or {}
    label = slot.get("label", name.replace("_", " "))
    width = int(slot.get("width") or 970)
    height = int(slot.get("height") or 90)
    provider = str(ad_network.get("provider") or "").lower()
    adsense_ready = bool(ad_network.get("enabled") and provider == "adsense" and ad_network.get("client") and slot.get("slot_id"))
    if adsense_ready:
        inner = (
            f'<ins class="adsbygoogle ad-slot-unit" style="display:block" '
            f'data-ad-client="{escape_html(str(ad_network["client"]))}" '
            f'data-ad-slot="{escape_html(str(slot["slot_id"]))}" '
            f'data-ad-format="{escape_html(str(slot.get("format", "auto")))}" '
            f'data-full-width-responsive="{"false" if slot.get("responsive") is False else "true"}"></ins>'
        )
    else:
        inner = (
            f'<div class="ad-slot-placeholder"><strong>Advertisement</strong>'
            f'<span>{escape_html(str(label))}</span><span>{width} x {height}</span></div>'
        )
    return (
        f'<div class="ad-slot ad-slot-{escape_html(name)}" data-ad-slot="{escape_html(name)}" '
        f'style="--slot-width:{width}px;--slot-height:{height}px">'
        f'<div class="ad-slot-meta"><span>Advertisement</span><span>{escape_html(str(label))}</span></div>'
        f'<div class="ad-slot-frame">{inner}</div></div>'
    )


def nav_href(page: str, target: str) -> str:
    if page == "fighter":
        base = "../.."
    elif page in {"fighters", "champions", "rankings"}:
        base = ".."
    else:
        base = "."
    paths = {
        "home": f"{base}/index.html",
        "fighters": f"{base}/fighters/index.html",
        "rankings": f"{base}/rankings/index.html",
        "champions": f"{base}/champions/index.html",
    }
    return paths[target]


def active_class(page: str, target: str) -> str:
    if page == target:
        return " active"
    if page == "fighter" and target == "fighters":
        return " active"
    return ""


def escape_html(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
