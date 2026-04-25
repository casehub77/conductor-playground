const body = document.body;
const page = body.dataset.page;
const assetPrefix = body.dataset.assetPrefix;
const assetVersion = body.dataset.assetVersion || "";
const app = document.querySelector("#app");
const siteConfigEl = document.querySelector("#site-config");
const siteConfig = siteConfigEl ? JSON.parse(siteConfigEl.textContent) : {};
const jsonCache = new Map();

async function loadJson(path) {
  if (jsonCache.has(path)) return jsonCache.get(path);
  const versionSuffix = assetVersion ? `?v=${encodeURIComponent(assetVersion)}` : "";
  const response = await fetch(`${assetPrefix}/${path}${versionSuffix}`, { cache: "force-cache" });
  if (!response.ok) throw new Error(`Unable to load ${path}`);
  const payload = await response.json();
  jsonCache.set(path, payload);
  return payload;
}

function debounce(fn, delayMs) {
  let timer = null;
  return (...args) => {
    if (timer) window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), delayMs);
  };
}

function fmt(value) {
  if (value === null || value === undefined || value === "") return "-";
  return Number.isFinite(value) ? value.toLocaleString() : value;
}

function fighterHref(slug) {
  if (page === "home") return `fighters/${slug}/index.html`;
  if (page === "fighters") return `${slug}/index.html`;
  if (page === "fighter") return `../${slug}/index.html`;
  return `../fighters/${slug}/index.html`;
}

function slugify(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "unknown";
}

function systemKey(value) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "unknown";
}

function fighterLink(name, slug = "") {
  if (!name) return `<span class="muted">VACANT / NO CONTEST</span>`;
  const safeSlug = slug || slugify(name);
  return `<a href="${fighterHref(safeSlug)}">${escapeHtml(name)}</a>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function displayEventName(value) {
  return String(value || "")
    .replace(/^UFC\s+Fight\s+Night\b/i, "Fight Night")
    .replace(/^UFC\s+on\s+(ESPN|ABC|FOX|FX|FUEL TV)\b/i, "Fight Night")
    .replace(/^UFC\s+Live\b/i, "Fight Night")
    .replace(/^UFC\s+(\d+(?:\.\d+)?)/i, "Event $1")
    .replace(/^UFC\b:?\s*/i, "Fight Card");
}

function instagramHandle(url) {
  const match = String(url || "").match(/instagram\.com\/([^/?#]+)/i);
  return match ? match[1].replace(/^@/, "") : "";
}

function stat(label, value) {
  return `<div class="stat"><span>${label}</span><strong>${fmt(value)}</strong></div>`;
}

function sectionHeader(title, badge = "") {
  return `<div class="section-header">
    <div class="section-title">${escapeHtml(title)}</div>
    ${badge ? `<span class="section-badge">${escapeHtml(badge)}</span>` : ""}
  </div>`;
}

function adSlot(name) {
  const slot = ((siteConfig.ad_slots || {})[name]) || {};
  const label = slot.label || name.replace(/_/g, " ");
  const width = Number(slot.width) || 970;
  const height = Number(slot.height) || 90;
  const provider = String((siteConfig.ad_network || {}).provider || "").toLowerCase();
  const enabled = Boolean(siteConfig.ad_network && siteConfig.ad_network.enabled);
  const adsenseClient = siteConfig.ad_network && siteConfig.ad_network.client;
  const adsenseEligible = enabled && provider === "adsense" && adsenseClient && slot.slot_id;
  const adMarkup = adsenseEligible
    ? `<ins class="adsbygoogle ad-slot-unit"
        style="display:block"
        data-ad-client="${escapeHtml(adsenseClient)}"
        data-ad-slot="${escapeHtml(slot.slot_id)}"
        data-ad-format="${escapeHtml(slot.format || "auto")}"
        data-full-width-responsive="${slot.responsive === false ? "false" : "true"}"></ins>`
    : `<div class="ad-slot-placeholder">
        <strong>Advertisement</strong>
        <span>${escapeHtml(label)}</span>
        <span>${width} x ${height}</span>
      </div>`;
  return `<div class="ad-slot ad-slot-${escapeHtml(name)}" data-ad-slot="${escapeHtml(name)}" data-ad-format="${escapeHtml(slot.format || "")}" style="--slot-width:${width}px;--slot-height:${height}px">
    <div class="ad-slot-meta">
      <span>Advertisement</span>
      <span>${escapeHtml(label)}</span>
    </div>
    <div class="ad-slot-frame">
      ${adMarkup}
    </div>
  </div>`;
}

function initializeAds() {
  const provider = String((siteConfig.ad_network || {}).provider || "").toLowerCase();
  if (provider !== "adsense" || !siteConfig.ad_network || !siteConfig.ad_network.enabled || !window.adsbygoogle) {
    return;
  }
  document.querySelectorAll("ins.adsbygoogle").forEach((node) => {
    if (node.dataset.adsReady === "true") return;
    try {
      (window.adsbygoogle = window.adsbygoogle || []).push({});
      node.dataset.adsReady = "true";
    } catch (error) {
      console.error("Ad slot initialization failed", error);
    }
  });
}

function renderTable(headers, rows) {
  return `<div class="table-wrap"><table class="data-table"><thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
}

