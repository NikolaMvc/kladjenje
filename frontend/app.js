/* BetAdvisor — statički frontend, čita JSON sa GitHub data grane */

// !! PROMENI OVO na tvoje vrednosti posle kreiranja GitHub repo-a !!
const GITHUB_RAW = 'https://raw.githubusercontent.com/NikolaMvc/kladjenje/data';

let activeTab    = 'upcoming';
let upcomingData = [];
let liveData     = [];
let tipoviData   = [];
let pollTimer    = null;
let lastUpdated  = null;
let isFirstLoad  = true;
let fetchDone    = false;

// ─── INIT ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Odmah prikaži keširane podatke iz prošlog puta (instant, bez čekanja)
  loadFromLocalStorage();

  switchTab('upcoming');

  // Tiho osvežavaj u pozadini
  fetchAll();
  pollTimer = setInterval(fetchAll, 30000);

  document.getElementById('modal-overlay')?.addEventListener('click', e => {
    if (e.target.id === 'modal-overlay') closeModal();
  });
});

function loadFromLocalStorage() {
  try {
    const up   = localStorage.getItem('ba_upcoming');
    const live = localStorage.getItem('ba_live');
    const tip  = localStorage.getItem('ba_tipovi');
    const ts   = localStorage.getItem('ba_updated');
    if (up)   upcomingData = JSON.parse(up);
    if (live) liveData     = JSON.parse(live);
    if (tip)  tipoviData   = JSON.parse(tip);
    if (ts)   lastUpdated  = ts;
    if (upcomingData.length || liveData.length || tipoviData.length) {
      isFirstLoad = false; // imamo podatke — nema spinnera
    }
  } catch (e) { /* prvi put, nema podataka */ }
}

// ─── FETCH ────────────────────────────────────────────────────────────────────
async function fetchAll() {
  try {
    const [upRes, liveRes, tipRes] = await Promise.all([
      fetch(`${GITHUB_RAW}/upcoming.json?t=${Date.now()}`),
      fetch(`${GITHUB_RAW}/live.json?t=${Date.now()}`),
      fetch(`${GITHUB_RAW}/tipovi.json?t=${Date.now()}`),
    ]);

    const upJson   = upRes.ok   ? await upRes.json()   : { matches: [] };
    const liveJson = liveRes.ok ? await liveRes.json() : { matches: [] };
    const tipJson  = tipRes.ok  ? await tipRes.json()  : { matches: [] };

    const newUpcoming = upJson.matches   || [];
    const newLive     = liveJson.matches || [];
    const newTipovi   = tipJson.matches  || [];
    const newUpdated  = upJson.last_updated || liveJson.last_updated;

    const changed =
      JSON.stringify(newUpcoming) !== JSON.stringify(upcomingData) ||
      JSON.stringify(newLive)     !== JSON.stringify(liveData)     ||
      JSON.stringify(newTipovi)   !== JSON.stringify(tipoviData);

    upcomingData = newUpcoming;
    liveData     = newLive;
    tipoviData   = newTipovi;
    lastUpdated  = newUpdated;

    // Sačuvaj u localStorage za sledeće otvaranje
    try {
      localStorage.setItem('ba_upcoming', JSON.stringify(newUpcoming));
      localStorage.setItem('ba_live',     JSON.stringify(newLive));
      localStorage.setItem('ba_tipovi',   JSON.stringify(newTipovi));
      if (newUpdated) localStorage.setItem('ba_updated', newUpdated);
    } catch (e) { /* storage pun */ }

    if (changed || isFirstLoad) {
      if (activeTab === 'upcoming') renderMatches('panel-upcoming', upcomingData, false);
      if (activeTab === 'live')     renderMatches('panel-live',     liveData,     true);
      if (activeTab === 'tipovi')   renderTipovi();
      updateLiveBadge(newLive.length);
      isFirstLoad = false;
    }

    updateStatusBar(newUpdated);
  } catch (e) {
    console.error('fetchAll error:', e);
    updateStatusBar(null, true);
  } finally {
    fetchDone = true;
  }
}

