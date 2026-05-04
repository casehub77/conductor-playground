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
    write_static_pages(docs_dir, site_config, asset_version)


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
    for path in [docs_dir / "about", docs_dir / "methodology", docs_dir / "privacy", docs_dir / "articles"]:
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
    <p class="footer-links">
      <a href="{nav_href(page, 'about')}">About</a> ★
      <a href="{nav_href(page, 'methodology')}">Methodology</a> ★
      <a href="{nav_href(page, 'privacy')}">Privacy</a> ★
      <a href="{nav_href(page, 'articles')}">Articles</a>
    </p>
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
    elif page in {"fighters", "champions", "rankings", "about", "methodology", "privacy", "articles", "article"}:
        base = ".."
    else:
        base = "."
    paths = {
        "home": f"{base}/index.html",
        "fighters": f"{base}/fighters/index.html",
        "rankings": f"{base}/rankings/index.html",
        "champions": f"{base}/champions/index.html",
        "about": f"{base}/about/index.html",
        "methodology": f"{base}/methodology/index.html",
        "privacy": f"{base}/privacy/index.html",
        "articles": f"{base}/articles/index.html",
    }
    return paths[target]


def active_class(page: str, target: str) -> str:
    if page == target:
        return " active"
    if page == "fighter" and target == "fighters":
        return " active"
    return ""