function row(cells) {
  return `<tr>${cells.map((cell) => `<td>${cell}</td>`).join("")}</tr>`;
}

function prepareFighterSearch(fighters) {
  return [...fighters]
    .map((fighter) => ({
      ...fighter,
      _search: `${fighter.name} ${fighter.nickname || ""} ${fighter.weight_class}`.toLowerCase(),
    }))
    .sort((a, b) => b.current_elo - a.current_elo);
}

function mountSearch(target, fighters) {
  const input = target.querySelector("[data-search]");
  const results = target.querySelector("[data-results]");
  if (!input || !results) return;
  const ordered = prepareFighterSearch(fighters);
  const render = () => {
    const query = input.value.trim().toLowerCase();
    const filtered = ordered.filter((fighter) => !query || fighter._search.includes(query)).slice(0, query ? 30 : 12);
    results.innerHTML = filtered
      .map(
        (fighter) => `<a class="fighter-result" href="${fighterHref(fighter.slug)}">
          <span class="rank-mini">#${escapeHtml(fighter.divisional_rank || "-")}</span>
          <strong>${escapeHtml(fighter.name)}</strong>
          <span>${escapeHtml(fighter.gender)} ${escapeHtml(fighter.weight_class)}</span>
          <span class="fighter-elo-label">ELO RATING</span>
          <span class="elo-mini">${fmt(fighter.current_elo)}</span>
        </a>`
      )
      .join("");
    if (!filtered.length) {
      results.innerHTML = `<div class="loading">&gt; NO FIGHTER FOUND</div>`;
    }
  };
  input.addEventListener("input", debounce(render, 80));
  render();
}

async function renderHome() {
  const home = await loadJson("home.json");
  app.innerHTML = `
    <section class="hero-band">
      <div class="hero-copy">
        <p class="eyebrow">Independent ratings from fight history</p>
        <h1>TRACK FIGHTS</h1>
        <p class="dek">MMA fighter ratings and fight history tracking, built from public fight result data with fallback imports and manual correction files.</p>
      </div>
      <div class="hero-stats">
        ${stat("Fighters", home.fighter_count)}
        ${stat("Fights", home.fight_count)}
        ${stat("Updated", home.as_of)}
      </div>
    </section>
    ${adSlot("home_top")}
    <section class="band search-band">
      ${sectionHeader("Find a Fighter")}
      <div class="search-wrap">
        <input class="search" data-search placeholder="Search any fighter">
      </div>
      <div class="result-grid" data-results><div class="loading">&gt; TYPE TO LOAD FIGHTER SEARCH</div></div>
    </section>
    <div class="divider"></div>
    <section class="band">
      ${sectionHeader("The Rankings")}
      <div class="tabs" role="tablist">
        <button class="tab active" data-tab="champions">Champions</button>
        <button class="tab" data-tab="highest">Highest ever</button>
        <button class="tab" data-tab="movers">Recent movers</button>
        <button class="tab" data-tab="previous">Previous champions</button>
      </div>
      <div data-tab-panel></div>
    </section>`;
  mountDeferredSearch(app);
  const panel = app.querySelector("[data-tab-panel]");
  const renderTab = (name) => {
    if (name === "champions") panel.innerHTML = championTable(home.champions);
    if (name === "highest") panel.innerHTML = highestTable(home.highest_ever);
    if (name === "movers") panel.innerHTML = moversTable(home.recent_movers);
    if (name === "previous") panel.innerHTML = previousTable(home.previous_champions.slice(0, 40));
  };
  app.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      app.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      renderTab(button.dataset.tab);
    });
  });
  renderTab("champions");
}