// ─── TAB ─────────────────────────────────────────────────────────────────────
function switchTab(tab) {
  activeTab = tab;
  document.querySelectorAll('.tab-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.tab-panel').forEach(p =>
    p.classList.toggle('active', p.id === `panel-${tab}`));

  if (tab === 'upcoming') renderMatches('panel-upcoming', upcomingData, false);
  if (tab === 'live')     renderMatches('panel-live',     liveData,     true);
  if (tab === 'tipovi')   renderTipovi();
}

function handleTabClick(tab) { switchTab(tab); }

// ─── RENDER LISTE ─────────────────────────────────────────────────────────────
function renderMatches(panelId, matches, isLive) {
  const panel = document.getElementById(panelId);
  if (!panel) return;

  if (!matches || matches.length === 0) {
    if (!fetchDone) { panel.innerHTML = ''; return; }
    panel.innerHTML = `
      <div class="empty-state">
        <div class="icon">${isLive ? '📡' : '⏳'}</div>
        <p>${isLive ? 'Nema aktivnih utakmica.' : 'Podaci stižu za koji minut.'}</p>
      </div>`;
    return;
  }

  const groups = {};
  for (const m of matches) {
    const k = m.league || 'Football';
    if (!groups[k]) groups[k] = [];
    groups[k].push(m);
  }

  let html = '';
  for (const [league, ms] of Object.entries(groups)) {
    html += `
      <div class="league-group">
        <div class="league-header"><span class="league-flag">⚽</span><span>${escHtml(league)}</span></div>
        ${ms.map(m => renderCard(m, isLive)).join('')}
      </div>`;
  }
  panel.innerHTML = html;
}

function renderCard(m, isLive) {
  const tip        = m.tip || {};
  const market     = tip.market || '';
  const confidence = tip.confidence || 0;
  const stars      = tip.stars || 0;
  const hasValidTip = market && market !== 'N/A' && confidence > 0;

  const timeHtml = isLive
    ? `<span class="match-time live">${m.minute != null ? m.minute + "'" : 'LIVE'}</span>`
    : `<span class="match-time">${formatTime(m.kickoff)}</span>`;

  const sh = m.score?.home != null ? m.score.home : '';
  const sa = m.score?.away != null ? m.score.away : '';

  const odds = m.odds;
  const oddsHtml = odds?.home
    ? `<div class="odds-row">
        <span class="odds-cell">${odds.home.toFixed(2)}</span>
        <span class="odds-sep">×</span>
        <span class="odds-cell">${odds.draw != null ? odds.draw.toFixed(2) : '-'}</span>
        <span class="odds-sep">×</span>
        <span class="odds-cell">${odds.away.toFixed(2)}</span>
       </div>`
    : '';

  const tipHtml = hasValidTip ? `
    <div class="tip-row">
      <div class="tip-chip" onclick="event.stopPropagation();openModal('${escHtml(m.id)}')">
        <span class="tip-chip__icon">🎯</span>
        <span class="tip-chip__text">${escHtml(market)}</span>
      </div>
      <div style="display:flex;align-items:center;gap:6px">
        ${renderStars(stars)}
        <span class="confidence-badge">${confidence}%</span>
      </div>
    </div>
    ${oddsHtml}` : oddsHtml;

  const liveBar = isLive && m.stats ? `
    <div class="live-stats-bar">
      ${m.stats.possession ? `<span class="live-stat">⚽ ${m.stats.possession.home}%-${m.stats.possession.away}%</span>` : ''}
      ${m.stats.shots_on_target ? `<span class="live-stat">🎯 ${m.stats.shots_on_target.home}-${m.stats.shots_on_target.away}</span>` : ''}
      ${m.stats.xg ? `<span class="live-stat">xG ${m.stats.xg.home}-${m.stats.xg.away}</span>` : ''}
    </div>` : '';

  return `
    <div class="match-card" onclick="openModal('${escHtml(m.id)}')">
      <div class="match-card__top">
        ${timeHtml}
        <div class="match-teams">
          <div class="team-row">
            <span class="team-name">${escHtml(m.home_team)}</span>
            ${sh !== '' ? `<span class="team-score">${sh}</span>` : ''}
          </div>
          <div class="team-row">
            <span class="team-name">${escHtml(m.away_team)}</span>
            ${sa !== '' ? `<span class="team-score">${sa}</span>` : ''}
          </div>
        </div>
      </div>
      ${liveBar}
      ${tipHtml}
    </div>`;
}