def write_static_pages(docs_dir: Path, site_config: dict[str, Any], asset_version: str) -> None:
    about_dir = docs_dir / "about"
    methodology_dir = docs_dir / "methodology"
    privacy_dir = docs_dir / "privacy"
    articles_dir = docs_dir / "articles"
    about_dir.mkdir(exist_ok=True)
    methodology_dir.mkdir(exist_ok=True)
    privacy_dir.mkdir(exist_ok=True)
    articles_dir.mkdir(exist_ok=True)

    about_html = content_shell(
        title="About | Track Fights",
        description="What Track Fights is, who runs it, and why the project exists.",
        page="about",
        asset_prefix="../assets",
        asset_version=asset_version,
        site_config=site_config,
        heading="About Track Fights",
        body="""
<p>Track Fights is an independent MMA rankings publication built around a transparent Elo model. The site is fan made and is not affiliated with UFC, PFL, ONE, Bellator, KSW, or any promotion.</p>
<p>The goal is simple: track form and opponent strength across a fighter's career using one consistent rating framework. Traditional standings are often tied to title history, judging controversy, promotional timing, and matchmaking context. Elo gives a second lens that updates after every recorded bout.</p>
<p>The project is run by an MMA fan with engineering support. It exists to answer practical questions: who is rising, who is declining, which wins carried the most rating value, and how divisions compare when records alone are misleading.</p>
<p>Track Fights publishes ranking data, fighter profiles, and methodology notes so readers can evaluate assumptions directly. If the model is wrong in a case, the inputs and correction process are visible and fixable.</p>
""",
    )
    (about_dir / "index.html").write_text(about_html, encoding="utf-8")

    methodology_html = content_shell(
        title="Methodology | Track Fights",
        description="How Track Fights Elo is calculated and maintained.",
        page="methodology",
        asset_prefix="../assets",
        asset_version=asset_version,
        site_config=site_config,
        heading="Track Fights Methodology",
        body="""
<p>Track Fights uses a chess-style Elo rating system adapted for MMA. Every recorded fight updates both fighters based on expected outcome versus actual outcome. Beating a higher-rated opponent adds more points than beating a lower-rated opponent.</p>
<h2>Data Sources</h2>
<p>Primary records come from public MMA fight-result datasets and official event pages. When source coverage lags, controlled fallback ingestion is used, then conflicts are validated before publish.</p>
<h2>Fight Processing</h2>
<p>Each fight is normalized into a common schema: event date, red corner, blue corner, outcome, method, and weight class. Duplicate fight IDs are rejected. Source conflicts are flagged into a report rather than silently merged.</p>
<h2>Manual Corrections</h2>
<p>Manual CSV overrides are used for known edge cases: aliases, excluded bouts, and championship lineage fixes. Every override is explicit and version controlled so changes are auditable.</p>
<h2>Why Rankings Differ From Official Promotion Rankings</h2>
<p>Promotion rankings and Elo rankings answer different questions. Promotion rankings are editorial and title-cycle driven. Track Fights Elo is formula driven, updates after each result, and can reward difficult non-title wins even when they do not move an official ranking slot.</p>
<h2>Inactivity and Context</h2>
<p>The model marks fighters active or inactive using a defined threshold window and applies configured decay for long inactivity periods. Divisional transitions are context-aware so historical performance is not treated as a full reset.</p>
""",
    )
    (methodology_dir / "index.html").write_text(methodology_html, encoding="utf-8")

    privacy_html = content_shell(
        title="Privacy Policy | Track Fights",
        description="Track Fights privacy policy and advertising disclosures.",
        page="privacy",
        asset_prefix="../assets",
        asset_version=asset_version,
        site_config=site_config,
        heading="Privacy Policy",
        body="""
<p>Track Fights uses third-party advertising services, including Google AdSense, to support hosting and operations. This page explains what data may be collected when you visit.</p>
<h2>Advertising Cookies</h2>
<p>Google and other third-party vendors may use cookies to serve ads based on prior visits to this site or other websites. Google may use advertising cookies to enable it and its partners to serve personalized ads.</p>
<h2>Personalized Ads and Opt-Out</h2>
<p>Users can opt out of personalized advertising by visiting Google Ads Settings. Users can also visit www.aboutads.info to opt out of some third-party vendor uses of cookies for personalized advertising.</p>
<h2>Analytics and Logs</h2>
<p>Hosting and CDN providers may collect technical request logs such as IP address, browser type, and request timestamps for security, performance, and abuse prevention.</p>
<h2>Third-Party Vendors</h2>
<p>Third-party ad vendors may serve ads on this site. Those vendors may use cookies or similar technologies to measure ad performance and provide relevant ad experiences.</p>
<h2>Contact</h2>
<p>If you have privacy questions, contact the site operator through the published project channels.</p>
""",
    )
    (privacy_dir / "index.html").write_text(privacy_html, encoding="utf-8")

    article_index = content_shell(
        title="Articles | Track Fights",
        description="Original analysis and explainers from Track Fights.",
        page="articles",
        asset_prefix="../assets",
        asset_version=asset_version,
        site_config=site_config,
        heading="Track Fights Articles",
        body="""
<ul class="content-links">
  <li><a href="./how-track-fights-elo-works/index.html">How Track Fights Elo Works</a></li>
  <li><a href="./best-featherweights-by-elo/index.html">Best Featherweights by Elo</a></li>
  <li><a href="./biggest-elo-risers-this-year/index.html">Biggest Elo Risers This Year</a></li>
  <li><a href="./why-our-rankings-are-different/index.html">Why Our MMA Rankings Are Different</a></li>
</ul>
""",
    )
    (articles_dir / "index.html").write_text(article_index, encoding="utf-8")

    write_article(
        articles_dir / "how-track-fights-elo-works",
        "How Track Fights Elo Works",
        "A practical explainer of the Track Fights Elo model.",
        site_config,
        asset_version,
        """
<p>Track Fights Elo starts from the same principle used in competitive games: each fighter has a rating, and each fight updates that rating based on expected vs actual outcome. If Fighter A is heavily favored by rating and wins, rating movement is modest. If Fighter A is a clear underdog and wins, movement is larger.</p>
<p>This model is useful in MMA because records alone hide schedule quality. A 10-2 run against lower opposition is different from a 5-3 run against elite opponents. Elo captures that difference automatically after every event.</p>
<p>The implementation keeps separate divisional and overall views, tracks peak values, and logs fight-by-fight deltas so movement is explainable. For readers, the benefit is consistency: one formula, updated the same way across every fighter profile and rankings table.</p>
""",
    )
    write_article(
        articles_dir / "best-featherweights-by-elo",
        "Best Featherweights by Elo",
        "How to interpret featherweight strength using Elo context.",
        site_config,
        asset_version,
        """
<p>Featherweight Elo highlights two things at once: who has built a high peak and who has maintained level over time. A single title upset can spike a rating, but sustained top-15 opposition is what keeps a fighter near the top.</p>
<p>When reading featherweight rankings, focus on recent fight count, opponent Elo, and whether rating gains came in one burst or in steady increments. The strongest profiles usually combine both a high absolute rating and repeated wins against similarly rated opponents.</p>
<p>That is where Elo adds value over simple win streaks. It distinguishes momentum from durable performance.</p>
""",
    )
    write_article(
        articles_dir / "biggest-elo-risers-this-year",
        "Biggest Elo Risers This Year",
        "Which fighters gained the most rating and why.",
        site_config,
        asset_version,
        """
<p>Rapid Elo growth usually comes from three patterns: defeating a highly rated favorite, stacking wins in short intervals, or changing divisions and beating ranked opposition immediately. The model reacts quickly to those outcomes because expected probability is low.</p>
<p>A key check is sustainability. Some jumps normalize after the next two or three fights if competition rises. Others hold and become a new baseline. Track Fights keeps this visible in the fight-by-fight chart so readers can separate temporary spikes from durable progression.</p>
<p>The yearly risers list should be read as form plus schedule quality, not only as raw win count.</p>
""",
    )
    write_article(
        articles_dir / "why-our-rankings-are-different",
        "Why Our MMA Rankings Are Different",
        "Why model-driven Elo often disagrees with promotion rankings.",
        site_config,
        asset_version,
        """
<p>Promotion rankings and Elo rankings are built for different jobs. Promotion rankings support title matchmaking and editorial narratives. Elo rankings estimate competitive strength from outcomes and opponent quality in a formulaic way.</p>
<p>Because of that, disagreements are expected. A fighter can be low in an official ranking but high in Elo if their losses are close and against elite opposition. The reverse can also happen when a strong record was built against weaker schedules.</p>
<p>Track Fights is not trying to replace official rankings. It gives a transparent, repeatable second opinion.</p>
""",
    )