function mountDeferredSearch(target) {
  const input = target.querySelector("[data-search]");
  const results = target.querySelector("[data-results]");
  if (!input || !results) return;
  let fighters = null;
  let pending = null;

  const loadFighters = async () => {
    if (fighters) return fighters;
    if (!pending) {
      results.innerHTML = `<div class="loading">&gt; LOADING FIGHTER INDEX...</div>`;
      pending = loadJson("fighter-index.json")
        .then((rows) => {
          fighters = rows;
          return rows;
        })
        .finally(() => {
          pending = null;
        });
    }
    return pending;
  };

  const render = debounce(async () => {
    if (!fighters) {
      await loadFighters();
      mountSearch(target, fighters || []);
      const inputEvent = new Event("input");
      input.dispatchEvent(inputEvent);
    }
  }, 60);

  input.addEventListener("focus", () => {
    if (!fighters) loadFighters();
  }, { once: true });
  input.addEventListener("input", render);
}

function championTable(champions) {
  return renderTable(
    ["Division", "Champion", "Elo", "Rank", "Won/Retained"],
    champions.map((item) =>
      row([
        `${escapeHtml(item.gender)} ${escapeHtml(item.weight_class)}`,
        fighterLink(item.fighter_name, item.slug),
        fmt(item.current_elo),
        fmt(item.rank),
        `${escapeHtml(item.date)}<br><span class="muted">${escapeHtml(displayEventName(item.event_name))}</span>`,
      ])
    )
  );
}

function highestTable(rows) {
  return renderTable(
    ["#", "Fighter", "Peak Elo", "Current", "Division"],
    rows.map((item, index) => row([index + 1, fighterLink(item.name, item.slug), fmt(item.peak_elo), fmt(item.current_elo), `${escapeHtml(item.gender)} ${escapeHtml(item.weight_class)}`]))
  );
}

function moversTable(rows) {
  return renderTable(
    ["Fighter", "Change", "Fights", "Current", "Division"],
    rows.map((item) => row([fighterLink(item.name, item.slug), signed(item.change), fmt(item.fights), fmt(item.current_elo), `${escapeHtml(item.gender)} ${escapeHtml(item.weight_class)}`]))
  );
}

function previousTable(rows) {
  return renderTable(
    ["Date", "Division", "Champion", "Event", "Method"],
    rows.map((item) => row([escapeHtml(item.date), `${escapeHtml(item.gender)} ${escapeHtml(item.weight_class)}`, fighterLink(item.fighter_name, item.slug), escapeHtml(displayEventName(item.event_name)), escapeHtml(item.method)]))
  );
}

function signed(value) {
  const number = Number(value || 0);
  const sign = number > 0 ? "+" : "";
  return `<span class="${number >= 0 ? "up" : "down"}">${sign}${number.toFixed(1)}</span>`;
}

async function renderFighters() {
  const fighters = await loadJson("fighter-index.json");
  app.innerHTML = `
    ${adSlot("fighters_top")}
    <section class="band">
      ${sectionHeader("All Fighters")}
      <div class="search-wrap">
        <input class="search" data-search placeholder="Search by name or division">
      </div>
      <div class="result-grid wide" data-results></div>
    </section>`;
  mountSearch(app, fighters);
}