// ─── TIPOVI TAB ───────────────────────────────────────────────────────────────
function renderTipovi() {
  const panel = document.getElementById('panel-tipovi');
  if (!panel) return;

  if (!tipoviData || tipoviData.length === 0) {
    if (!fetchDone) { panel.innerHTML = ''; return; }
    panel.innerHTML = `<div class="empty-state"><div class="icon">⏳</div><p>Tipovi stižu za koji minut.</p></div>`;
    return;
  }

  const sorted = [...tipoviData].sort((a,b) =>
    (b.tip?.confidence || 0) - (a.tip?.confidence || 0));

  let html = `<div class="tipovi-header">Top ${sorted.length} najsigurnijih tipova</div>`;
  sorted.forEach((m, i) => {
    const tip    = m.tip || {};
    const odds   = m.odds;
    const oddsStr = odds?.home
      ? `<span class="tipovi-odds">${odds.home.toFixed(2)} / ${odds.draw != null ? odds.draw.toFixed(2) : '-'} / ${odds.away.toFixed(2)}</span>`
      : '';

    html += `
      <div class="tipovi-item" onclick="openModal('${escHtml(m.id)}')">
        <div class="tipovi-rank">${i + 1}</div>
        <div class="tipovi-content">
          <div class="tipovi-match">${escHtml(m.home_team)} vs ${escHtml(m.away_team)}</div>
          <div class="tipovi-league">${escHtml(m.league || '')} · ${formatTime(m.kickoff)}</div>
          <div class="tipovi-tip">
            <span style="font-size:13px;font-weight:700;color:var(--accent)">🎯 ${escHtml(tip.market || '')}</span>
            ${oddsStr}
          </div>
        </div>
        <div class="tipovi-right">
          ${renderStars(tip.stars || 0)}
          <div class="confidence-badge large">${tip.confidence || 0}%</div>
        </div>
      </div>`;
  });

  panel.innerHTML = html;
}

// ─── STATUS BAR ───────────────────────────────────────────────────────────────
function updateStatusBar(time, error = false) {
  const el = document.getElementById('status-bar');
  if (!el) return;
  if (error) {
    el.textContent = '⚠ Greška pri učitavanju';
    el.style.color = 'var(--red)';
  } else if (time) {
    el.textContent = `✓ ${time} (osvežava se svakih 5 min)`;
    el.style.color = 'var(--text-dim)';
  }
}

// ─── MODAL (instant, iz memorije — bez API) ───────────────────────────────────
function openModal(matchId) {
  const overlay = document.getElementById('modal-overlay');
  overlay.classList.add('open');

  const match = [...upcomingData, ...liveData, ...tipoviData].find(m => m.id === matchId);
  if (!match) {
    document.getElementById('modal-header').innerHTML = '';
    document.getElementById('modal-body').innerHTML =
      `<div class="empty-state"><p>Utakmica nije pronađena.</p></div>`;
    return;
  }
  renderModal(match);
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
}