def content_shell(
    title: str,
    description: str,
    page: str,
    asset_prefix: str,
    asset_version: str,
    site_config: dict[str, Any],
    heading: str,
    body: str,
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
<body data-page="{page}" data-asset-prefix="{asset_prefix}" data-fighter-slug="" data-asset-version="{asset_version}">
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
      <span class="marquee-inner">★ INDEPENDENT MMA RATINGS ★ CHESS-STYLE RANKINGS FROM FIGHT HISTORY ★ FULL HISTORY BUILD ★ TRACK FIGHTS IS FAN-MADE ★</span>
    </div>
  </header>
  <main class="app">
    <section class="content-page">
      <h1>{escape_html(heading)}</h1>
      {body}
    </section>
  </main>
  <footer class="site-footer">
    {render_static_ad_slot("footer", site_config or {})}
    <p>INDEPENDENT RATINGS ★ DATA PIPELINE USES PUBLIC FIGHT RESULT SOURCES AND MANUAL FALLBACKS</p>
    <p class="footer-links">
      <a href="{nav_href(page, 'about')}">About</a> ★
      <a href="{nav_href(page, 'methodology')}">Methodology</a> ★
      <a href="{nav_href(page, 'privacy')}">Privacy</a> ★
      <a href="{nav_href(page, 'articles')}">Articles</a>
    </p>
    <p class="best-viewed">BEST VIEWED IN 1024x768</p>
  </footer>
</body>
</html>
"""


def write_article(path: Path, title: str, description: str, site_config: dict[str, Any], asset_version: str, body: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "index.html").write_text(
        content_shell(
            title=f"{title} | Track Fights",
            description=description,
            page="article",
            asset_prefix="../../assets",
            asset_version=asset_version,
            site_config=site_config,
            heading=title,
            body=body,
        ),
        encoding="utf-8",
    )


def escape_html(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