async function renderRankings() {
  const data = await loadJson("rankings-index.json");
  const systems = data.systems.filter((system) => !system.endsWith(":overall"));
  app.innerHTML = `
    ${adSlot("rankings_top")}
    <section class="band">
      ${sectionHeader("Rankings")}
      <label class="select-label">Division
        <select class="select" data-system>${systems.map((system) => `<option value="${system}">${escapeHtml(system.replace(":", " "))}</option>`).join("")}</select>
      </label>
      <div class="tabs" role="tablist">
        <button class="tab active" data-rank-tab="current">Current</button>
        <button class="tab" data-rank-tab="alltime">All-time peaks</button>
      </div>
      <div data-rank-panel></div>
    </section>`;
  const select = app.querySelector("[data-system]");
  const panel = app.querySelector("[data-rank-panel]");
  let activeTab = "current";
  const currentCache = new Map();
  const peakCache = new Map();
  let drawNonce = 0;
  const draw = async () => {
    const nonce = ++drawNonce;
    panel.innerHTML = `<div class="loading">&gt; LOADING RANKINGS...</div>`;
    const system = select.value;
    const key = systemKey(system);
    if (activeTab === "current") {
      if (!currentCache.has(system)) {
        const payload = await loadJson(`rankings/${key}.json`);
        if (nonce !== drawNonce) return;
        currentCache.set(system, payload.rows || []);
      }
      const rows = currentCache.get(system) || [];
      panel.innerHTML = renderTable(
        ["Rank", "Fighter", "Elo", "Peak", "Fights", "Last fight"],
        rows.slice(0, 100).map((item) => row([fmt(item.rank), fighterLink(item.name, item.slug), fmt(item.rating), fmt(item.peak), fmt(item.fights), fmt(item.last_fight_date)]))
      );
      return;
    }
    if (!peakCache.has(system)) {
      const payload = await loadJson(`peaks/${key}.json`);
      if (nonce !== drawNonce) return;
      peakCache.set(system, payload.rows || []);
    }
    const rows = peakCache.get(system) || [];
    panel.innerHTML = renderTable(
      ["#", "Fighter", "Peak Elo", "Current Elo", "Fights", "Last fight"],
      rows.map((item, index) => row([index + 1, fighterLink(item.name, item.slug), fmt(item.peak_elo), fmt(item.current_elo), fmt(item.fights), fmt(item.last_fight_date)]))
    );
  };
  select.addEventListener("change", draw);
  app.querySelectorAll("[data-rank-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      app.querySelectorAll("[data-rank-tab]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      activeTab = btn.dataset.rankTab;
      draw();
    });
  });
  draw();
}

async function renderChampions() {
  const data = await loadJson("previous-champions.json");
  const lineage = data.title_lineage || {};
  const lineageSystems = Object.keys(lineage).sort();
  app.innerHTML = `
    ${adSlot("champions_top")}
    <section class="band">
      ${sectionHeader("Title History")}
      <p class="muted">Derived from title bouts in the source data. Use <code>overrides/champion_overrides.csv</code> for manual fixes.</p>
      <div class="tabs" role="tablist">
        <button class="tab active" data-champ-tab="list">All title bouts</button>
        <button class="tab" data-champ-tab="lineage">Lineage by division</button>
      </div>
      <div data-champ-panel></div>
    </section>`;
  const panel = app.querySelector("[data-champ-panel]");
  const renderTab = (tab) => {
    if (tab === "list") {
      panel.innerHTML = previousTable(data.previous_champions);
      return;
    }
    panel.innerHTML = `
      <label class="select-label">Division
        <select class="select" data-lineage-system>
          ${lineageSystems.map((system) => `<option value="${escapeHtml(system)}">${escapeHtml(system.replace(":", " "))}</option>`).join("")}
        </select>
      </label>
      <div data-lineage-chain></div>`;
    const select = panel.querySelector("[data-lineage-system]");
    const chain = panel.querySelector("[data-lineage-chain]");
    const draw = () => {
      chain.innerHTML = lineageChain(lineage[select.value] || []);
    };
    select.addEventListener("change", draw);
    draw();
  };
  app.querySelectorAll("[data-champ-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      app.querySelectorAll("[data-champ-tab]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      renderTab(btn.dataset.champTab);
    });
  });
  renderTab("list");
}

function lineageChain(entries) {
  if (!entries.length) return `<p class="muted">No title bouts on record for this division.</p>`;
  const steps = entries.map((entry) => {
    const outcomeLabel = entry.outcome === "no_contest" ? "No contest" : (entry.outcome === "draw" ? "Draw" : "Winner");
    const who = entry.fighter_name ? fighterLink(entry.fighter_name, entry.slug || "") : `<span class="muted">${outcomeLabel}</span>`;
    return `<li class="lineage-step">
      <time>${escapeHtml(entry.date)}</time>
      <div>
        <strong>${who}</strong>
        <div class="muted">${escapeHtml(displayEventName(entry.event_name))}${entry.method ? " | " + escapeHtml(entry.method) : ""}</div>
        <div class="muted">${escapeHtml(entry.red_name)} vs ${escapeHtml(entry.blue_name)} | ${outcomeLabel}</div>
      </div>
    </li>`;
  });
  return `<ol class="lineage">${steps.join("")}</ol>`;
}