function renderModal(m) {
  const header = document.getElementById('modal-header');
  const body   = document.getElementById('modal-body');
  const tip    = m.tip || {};
  const isLive = m.status === 'live';
  const odds   = m.odds;

  header.innerHTML = `
    <div class="modal-league">${escHtml(m.league || 'Football')}</div>
    <div class="modal-teams">${escHtml(m.home_team)} vs ${escHtml(m.away_team)}</div>
    <div class="modal-meta">${isLive
      ? `⚡ UŽIVO — ${m.minute != null ? m.minute + "'" : '?'}`
      : formatTime(m.kickoff)}</div>
    ${m.score?.home != null
      ? `<div style="font-size:22px;font-weight:800;color:var(--accent);margin-top:6px">${m.score.home} - ${m.score.away}</div>`
      : ''}
    ${odds?.home
      ? `<div class="modal-odds"><span>${odds.home.toFixed(2)}</span><span>${odds.draw != null ? odds.draw.toFixed(2) : '-'}</span><span>${odds.away.toFixed(2)}</span></div>`
      : ''}`;

  let html = '';

  if (tip.market && tip.market !== 'N/A') {
    html += `
      <div class="tip-highlight">
        <div class="tip-highlight__market">🎯 ${escHtml(tip.market)}</div>
        <div class="tip-highlight__row">
          <div>${renderStars(tip.stars || 0, true)}</div>
          <div class="confidence-bar-wrap">
            <div class="confidence-bar-fill" style="width:${tip.confidence || 0}%"></div>
          </div>
          <div class="confidence-pct">${tip.confidence || 0}%</div>
        </div>
      </div>`;

    if (tip.explanation) {
      html += `<div class="section"><div class="section-title">📋 Objašnjenje</div><div class="explanation-text">${escHtml(tip.explanation)}</div></div>`;
    }

    if (tip.key_factors?.length) {
      html += `<div class="section"><div class="section-title">⚡ Ključni faktori</div><ul class="key-factors">${tip.key_factors.map(f => `<li class="key-factor">${escHtml(f)}</li>`).join('')}</ul></div>`;
    }

    if (tip.stats_breakdown?.all_markets) {
      const sorted = Object.entries(tip.stats_breakdown.all_markets).sort((a,b) => b[1]-a[1]);
      html += `<div class="section"><div class="section-title">📊 Svi marketi</div>`;
      for (const [mkt, pct] of sorted) {
        const best = mkt === tip.market;
        html += `
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
            <span style="flex:1;font-size:12px;color:${best?'var(--accent)':'var(--text-secondary)'};font-weight:${best?700:400}">${escHtml(mkt)}</span>
            <div style="width:80px;height:5px;background:var(--border);border-radius:3px;overflow:hidden">
              <div style="width:${pct}%;height:100%;background:${best?'var(--accent)':'var(--text-dim)'};border-radius:3px"></div>
            </div>
            <span style="font-size:11px;color:${best?'var(--accent)':'var(--text-dim)'};min-width:32px;text-align:right">${pct}%</span>
          </div>`;
      }
      html += `</div>`;
    }
  }

  if (m.h2h?.length) {
    html += `<div class="section"><div class="section-title">🔄 H2H (poslednjih 5)</div>`;
    for (const h of m.h2h) {
      html += `<div class="h2h-match"><span class="h2h-team home">${escHtml(h.home_team||'')}</span><span class="h2h-score">${h.score_home}-${h.score_away}</span><span class="h2h-team away">${escHtml(h.away_team||'')}</span></div>`;
    }
    html += `</div>`;
  }

  body.innerHTML = html || `<div class="empty-state"><p>Nema detalja za ovu utakmicu.</p></div>`;
}

// ─── REFRESH ─────────────────────────────────────────────────────────────────
async function doRefresh() {
  const fab = document.getElementById('refresh-fab');
  fab.classList.add('spinning');
  showToast('Osvežavanje...');
  try {
    await fetchAll();
    showToast('Podaci osveženi!');
  } catch { showToast('Greška.'); }
  finally { setTimeout(() => fab.classList.remove('spinning'), 1200); }
}

// ─── UTILS ───────────────────────────────────────────────────────────────────
function renderStars(n, large = false) {
  const sz = large ? '15px' : '10px';
  return `<div class="tip-stars">${Array.from({length:5},(_,i) =>
    `<span class="star${i>=n?' empty':''}" style="font-size:${sz}">★</span>`).join('')}</div>`;
}

function formatTime(iso) {
  if (!iso) return '';
  try { return new Date(iso).toLocaleTimeString('sr-RS', { hour:'2-digit', minute:'2-digit' }); }
  catch { return iso; }
}

function updateLiveBadge(n) {
  const b = document.getElementById('live-badge');
  if (b) { b.textContent = n; b.style.display = n > 0 ? '' : 'none'; }
}

let toastT = null;
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastT);
  toastT = setTimeout(() => t.classList.remove('show'), 2500);
}

function escHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