async function renderFighter() {
  const slug = body.dataset.fighterSlug;
  const fighter = await loadJson(`fighters/${slug}.json`);
  const divisionChart = buildDivisionSeries(fighter);
  const activeSystem = divisionChart.primary ? divisionChart.primary.system : "";
  app.innerHTML = `
    <section class="fighter-head">
      <div>
        <p class="eyebrow">${escapeHtml(fighter.gender)} ${escapeHtml(fighter.weight_class)}</p>
        ${renderActivityStatus(fighter)}
        <h1>${escapeHtml(fighter.name)}</h1>
        ${fighter.nickname ? `<p class="nickname">"${escapeHtml(fighter.nickname)}"</p>` : ""}
      </div>
      <div class="hero-stats">
        ${stat("Current Elo", fighter.current_elo)}
        ${fighter.inactivity_adjusted ? stat("Last Active Elo", fighter.raw_current_elo) : ""}
        ${stat("Peak Elo", fighter.peak_elo)}
        ${stat("Div. rank", fighter.divisional_rank)}
      </div>
    </section>
    ${adSlot("fighter_top")}
    <section class="band">
      <div class="fighter-meta">
        <span>${fmt(fighter.fight_count)} bouts</span>
        <span>First: ${fmt(fighter.first_fight_date)}</span>
        <span>Last: ${fmt(fighter.last_fight_date)}</span>
        ${renderActivityMeta(fighter)}
        ${fighter.instagram ? `<a href="${fighter.instagram}" rel="nofollow noopener" target="_blank">INSTAGRAM</a>` : "<span>NO VERIFIED INSTAGRAM</span>"}
      </div>
      ${renderInstagramEmbed(fighter)}
      ${sectionHeader("Elo History")}
      ${renderDivisionSelector(divisionChart.series, activeSystem)}
      <div class="chart-wrap" data-chart-wrap></div>
    </section>
    <div class="divider"></div>
    <section class="band">
      ${sectionHeader("Fight-by-Fight Elo")}
      ${renderFightLog(fighter.fight_log)}
    </section>`;
  const chartWrap = app.querySelector("[data-chart-wrap]");
  const drawChart = (system) => {
    const selected = divisionChart.series.find((series) => series.system === system) || divisionChart.primary;
    const overallHistory = fighter.history.filter((point) => point.scope === "overall");
    chartWrap.innerHTML = `${renderDivisionHistoryContext(divisionChart.series, system)}${renderEloChart(selected, overallHistory, fighter)}`;
  };
  app.querySelectorAll("[data-division-system]").forEach((button) => {
    button.addEventListener("click", () => {
      app.querySelectorAll("[data-division-system]").forEach((node) => node.classList.remove("active"));
      button.classList.add("active");
      drawChart(button.dataset.divisionSystem);
    });
  });
  drawChart(activeSystem);
  processInstagramEmbeds();
}

function renderActivityStatus(fighter) {
  const status = fighter.activity_status;
  if (!status || status === "unknown") return "";
  const label = status === "inactive" ? "INACTIVE" : "ACTIVE";
  const klass = status === "inactive" ? "inactive" : "active";
  return `<div class="activity-badge ${klass}">${label}</div>`;
}

function renderActivityMeta(fighter) {
  if (fighter.activity_status === "inactive") {
    return `<span>Inactive after ${fmt(fighter.inactive_after_days)} days</span>`;
  }
  if (fighter.activity_status === "active" && fighter.days_since_last_fight !== null && fighter.days_since_last_fight !== undefined) {
    return `<span>${fmt(fighter.days_since_last_fight)} days since last fight</span>`;
  }
  return "";
}

function renderInstagramEmbed(fighter) {
  if (!fighter.instagram_featured || !fighter.instagram) return "";
  const handle = instagramHandle(fighter.instagram);
  const safeUrl = escapeHtml(fighter.instagram);
  const safeHandle = escapeHtml(handle);
  return `<div class="instagram-panel">
    <div>
      <p class="eyebrow">Featured social</p>
      <h2>Instagram</h2>
    </div>
    <div class="instagram-embed-shell">
      <div class="instagram-profile-card">
        <span class="instagram-mark">IG</span>
        <div>
          <strong>@${safeHandle}</strong>
          <span>${escapeHtml(fighter.name)}</span>
        </div>
        <a href="${safeUrl}" rel="nofollow noopener" target="_blank">OPEN PROFILE</a>
      </div>
      <blockquote class="instagram-media" data-instgrm-permalink="${safeUrl}" data-instgrm-version="14">
        <a href="${safeUrl}" rel="nofollow noopener" target="_blank">@${safeHandle}</a>
      </blockquote>
    </div>
  </div>`;
}

function processInstagramEmbeds() {
  if (!app.querySelector(".instagram-media")) return;
  if (window.instgrm && window.instgrm.Embeds) {
    window.instgrm.Embeds.process();
    return;
  }
  if (document.querySelector("script[data-instagram-embed]")) return;
  const script = document.createElement("script");
  script.src = "https://www.instagram.com/embed.js";
  script.async = true;
  script.dataset.instagramEmbed = "true";
  document.body.appendChild(script);
}

function buildDivisionSeries(fighter) {
  const counts = new Map();
  fighter.history.forEach((point) => {
    if (point.scope !== "division") return;
    counts.set(point.system, (counts.get(point.system) || 0) + 1);
  });
  const primarySystem = fighter.systems && fighter.systems.division;
  const sorted = [...counts.entries()].sort((a, b) => {
    if (a[0] === primarySystem) return -1;
    if (b[0] === primarySystem) return 1;
    return b[1] - a[1];
  });
  const series = sorted.map(([system, count], index) => ({
    system,
    count,
    color: index === 0 ? "division" : "division-alt",
    label: prettyDivisionLabel(system),
    points: fighter.history.filter((p) => p.scope === "division" && p.system === system),
  }));
  return {
    series,
    primary: series[0] || null,
    alternates: series.slice(1),
  };
}

function prettyDivisionLabel(system) {
  const [, weightClass = ""] = String(system || "").split(":");
  return weightClass || system;
}

function renderDivisionSelector(series, activeSystem) {
  if (!series || series.length <= 1) return "";
  return `<div class="division-selector" role="tablist" aria-label="Division history">
    ${series.map((item) => `<button class="division-chip${item.system === activeSystem ? " active" : ""}" data-division-system="${escapeHtml(item.system)}" role="tab">${escapeHtml(item.label)}</button>`).join("")}
  </div>`;
}

function renderDivisionHistoryContext(series, activeSystem) {
  if (!series || !series.length) return "";
  const active = series.find((item) => item.system === activeSystem) || series[0];
  const otherLabels = series.filter((item) => item.system !== (active && active.system)).map((item) => escapeHtml(item.label));
  return `<p class="chart-context">
    Showing divisional Elo for <strong>${escapeHtml(active ? active.label : "Unknown")}</strong>${otherLabels.length ? ` with other division history available: ${otherLabels.join(" / ")}` : ""}.
  </p>`;
}

function renderEloChart(primaryDivisionSeries, overallHistory, fighter) {
  const normalizedDivisions = (primaryDivisionSeries ? [{
    ...primaryDivisionSeries,
    data: normalizeChartSeries(primaryDivisionSeries.points),
  }] : []).filter((series) => series.data.length);
  const overall = normalizeChartSeries(overallHistory);
  const lineSeries = [
    ...normalizedDivisions,
    overall.length ? { system: "overall", color: "overall", label: "Overall Elo", data: overall } : null,
  ].filter(Boolean);
  const allPoints = lineSeries.flatMap((series) => series.data);
  if (!allPoints.length) return `<p class="muted">No chart data yet.</p>`;

  const width = 1000;
  const height = 340;
  const padLeft = 70;
  const padRight = 28;
  const padTop = 28;
  const padBottom = 62;
  const ratings = allPoints.map((point) => point.rating);
  const rawMin = Math.min(...ratings);
  const rawMax = Math.max(...ratings);
  const min = Math.floor((rawMin - 20) / 25) * 25;
  const max = Math.ceil((rawMax + 20) / 25) * 25;
  const span = Math.max(1, max - min);
  const times = allPoints.map((p) => Date.parse(p.date)).filter((t) => Number.isFinite(t));
  const firstTime = times.length ? Math.min(...times) : 0;
  const lastTime = times.length ? Math.max(...times) : firstTime + 1;
  const timeSpan = Math.max(1, lastTime - firstTime);
  const xFor = (dateStr) => {
    const t = Date.parse(dateStr);
    if (!Number.isFinite(t)) return padLeft;
    return padLeft + ((t - firstTime) / timeSpan) * (width - padLeft - padRight);
  };
  const yFor = (rating) => padTop + ((max - rating) / span) * (height - padTop - padBottom);
  const yTicks = makeTicks(min, max, 5);
  const firstDate = new Date(firstTime).toISOString().slice(0, 10);
  const lastDate = new Date(lastTime).toISOString().slice(0, 10);

  const occupiedLabels = [];

  const renderSeries = (series, labelSide) => {
    if (!series.data.length) return "";
    const coords = series.data.map((point) => `${xFor(point.date).toFixed(1)},${yFor(point.rating).toFixed(1)}`);
    const circles = series.data
      .map((point) => `<circle cx="${xFor(point.date).toFixed(1)}" cy="${yFor(point.rating).toFixed(1)}" r="${series.data.length === 1 ? 6 : 4}"><title>${escapeHtml(series.label)} ${escapeHtml(point.date)}: ${fmt(point.rating)}</title></circle>`)
      .join("");
    const labelIndices = pickLabelIndices(series.data, 4);
    const pointLabels = labelIndices
      .map((index) => {
        const point = series.data[index];
        const value = fmt(point.rating);
        const boxWidth = Math.max(50, String(value).length * 8 + 14);
        const boxHeight = 20;
        const pointX = xFor(point.date);
        const pointY = yFor(point.rating);
        const labelX = Math.max(padLeft + boxWidth / 2, Math.min(width - padRight - boxWidth / 2, pointX));
        const candidateOffsets = labelSide === "above" ? [-24, -46, 24, 46] : [24, 46, -24, -46];
        let labelY = null;
        for (const offset of candidateOffsets) {
          const tryY = Math.max(padTop + boxHeight / 2, Math.min(height - padBottom - boxHeight / 2, pointY + offset));
          const rect = {
            left: labelX - boxWidth / 2,
            right: labelX + boxWidth / 2,
            top: tryY - boxHeight / 2,
            bottom: tryY + boxHeight / 2,
          };
          const collides = occupiedLabels.some((placed) => !(rect.right < placed.left || rect.left > placed.right || rect.bottom < placed.top || rect.top > placed.bottom));
          if (!collides) {
            occupiedLabels.push(rect);
            labelY = tryY;
            break;
          }
        }
        if (labelY === null) return "";
        return `<g class="chart-point-label ${series.color}">
          <rect x="${(labelX - boxWidth / 2).toFixed(1)}" y="${(labelY - boxHeight / 2).toFixed(1)}" width="${boxWidth.toFixed(1)}" height="${boxHeight}" rx="2"></rect>
          <text x="${labelX.toFixed(1)}" y="${(labelY + 6).toFixed(1)}" text-anchor="middle">${escapeHtml(value)}</text>
        </g>`;
      })
      .join("");
    const line = series.data.length > 1 ? `<polyline points="${coords.join(" ")}"></polyline>` : "";
    return `<g class="chart-series ${series.color}">${line}${pointLabels}${circles}</g>`;
  };

  const legendEntries = lineSeries.map((series, i) => {
    const legendWidth = 150;
    const spacing = 16;
    const totalWidth = lineSeries.length * legendWidth + (lineSeries.length - 1) * spacing;
    const startX = width / 2 - totalWidth / 2;
    const x1 = startX + i * (legendWidth + spacing);
    return `<line class="legend-line ${series.color}" x1="${x1}" y1="${height - 18}" x2="${x1 + 40}" y2="${height - 18}"></line>
      <text class="axis-label" x="${x1 + 48}" y="${height - 13}">${escapeHtml(series.label)}</text>`;
  }).join("");

  // Bottom series (usually overall) labels "below" to avoid collision with top
  const seriesLabelSide = (index) => (index === lineSeries.length - 1 && lineSeries.length > 1 ? "below" : "above");

  return `<svg class="elo-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Elo history chart">
    <rect class="chart-bg" x="0" y="0" width="${width}" height="${height}"></rect>
    ${yTicks.map((tick) => `<line class="grid-line" x1="${padLeft}" y1="${yFor(tick).toFixed(1)}" x2="${width - padRight}" y2="${yFor(tick).toFixed(1)}"></line><text class="axis-label" x="${padLeft - 12}" y="${(yFor(tick) + 5).toFixed(1)}" text-anchor="end">${fmt(tick)}</text>`).join("")}
    <line class="axis-line" x1="${padLeft}" y1="${padTop}" x2="${padLeft}" y2="${height - padBottom}"></line>
    <line class="axis-line" x1="${padLeft}" y1="${height - padBottom}" x2="${width - padRight}" y2="${height - padBottom}"></line>
    ${lineSeries.map((series, i) => renderSeries(series, seriesLabelSide(i))).join("")}
    <text class="axis-title" x="20" y="${height / 2}" transform="rotate(-90 20 ${height / 2})">ELO</text>
    <text class="axis-label" x="${padLeft}" y="${height - 26}" text-anchor="start">${escapeHtml(firstDate)}</text>
    <text class="axis-label" x="${width - padRight}" y="${height - 26}" text-anchor="end">${escapeHtml(lastDate)}</text>
    <g class="chart-legend">${legendEntries}</g>
  </svg>`;
}

function normalizeChartSeries(history) {
  return [...history]
    .sort((a, b) => `${a.date}-${a.fight_id}`.localeCompare(`${b.date}-${b.fight_id}`))
    .map((point) => ({ date: point.date, rating: Number(point.rating) }))
    .filter((point) => Number.isFinite(point.rating));
}

function pickLabelIndices(series, target) {
  if (series.length <= target) {
    return series.map((_, index) => index);
  }
  const indices = new Set([0, series.length - 1]);
  let peakIndex = 0;
  let valleyIndex = 0;
  series.forEach((point, index) => {
    if (point.rating > series[peakIndex].rating) peakIndex = index;
    if (point.rating < series[valleyIndex].rating) valleyIndex = index;
  });
  indices.add(peakIndex);
  indices.add(valleyIndex);
  const step = (series.length - 1) / Math.max(1, target - 1);
  for (let i = 0; i < target; i += 1) {
    indices.add(Math.round(i * step));
  }
  return Array.from(indices).sort((a, b) => a - b);
}

function makeTicks(min, max, count) {
  if (max <= min) return [min];
  const step = (max - min) / Math.max(1, count - 1);
  return Array.from({ length: count }, (_, index) => Math.round((min + step * index) / 25) * 25);
}

function renderFightLog(logs) {
  return renderTable(
    ["Date", "Opponent", "Result", "Elo", "Change", "Opp. Elo", "Promotion", "Event"],
    logs.map((item) => {
      const isRed = item.red_name !== item.opponent;
      let result = "NC";
      if (item.outcome === "draw") result = "Draw";
      if (item.outcome === "red_win") result = isRed ? "Win" : "Loss";
      if (item.outcome === "blue_win") result = isRed ? "Loss" : "Win";
      return row([
        escapeHtml(item.date),
        fighterLink(item.opponent),
        result,
        `${fmt(item.pre_elo)} -> ${fmt(item.post_elo)}`,
        signed(item.elo_delta),
        fmt(item.opponent_elo),
        escapeHtml(promotionName(item)),
        `${escapeHtml(displayEventName(item.event_name))}<br><span class="muted">${escapeHtml(item.method)}</span>`,
      ]);
    })
  );
}

function promotionName(item) {
  const eventName = String(item.event_name || "").trim();
  if (!eventName) return item.source || "-";
  const colonPrefix = eventName.split(":")[0].trim();
  if (/^ufc\b/i.test(colonPrefix)) return "UFC";
  if (/^bellator\b/i.test(colonPrefix)) return "Bellator";
  if (/^pfl\b/i.test(colonPrefix)) return "PFL";
  if (/^rizin\b/i.test(colonPrefix)) return "Rizin";
  if (/^dream\b/i.test(colonPrefix)) return "DREAM";
  if (/^cage warriors\b/i.test(colonPrefix)) return "Cage Warriors";
  if (/^lfa\b/i.test(colonPrefix)) return "LFA";
  if (/^one\b/i.test(colonPrefix)) return "ONE";
  if (/^oktagon\b/i.test(colonPrefix)) return "OKTAGON";
  if (/^ksw\b/i.test(colonPrefix)) return "KSW";
  if (colonPrefix) return colonPrefix;
  const token = eventName.split(/\s+/)[0];
  return token || (item.source || "-");
}

const renderers = {
  home: renderHome,
  fighters: renderFighters,
  rankings: renderRankings,
  champions: renderChampions,
  fighter: renderFighter,
};

renderers[page]()
  .then(() => {
    initializeAds();
  })
  .catch((error) => {
    app.innerHTML = `<section class="band error"><h1>Data load failed</h1><p>${escapeHtml(error.message)}</p></section>`;
    console.error(error);
  });
