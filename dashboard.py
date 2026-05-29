"""
dashboard.py
============
Dashboard d'évaluation des politiques de mobilité durable — Lille vs Montpellier

Lance avec :  python dashboard.py
Ouvre :       http://localhost:5000

Pages :
  /           → Vue synthèse (scores politiques + KPIs clés)
  /compare    → Comparaison Lille vs Montpellier
  /analyse    → Analyse temporelle + avant/après
  /kpi        → KPIs opérationnels détaillés
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config.settings import settings, patch_windows_encoding

patch_windows_encoding()

from flask import Flask, jsonify, render_template_string
from sqlalchemy import create_engine, text

app = Flask(__name__)


def get_engine():
    return create_engine(
        settings.database_url,
        connect_args={"options": "-c client_encoding=UTF8", "client_encoding": "utf8"},
        pool_pre_ping=True,
    )


def query(sql: str, params: dict | None = None) -> list[dict]:
    try:
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text(sql), params or {})
            cols = result.keys()
            return [dict(zip(cols, row)) for row in result]
    except Exception as e:
        return [{"error": str(e)}]


def _serialize(rows: list[dict], date_cols: list[str]) -> list[dict]:
    for r in rows:
        for col in date_cols:
            if col in r and hasattr(r[col], "isoformat"):
                r[col] = r[col].isoformat()
    return rows


# ---------------------------------------------------------------------------
# SHARED CSS
# ---------------------------------------------------------------------------

CSS = r"""
:root {
  --bg: #0a0e1a; --surface: #111827; --surface2: #1a2235; --border: #1e2d45;
  --accent: #00d4ff; --accent2: #7c3aed; --green: #10b981; --yellow: #f59e0b;
  --red: #ef4444; --text: #e2e8f0; --muted: #64748b;
  --font-mono: 'Space Mono', monospace; --font-sans: 'DM Sans', sans-serif;
  --lille: #60a5fa; --mtp: #a78bfa;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font-family: var(--font-sans); min-height: 100vh; overflow-x: hidden; }
body::before {
  content: ''; position: fixed; inset: 0;
  background-image: linear-gradient(rgba(0,212,255,.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,212,255,.03) 1px, transparent 1px);
  background-size: 40px 40px; pointer-events: none; z-index: 0;
}
header {
  position: relative; z-index: 10; padding: 20px 32px;
  border-bottom: 1px solid var(--border); display: flex; align-items: center;
  justify-content: space-between; background: rgba(10,14,26,.9); backdrop-filter: blur(12px);
}
.logo { font-family: var(--font-mono); font-size: 13px; color: var(--accent); letter-spacing: 3px; text-transform: uppercase; }
.logo span { color: var(--muted); }
nav { display: flex; gap: 8px; }
nav a {
  font-family: var(--font-mono); font-size: 11px; letter-spacing: 1px;
  padding: 6px 14px; border-radius: 6px; border: 1px solid var(--border);
  color: var(--muted); text-decoration: none; transition: all .15s;
}
nav a:hover, nav a.active { background: rgba(0,212,255,.08); border-color: var(--accent); color: var(--accent); }
.main { position: relative; z-index: 1; padding: 28px 32px; max-width: 1600px; margin: 0 auto; }
.card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 24px; position: relative; overflow: hidden; transition: border-color .2s;
}
.card:hover { border-color: rgba(0,212,255,.3); }
.card-title {
  font-family: var(--font-mono); font-size: 10px; letter-spacing: 2px;
  text-transform: uppercase; color: var(--muted); margin-bottom: 20px;
  display: flex; align-items: center; gap: 10px;
}
.card-title::after { content: ''; flex: 1; height: 1px; background: var(--border); }
.grid { display: grid; gap: 20px; }
.grid-2 { grid-template-columns: 1fr 1fr; }
.grid-3 { grid-template-columns: 1fr 1fr 1fr; }
.grid-4 { grid-template-columns: repeat(4, 1fr); }
.wide { grid-column: 1 / -1; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th {
  font-family: var(--font-mono); font-size: 10px; letter-spacing: 1px; color: var(--muted);
  text-transform: uppercase; padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border);
}
td { padding: 10px 12px; border-bottom: 1px solid rgba(30,45,69,.5); }
tr:last-child td { border-bottom: none; }
tr:hover td { background: rgba(0,212,255,.03); }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-family: var(--font-mono); font-size: 10px; font-weight: 700; }
.badge-up { background: rgba(16,185,129,.15); color: var(--green); }
.badge-stable { background: rgba(0,212,255,.15); color: var(--accent); }
.badge-down { background: rgba(239,68,68,.15); color: var(--red); }
.badge-na { background: rgba(100,116,139,.15); color: var(--muted); }
.badge-ok { background: rgba(16,185,129,.15); color: var(--green); }
.badge-attention { background: rgba(245,158,11,.15); color: var(--yellow); }
.badge-alerte { background: rgba(239,68,68,.15); color: var(--red); }
.badge-success { background: rgba(16,185,129,.15); color: var(--green); }
.badge-running { background: rgba(0,212,255,.15); color: var(--accent); }
.badge-error { background: rgba(239,68,68,.15); color: var(--red); }
.num { font-family: var(--font-mono); font-size: 12px; }
.lille { color: var(--lille); }
.mtp { color: var(--mtp); }
.score { font-family: var(--font-mono); font-size: 28px; font-weight: 700; }
.table-scroll { max-height: 450px; overflow-y: auto; }
.table-scroll::-webkit-scrollbar { width: 4px; }
.table-scroll::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
.empty { text-align: center; color: var(--muted); font-family: var(--font-mono); font-size: 12px; padding: 40px 20px; }
.score-bar-bg { background: var(--surface2); border-radius: 4px; height: 8px; width: 100%; overflow: hidden; }
.score-bar { height: 100%; border-radius: 4px; transition: width .5s; }
.dim-douce { color: #34d399; }
.dim-air { color: #a78bfa; }
.dim-tc { color: #60a5fa; }
.dim-trafic { color: #fb923c; }
.dim-global { color: var(--accent); }
.delta-pos { color: var(--green); }
.delta-neg { color: var(--red); }
.delta-zero { color: var(--muted); }
.politique { background: var(--surface2); border-left: 3px solid var(--accent); padding: 12px 16px; border-radius: 0 8px 8px 0; margin-bottom: 12px; }
.politique h4 { font-family: var(--font-mono); font-size: 12px; color: var(--accent); margin-bottom: 4px; }
.politique p { font-size: 12px; color: var(--muted); }
"""


# ---------------------------------------------------------------------------
# PAGE 1 — SYNTHÈSE POLITIQUE
# ---------------------------------------------------------------------------

PAGE_INDEX = r"""
<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Mobilité Durable — Évaluation Politiques</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;600&display=swap" rel="stylesheet">
<style>""" + CSS + r"""
.score-card { text-align: center; padding: 24px; }
.score-card .ville-label { font-family: var(--font-mono); font-size: 11px; letter-spacing: 2px; margin-bottom: 8px; }
.score-card .score-val { font-family: var(--font-mono); font-size: 42px; font-weight: 700; line-height: 1; }
.score-card .tendance { font-family: var(--font-mono); font-size: 16px; margin-top: 4px; }
.dimension-row { display: flex; align-items: center; gap: 16px; padding: 12px 0; border-bottom: 1px solid rgba(30,45,69,.5); }
.dimension-row:last-child { border-bottom: none; }
.dim-name { width: 180px; font-family: var(--font-mono); font-size: 11px; letter-spacing: 1px; }
.dim-score { width: 60px; font-family: var(--font-mono); font-size: 16px; font-weight: 700; text-align: right; }
.dim-bar { flex: 1; }
.insight { background: var(--surface2); border-radius: 8px; padding: 16px; margin-top: 16px; }
.insight h3 { font-family: var(--font-mono); font-size: 12px; color: var(--accent); margin-bottom: 8px; letter-spacing: 1px; }
.insight p { font-size: 13px; line-height: 1.6; color: var(--text); }
</style></head><body>
<header>
  <div class="logo">MOBILITÉ <span>//</span> DURABLE <span>—</span> ÉVALUATION POLITIQUES</div>
  <nav>
    <a href="/" class="active">Synthèse</a>
    <a href="/compare">Comparaison</a>
    <a href="/analyse">Analyse</a>
    <a href="/kpi">KPIs</a>
  </nav>
</header>
<div class="main">
  <div class="grid grid-2" style="margin-bottom:20px">
    <div class="card score-card" id="score-lille">
      <div class="ville-label lille">LILLE MÉTROPOLE</div>
      <div class="score-val" style="color:var(--lille)" id="s-lille">—</div>
      <div class="tendance" id="t-lille">—</div>
    </div>
    <div class="card score-card" id="score-mtp">
      <div class="ville-label mtp">MONTPELLIER 3M</div>
      <div class="score-val" style="color:var(--mtp)" id="s-mtp">—</div>
      <div class="tendance" id="t-mtp">—</div>
    </div>
  </div>
  <div class="grid grid-2" style="margin-bottom:20px">
    <div class="card">
      <div class="card-title">⬡ Dimensions — Lille</div>
      <div id="dims-lille"></div>
    </div>
    <div class="card">
      <div class="card-title">⬡ Dimensions — Montpellier</div>
      <div id="dims-mtp"></div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">◈ Analyse — Les politiques fonctionnent-elles ?</div>
    <div id="insight"></div>
  </div>
</div>
<script>
const tendanceBadge = t => ({'UP':'badge-up','STABLE':'badge-stable','DOWN':'badge-down','NA':'badge-na','↑':'badge-up','→':'badge-stable','↓':'badge-down','—':'badge-na'}[t]||'badge-na');
const dimClass = d => ({'MOBILITE_DOUCE':'dim-douce','QUALITE_AIR':'dim-air','EFFICACITE_TC':'dim-tc','TRAFIC_ROUTIER':'dim-trafic','SCORE_GLOBAL':'dim-global'}[d]||'');
const dimLabel = d => ({'MOBILITE_DOUCE':'Mobilité Douce','QUALITE_AIR':'Qualité de l\'Air','EFFICACITE_TC':'Efficacité TC','TRAFIC_ROUTIER':'Trafic Routier','SCORE_GLOBAL':'Score Global'}[d]||d);
const barColor = s => s >= 70 ? 'var(--green)' : s >= 45 ? 'var(--yellow)' : 'var(--red)';

async function load() {
  try {
    const scores = await fetch('/api/policy_scores').then(r=>r.json());
    renderScores(scores);
    renderInsight(scores);
  } catch(e) { console.error(e); }
}

function renderScores(scores) {
  const byVille = {};
  scores.forEach(s => {
    if (!byVille[s.ville]) byVille[s.ville] = [];
    byVille[s.ville].push(s);
  });

  ['Lille','Montpellier'].forEach(ville => {
    const vScores = byVille[ville] || [];
    const global = vScores.find(s => s.dimension === 'SCORE_GLOBAL');
    const el = ville === 'Lille' ? 'lille' : 'mtp';
    document.getElementById('s-' + el).textContent = global ? Math.round(global.score) : '—';
    document.getElementById('t-' + el).innerHTML = global ? '<span class="badge ' + tendanceBadge(global.tendance) + '">' + global.tendance + '</span>' : '—';

    const dims = vScores.filter(s => s.dimension !== 'SCORE_GLOBAL');
    const container = document.getElementById('dims-' + el);
    if (!dims.length) {
      container.innerHTML = '<div class="empty">En attente du 1er cycle d\'évaluation (5 min)</div>';
      return;
    }
    container.innerHTML = dims.map(s => {
      const pct = Math.max(0, Math.min(100, s.score));
      return '<div class="dimension-row">' +
        '<div class="dim-name ' + dimClass(s.dimension) + '">' + dimLabel(s.dimension) + '</div>' +
        '<div class="dim-score">' + Math.round(s.score) + '</div>' +
        '<div class="dim-bar"><div class="score-bar-bg"><div class="score-bar" style="width:' + pct + '%;background:' + barColor(s.score) + '"></div></div></div>' +
        '<span class="badge ' + tendanceBadge(s.tendance) + '">' + s.tendance + '</span>' +
        '</div>';
    }).join('');
  });
}

function renderInsight(scores) {
  const container = document.getElementById('insight');
  const byVille = {};
  scores.forEach(s => { if (!byVille[s.ville]) byVille[s.ville] = []; byVille[s.ville].push(s); });
  const gLille = (byVille['Lille']||[]).find(s => s.dimension === 'SCORE_GLOBAL');
  const gMtp = (byVille['Montpellier']||[]).find(s => s.dimension === 'SCORE_GLOBAL');

  if (!gLille && !gMtp) {
    container.innerHTML = '<div class="insight"><p>Les scores politiques seront calculés automatiquement après le premier cycle d\'ingestion. Patiente environ 5 minutes après le démarrage du pipeline.</p></div>';
    return;
  }

  let html = '<div class="insight">';
  const sL = gLille ? gLille.score : 0;
  const sM = gMtp ? gMtp.score : 0;
  const leader = sL > sM + 3 ? 'Lille' : sM > sL + 3 ? 'Montpellier' : 'Les deux villes';

  html += '<h3>📊 Verdict</h3>';
  html += '<p>' + leader + ' ' + (leader.includes('deux') ? 'sont à égalité' : 'mène') + ' en matière de politiques de mobilité durable. ';

  if (gLille && gMtp) {
    const dims = ['MOBILITE_DOUCE','QUALITE_AIR','EFFICACITE_TC','TRAFIC_ROUTIER'];
    const forces = [];
    dims.forEach(d => {
      const l = (byVille['Lille']||[]).find(s => s.dimension === d);
      const m = (byVille['Montpellier']||[]).find(s => s.dimension === d);
      if (l && m) {
        if (l.score > m.score + 5) forces.push('<strong class="lille">Lille</strong> est plus performant sur <strong>' + dimLabel(d) + '</strong>');
        else if (m.score > l.score + 5) forces.push('<strong class="mtp">Montpellier</strong> est plus performant sur <strong>' + dimLabel(d) + '</strong>');
      }
    });
    if (forces.length) html += forces.join('. ') + '.';
  }
  html += '</p></div>';
  container.innerHTML = html;
}

load();
setInterval(load, 15000);
</script>
</body></html>
"""


# ---------------------------------------------------------------------------
# PAGE 2 — COMPARAISON LILLE VS MONTPELLIER
# ---------------------------------------------------------------------------

PAGE_COMPARE = r"""
<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Mobilité Durable — Comparaison</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;600&display=swap" rel="stylesheet">
<style>""" + CSS + r"""
.compare-bar { display: flex; align-items: center; gap: 0; margin: 8px 0; height: 32px; }
.compare-bar .left { background: var(--lille); height: 100%; border-radius: 4px 0 0 4px; display: flex; align-items: center; justify-content: flex-end; padding: 0 8px; font-family: var(--font-mono); font-size: 11px; color: var(--bg); min-width: 30px; transition: width .5s; }
.compare-bar .center { background: var(--surface2); height: 100%; flex: 1; display: flex; align-items: center; justify-content: center; font-family: var(--font-mono); font-size: 10px; color: var(--muted); min-width: 100px; }
.compare-bar .right { background: var(--mtp); height: 100%; border-radius: 0 4px 4px 0; display: flex; align-items: center; padding: 0 8px; font-family: var(--font-mono); font-size: 11px; color: var(--bg); min-width: 30px; transition: width .5s; }
.dim-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px solid var(--border); }
.dim-header .label { font-family: var(--font-mono); font-size: 11px; letter-spacing: 1px; }
.leader-badge { font-family: var(--font-mono); font-size: 10px; padding: 2px 8px; border-radius: 4px; }
</style></head><body>
<header>
  <div class="logo">MOBILITÉ <span>//</span> DURABLE <span>—</span> COMPARAISON</div>
  <nav>
    <a href="/">Synthèse</a>
    <a href="/compare" class="active">Comparaison</a>
    <a href="/analyse">Analyse</a>
    <a href="/kpi">KPIs</a>
  </nav>
</header>
<div class="main">
  <div class="grid grid-2" style="margin-bottom:20px">
    <div class="card score-card" style="text-align:center;padding:20px">
      <div style="font-family:var(--font-mono);font-size:11px;letter-spacing:2px;margin-bottom:8px" class="lille">LILLE</div>
      <div class="score" style="color:var(--lille)" id="s-lille">—</div>
    </div>
    <div class="card score-card" style="text-align:center;padding:20px">
      <div style="font-family:var(--font-mono);font-size:11px;letter-spacing:2px;margin-bottom:8px" class="mtp">MONTPELLIER</div>
      <div class="score" style="color:var(--mtp)" id="s-mtp">—</div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">⚖️ Comparaison par dimension</div>
    <div id="compare-dims"></div>
  </div>
  <div class="grid grid-2" style="margin-top:20px">
    <div class="card">
      <div class="card-title">🏛️ Politiques — Lille</div>
      <div id="pol-lille"></div>
    </div>
    <div class="card">
      <div class="card-title">🏛️ Politiques — Montpellier</div>
      <div id="pol-mtp"></div>
    </div>
  </div>
</div>
<script>
const dimLabel = d => ({'MOBILITE_DOUCE':'Mobilité Douce','QUALITE_AIR':'Qualité de l\'Air','EFFICACITE_TC':'Efficacité TC','TRAFIC_ROUTIER':'Trafic Routier','SCORE_GLOBAL':'Score Global'}[d]||d);
const dimClass = d => ({'MOBILITE_DOUCE':'dim-douce','QUALITE_AIR':'dim-air','EFFICACITE_TC':'dim-tc','TRAFIC_ROUTIER':'dim-trafic','SCORE_GLOBAL':'dim-global'}[d]||'');
const tendanceBadge = t => ({'UP':'badge-up','STABLE':'badge-stable','DOWN':'badge-down','NA':'badge-na'}[t]||'badge-na');

const POLITIQUES = {
  'Lille': [
    {nom:'Plan Climat Lille Métropole', date:'2024-01-01', desc:'Plan climat territorial — objectifs mobilité douce'},
    {nom:'Extension réseau V\'Lille', date:'2024-06-01', desc:'Nouvelles stations V\'Lille en périphérie'},
  ],
  'Montpellier': [
    {nom:'Plan Mobilités Montpellier 3M', date:'2024-03-01', desc:'Réorganisation réseau TAM + vélos'},
    {nom:'Lignes gratuites TAM', date:'2024-09-01', desc:'Gratuité TC certaines lignes'},
  ]
};

async function load() {
  try {
    const scores = await fetch('/api/policy_scores').then(r=>r.json());
    const byVille = {};
    scores.forEach(s => { if (!byVille[s.ville]) byVille[s.ville] = []; byVille[s.ville].push(s); });

    const gL = (byVille['Lille']||[]).find(s => s.dimension === 'SCORE_GLOBAL');
    const gM = (byVille['Montpellier']||[]).find(s => s.dimension === 'SCORE_GLOBAL');
    document.getElementById('s-lille').textContent = gL ? Math.round(gL.score) : '—';
    document.getElementById('s-mtp').textContent = gM ? Math.round(gM.score) : '—';

    renderComparison(byVille);
    renderPolitiques();
  } catch(e) { console.error(e); }
}

function renderComparison(byVille) {
  const dims = ['MOBILITE_DOUCE','QUALITE_AIR','EFFICACITE_TC','TRAFIC_ROUTIER','SCORE_GLOBAL'];
  const container = document.getElementById('compare-dims');
  let html = '';

  dims.forEach(d => {
    const l = (byVille['Lille']||[]).find(s => s.dimension === d);
    const m = (byVille['Montpellier']||[]).find(s => s.dimension === d);
    if (!l && !m) return;

    const sL = l ? l.score : 0;
    const sM = m ? m.score : 0;
    const total = Math.max(sL + sM, 1);
    const wL = (sL / total * 50);
    const wM = (sM / total * 50);
    const ecart = Math.abs(sL - sM).toFixed(1);
    const leader = sL > sM + 2 ? 'Lille' : sM > sL + 2 ? 'Montpellier' : 'Égalité';
    const leaderClass = leader === 'Lille' ? 'lille' : leader === 'Montpellier' ? 'mtp' : '';

    html += '<div style="margin-bottom:20px">';
    html += '<div class="dim-header"><div class="label ' + dimClass(d) + '">' + dimLabel(d) + '</div>';
    if (leader !== 'Égalité') html += '<span class="leader-badge" style="color:var(--' + leaderClass.replace('lille','lille').replace('mtp','mtp') + ')">▸ ' + leader + ' +' + ecart + '</span>';
    else html += '<span class="leader-badge" style="color:var(--muted)">Égalité</span>';
    html += '</div>';
    html += '<div class="compare-bar">';
    html += '<div class="left" style="width:' + wL + '%">' + Math.round(sL) + '</div>';
    html += '<div class="center">' + dimLabel(d) + '</div>';
    html += '<div class="right" style="width:' + wM + '%">' + Math.round(sM) + '</div>';
    html += '</div>';
    if (l) html += '<span class="badge ' + tendanceBadge(l.tendance) + '" style="margin-right:8px">Lille ' + l.tendance + '</span>';
    if (m) html += '<span class="badge ' + tendanceBadge(m.tendance) + '">Mtp ' + m.tendance + '</span>';
    html += '</div>';
  });

  container.innerHTML = html || '<div class="empty">En attente de données</div>';
}

function renderPolitiques() {
  ['Lille','Montpellier'].forEach(ville => {
    const el = ville === 'Lille' ? 'pol-lille' : 'pol-mtp';
    const pols = POLITIQUES[ville] || [];
    document.getElementById(el).innerHTML = pols.map(p =>
      '<div class="politique"><h4>' + p.nom + '</h4><p style="color:var(--accent);font-family:var(--font-mono);font-size:11px">Depuis ' + p.date + '</p><p>' + p.desc + '</p></div>'
    ).join('');
  });
}

load();
setInterval(load, 15000);
</script>
</body></html>
"""


# ---------------------------------------------------------------------------
# PAGE 3 — ANALYSE TEMPORELLE
# ---------------------------------------------------------------------------

PAGE_ANALYSE = r"""
<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Mobilité Durable — Analyse</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;600&display=swap" rel="stylesheet">
<style>""" + CSS + r"""
.timeline-row { display: flex; align-items: center; gap: 12px; padding: 8px 0; border-bottom: 1px solid rgba(30,45,69,.5); }
.timeline-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.timeline-time { width: 80px; font-family: var(--font-mono); font-size: 10px; color: var(--muted); }
.timeline-label { flex: 1; font-size: 13px; }
.timeline-score { font-family: var(--font-mono); font-size: 14px; font-weight: 700; width: 50px; text-align: right; }
.delta-pos { color: var(--green); }
.delta-neg { color: var(--red); }
.delta-zero { color: var(--muted); }
</style></head><body>
<header>
  <div class="logo">MOBILITÉ <span>//</span> DURABLE <span>—</span> ANALYSE</div>
  <nav>
    <a href="/">Synthèse</a>
    <a href="/compare">Comparaison</a>
    <a href="/analyse" class="active">Analyse</a>
    <a href="/kpi">KPIs</a>
  </nav>
</header>
<div class="main">
  <div class="card" style="margin-bottom:20px">
    <div class="card-title">📈 Évolution temporelle — Scores politiques</div>
    <div class="table-scroll">
      <table><thead><tr>
        <th>Timestamp</th><th>Ville</th><th>Dimension</th><th>Score</th><th>Tendance</th>
      </tr></thead><tbody id="timeline-body"></tbody></table>
    </div>
  </div>
  <div class="grid grid-2">
    <div class="card">
      <div class="card-title">🔬 Avant / Après politiques</div>
      <div id="before-after"></div>
    </div>
    <div class="card">
      <div class="card-title">📊 KPIs opérationnels — Tendances</div>
      <div class="table-scroll">
        <table><thead><tr>
          <th>KPI</th><th>Ville</th><th>Valeur</th><th>Alerte</th><th>Depuis</th>
        </tr></thead><tbody id="kpi-body"></tbody></table>
      </div>
    </div>
  </div>
</div>
<script>
const dimLabel = d => ({'MOBILITE_DOUCE':'Mob. Douce','QUALITE_AIR':'Air','EFFICACITE_TC':'TC','TRAFIC_ROUTIER':'Trafic','SCORE_GLOBAL':'Global'}[d]||d);
const dimClass = d => ({'MOBILITE_DOUCE':'dim-douce','QUALITE_AIR':'dim-air','EFFICACITE_TC':'dim-tc','TRAFIC_ROUTIER':'dim-trafic','SCORE_GLOBAL':'dim-global'}[d]||'');
const tendanceBadge = t => ({'UP':'badge-up','STABLE':'badge-stable','DOWN':'badge-down','NA':'badge-na'}[t]||'badge-na');
const alerteBadge = a => ({'OK':'badge-ok','ATTENTION':'badge-attention','ALERTE':'badge-alerte'}[a]||'badge-na');
const villeClass = v => v?.toLowerCase().includes('mont') ? 'mtp' : 'lille';
const relTime = ts => {
  if(!ts) return '—';
  const diff = Math.floor((Date.now() - new Date(ts+(ts.endsWith('Z')||ts.includes('+')?'':'Z')).getTime()) / 1000);
  if(diff < 0) return 'maintenant'; if(diff < 60) return diff+'s'; if(diff < 3600) return Math.floor(diff/60)+'min'; return Math.floor(diff/3600)+'h';
};

async function load() {
  try {
    const [timeline, kpis, beforeAfter] = await Promise.all([
      fetch('/api/policy_timeline').then(r=>r.json()),
      fetch('/api/kpis').then(r=>r.json()),
      fetch('/api/before_after').then(r=>r.json()),
    ]);
    renderTimeline(timeline);
    renderKPIs(kpis);
    renderBeforeAfter(beforeAfter);
  } catch(e) { console.error(e); }
}

function renderTimeline(rows) {
  const tbody = document.getElementById('timeline-body');
  if(!rows.length) { tbody.innerHTML = '<tr><td colspan="5"><div class="empty">En attente de données — le pipeline doit tourner +5 min</div></td></tr>'; return; }
  tbody.innerHTML = rows.map(r => '<tr>' +
    '<td class="num" style="color:var(--muted)">' + (r.timestamp||'').substring(11,16) + '</td>' +
    '<td class="' + villeClass(r.ville) + '">' + r.ville + '</td>' +
    '<td class="' + dimClass(r.dimension) + '">' + dimLabel(r.dimension) + '</td>' +
    '<td class="num" style="font-size:14px;font-weight:700">' + Math.round(r.score) + '</td>' +
    '<td><span class="badge ' + tendanceBadge(r.tendance) + '">' + r.tendance + '</span></td>' +
    '</tr>').join('');
}

function renderKPIs(rows) {
  const tbody = document.getElementById('kpi-body');
  if(!rows.length) { tbody.innerHTML = '<tr><td colspan="5"><div class="empty">Aucun KPI</div></td></tr>'; return; }
  tbody.innerHTML = rows.slice(0,30).map(r => '<tr>' +
    '<td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + r.kpi_id + '</td>' +
    '<td class="' + villeClass(r.ville) + '">' + r.ville + '</td>' +
    '<td class="num">' + (r.valeur?.toFixed(1)||'—') + '</td>' +
    '<td><span class="badge ' + alerteBadge(r.alerte) + '">' + r.alerte + '</span></td>' +
    '<td class="num" style="color:var(--muted)">' + relTime(r.timestamp_calcul) + '</td>' +
    '</tr>').join('');
}

function renderBeforeAfter(data) {
  const container = document.getElementById('before-after');
  if (!data || !data.length) {
    container.innerHTML = '<div class="empty"><p>En attente de données — le pipeline doit tourner quelques cycles.</p></div>';
    return;
  }

  const dimLabel = d => ({'MOBILITE_DOUCE':'Mobilité Douce','QUALITE_AIR':'Qualité de l\'Air','EFFICACITE_TC':'Efficacité TC','TRAFIC_ROUTIER':'Trafic Routier'}[d]||d);
  const dimClass = d => ({'MOBILITE_DOUCE':'dim-douce','QUALITE_AIR':'dim-air','EFFICACITE_TC':'dim-tc','TRAFIC_ROUTIER':'dim-trafic'}[d]||'');
  const villeClass = v => v?.toLowerCase().includes('mont') ? 'mtp' : 'lille';

  let html = '<table><thead><tr>' +
    '<th>Ville</th><th>Dimension</th><th>1er score</th><th>Dernier score</th><th>Delta</th>' +
    '</tr></thead><tbody>';

  data.forEach(r => {
    const delta = r.delta;
    const deltaClass = delta > 0 ? 'delta-pos' : delta < 0 ? 'delta-neg' : 'delta-zero';
    const deltaSign = delta > 0 ? '+' : '';
    html += '<tr>' +
      '<td class="' + villeClass(r.ville) + '">' + r.ville + '</td>' +
      '<td class="' + dimClass(r.dimension) + '">' + dimLabel(r.dimension) + '</td>' +
      '<td class="num">' + (r.score_avant != null ? r.score_avant.toFixed(1) : '—') + '</td>' +
      '<td class="num" style="font-weight:700">' + (r.score_apres != null ? r.score_apres.toFixed(1) : '—') + '</td>' +
      '<td class="num ' + deltaClass + '" style="font-weight:700">' + deltaSign + delta + '</td>' +
      '</tr>';
  });

  html += '</tbody></table>';
  container.innerHTML = html;
}

load();
setInterval(load, 15000);
</script>
</body></html>
"""


# ---------------------------------------------------------------------------
# PAGE 4 — KPIs OPÉRATIONNELS
# ---------------------------------------------------------------------------

PAGE_KPI = r"""
<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Mobilité Durable — KPIs</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;600&display=swap" rel="stylesheet">
<style>""" + CSS + r"""
.stat-card { text-align: center; padding: 16px; }
.stat-val { font-family: var(--font-mono); font-size: 28px; font-weight: 700; color: var(--accent); line-height: 1; margin-bottom: 4px; }
.stat-label { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }
</style></head><body>
<header>
  <div class="logo">MOBILITÉ <span>//</span> DURABLE <span>—</span> KPIs</div>
  <nav>
    <a href="/">Synthèse</a>
    <a href="/compare">Comparaison</a>
    <a href="/analyse">Analyse</a>
    <a href="/kpi" class="active">KPIs</a>
  </nav>
</header>
<div class="main">
  <div class="grid grid-4" style="margin-bottom:20px">
    <div class="card stat-card"><div class="stat-val" id="s-kpi">—</div><div class="stat-label">KPIs</div></div>
    <div class="card stat-card"><div class="stat-val" id="s-velos">—</div><div class="stat-label">Vélos</div></div>
    <div class="card stat-card"><div class="stat-val" id="s-tc">—</div><div class="stat-label">TC</div></div>
    <div class="card stat-card"><div class="stat-val" id="s-audit">—</div><div class="stat-label">Cycles</div></div>
  </div>
  <div class="card" style="margin-bottom:20px">
    <div class="card-title">⬡ KPIs opérationnels — Dernières valeurs</div>
    <div class="table-scroll">
      <table><thead><tr>
        <th>KPI</th><th>Ville</th><th>Domaine</th><th>Valeur</th><th>Unité</th><th>Fenêtre</th><th>Alerte</th><th>Calculé</th>
      </tr></thead><tbody id="kpi-body"></tbody></table>
    </div>
  </div>
  <div class="grid grid-2">
    <div class="card">
      <div class="card-title">◈ Journal pipeline</div>
      <div class="table-scroll">
        <table><thead><tr><th>Job</th><th>Statut</th><th>Durée</th><th>Records</th><th>Erreurs</th></tr></thead>
        <tbody id="audit-body"></tbody></table>
      </div>
    </div>
    <div class="card">
      <div class="card-title">◎ Stations vélos</div>
      <div class="table-scroll">
        <table><thead><tr><th>Station</th><th>Ville</th><th>Vélos</th><th>Capacité</th><th>Taux</th></tr></thead>
        <tbody id="velo-body"></tbody></table>
      </div>
    </div>
  </div>
</div>
<script>
const alerteBadge = a => ({'OK':'badge-ok','ATTENTION':'badge-attention','ALERTE':'badge-alerte','CRITIQUE':'badge-alerte'}[(a||'').toUpperCase()]||'badge-na');
const statusBadge = s => ({'SUCCESS':'badge-success','RUNNING':'badge-running','ERROR':'badge-error','PARTIAL':'badge-attention'}[(s||'').toUpperCase()]||'badge-na');
const villeClass = v => v?.toLowerCase().includes('mont') ? 'mtp' : 'lille';
const relTime = ts => { if(!ts) return '—'; const diff = Math.floor((Date.now() - new Date(ts+(ts.endsWith('Z')||ts.includes('+')?'':'Z')).getTime()) / 1000); if(diff<0) return 'now'; if(diff<60) return diff+'s'; if(diff<3600) return Math.floor(diff/60)+'min'; return Math.floor(diff/3600)+'h'; };

async function load() {
  try {
    const [stats,kpis,audit,velos] = await Promise.all([
      fetch('/api/stats').then(r=>r.json()), fetch('/api/kpis').then(r=>r.json()),
      fetch('/api/audit').then(r=>r.json()), fetch('/api/velos').then(r=>r.json()),
    ]);
    document.getElementById('s-kpi').textContent = stats.kpi_count ?? '0';
    document.getElementById('s-velos').textContent = stats.velo_count ?? '0';
    document.getElementById('s-tc').textContent = stats.tc_count ?? '0';
    document.getElementById('s-audit').textContent = stats.audit_count ?? '0';

    const kb = document.getElementById('kpi-body');
    kb.innerHTML = kpis.length ? kpis.map(r => '<tr>' +
      '<td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + r.kpi_id + '</td>' +
      '<td class="'+villeClass(r.ville)+'">' + r.ville + '</td>' +
      '<td>' + r.domaine + '</td>' +
      '<td class="num">' + (r.valeur?.toFixed(1)||'—') + '</td>' +
      '<td class="num" style="color:var(--muted)">' + r.unite + '</td>' +
      '<td class="num" style="color:var(--muted)">' + r.fenetre + '</td>' +
      '<td><span class="badge '+alerteBadge(r.alerte)+'">' + r.alerte + '</span></td>' +
      '<td class="num" style="color:var(--muted)">' + relTime(r.timestamp_calcul) + '</td></tr>').join('') :
      '<tr><td colspan="8"><div class="empty">Aucun KPI — le pipeline doit tourner</div></td></tr>';

    const ab = document.getElementById('audit-body');
    ab.innerHTML = audit.length ? audit.map(r => '<tr>' +
      '<td class="num">' + r.job_name + '</td>' +
      '<td><span class="badge '+statusBadge(r.statut)+'">' + r.statut + '</span></td>' +
      '<td class="num">' + (r.duree_ms != null ? r.duree_ms+'ms' : '—') + '</td>' +
      '<td class="num">' + (r.nb_enregistrements ?? '—') + '</td>' +
      '<td class="num">' + (r.nb_erreurs ?? '—') + '</td></tr>').join('') :
      '<tr><td colspan="5"><div class="empty">Aucun cycle</div></td></tr>';

    const vb = document.getElementById('velo-body');
    vb.innerHTML = velos.length ? velos.map(r => {
      const pct = r.taux_dispo != null ? Math.round(r.taux_dispo*100) : (r.capacite ? Math.round(r.velos_disponibles/r.capacite*100) : 0);
      const c = pct > 50 ? 'var(--green)' : pct > 20 ? 'var(--yellow)' : 'var(--red)';
      return '<tr><td style="max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + (r.nom_station||r.station_id) + '</td>' +
        '<td class="'+villeClass(r.ville)+'">' + r.ville + '</td>' +
        '<td class="num" style="color:var(--accent)">' + r.velos_disponibles + '</td>' +
        '<td class="num" style="color:var(--muted)">' + r.capacite + '</td>' +
        '<td class="num" style="color:'+c+'">' + pct + '%</td></tr>';
    }).join('') : '<tr><td colspan="5"><div class="empty">Aucune station</div></td></tr>';
  } catch(e) { console.error(e); }
}
load();
setInterval(load, 15000);
</script>
</body></html>
"""


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.route("/")
def page_index():
    return render_template_string(PAGE_INDEX)


@app.route("/compare")
def page_compare():
    return render_template_string(PAGE_COMPARE)


@app.route("/analyse")
def page_analyse():
    return render_template_string(PAGE_ANALYSE)


@app.route("/kpi")
def page_kpi():
    return render_template_string(PAGE_KPI)


@app.route("/api/stats")
def api_stats():
    rows = query("""
        SELECT
            (SELECT COUNT(*) FROM kpi_historique)   as kpi_count,
            (SELECT COUNT(*) FROM velo_stations)    as velo_count,
            (SELECT COUNT(*) FROM tc_retards)       as tc_count,
            (SELECT COUNT(*) FROM pipeline_audit)   as audit_count
    """)
    return jsonify(rows[0] if rows else {})


@app.route("/api/kpis")
def api_kpis():
    rows = query("""
        SELECT DISTINCT ON (kpi_id, ville)
            kpi_id, kpi_label, valeur, unite, ville, domaine, fenetre, alerte,
            timestamp_calcul
        FROM kpi_historique
        ORDER BY kpi_id, ville, timestamp_calcul DESC
        LIMIT 100
    """)
    return jsonify(_serialize(rows, ["timestamp_calcul"]))


@app.route("/api/audit")
def api_audit():
    rows = query("""
        SELECT job_name, statut, duree_ms, nb_enregistrements, nb_erreurs,
               timestamp_debut
        FROM pipeline_audit
        ORDER BY timestamp_debut DESC
        LIMIT 30
    """)
    return jsonify(_serialize(rows, ["timestamp_debut"]))


@app.route("/api/velos")
def api_velos():
    rows = query("""
        SELECT DISTINCT ON (station_id, ville)
            station_id, nom_station, ville,
            velos_disponibles, capacite, taux_dispo, en_service
        FROM velo_stations
        ORDER BY station_id, ville, timestamp_observation DESC
        LIMIT 100
    """)
    return jsonify(rows)


@app.route("/api/policy_scores")
def api_policy_scores():
    """Derniers scores par dimension par ville."""
    rows = query("""
        SELECT DISTINCT ON (ville, dimension)
            ville, dimension, score, tendance, nb_kpis, details, timestamp
        FROM policy_scores
        ORDER BY ville, dimension, timestamp DESC
    """)
    return jsonify(_serialize(rows, ["timestamp"]))


@app.route("/api/policy_timeline")
def api_policy_timeline():
    """Timeline des scores pour l'analyse temporelle."""
    rows = query("""
        SELECT ville, dimension, score, tendance, timestamp
        FROM policy_scores
        ORDER BY timestamp DESC
        LIMIT 100
    """)
    return jsonify(_serialize(rows, ["timestamp"]))


@app.route("/api/before_after")
def api_before_after():
    """
    Analyse avant/après : compare le 1er score et le dernier score
    enregistrés pour chaque dimension/ville.
    """
    rows = query("""
        WITH first_scores AS (
            SELECT DISTINCT ON (ville, dimension)
                ville, dimension, score AS score_avant, timestamp AS ts_avant
            FROM policy_scores
            ORDER BY ville, dimension, timestamp ASC
        ),
        last_scores AS (
            SELECT DISTINCT ON (ville, dimension)
                ville, dimension, score AS score_apres, timestamp AS ts_apres
            FROM policy_scores
            ORDER BY ville, dimension, timestamp DESC
        )
        SELECT
            f.ville,
            f.dimension,
            f.score_avant,
            l.score_apres,
            ROUND((l.score_apres - f.score_avant)::numeric, 1) AS delta,
            f.ts_avant,
            l.ts_apres
        FROM first_scores f
        JOIN last_scores l ON f.ville = l.ville AND f.dimension = l.dimension
        WHERE f.dimension != 'SCORE_GLOBAL'
        ORDER BY f.ville, f.dimension
    """)
    return jsonify(_serialize(rows, ["ts_avant", "ts_apres"]))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  MOBILITÉ DURABLE — Évaluation des Politiques Publiques")
    print("  http://localhost:5000")
    print("")
    print("  Pages :")
    print("    /        → Synthèse politique")
    print("    /compare → Lille vs Montpellier")
    print("    /analyse → Analyse temporelle")
    print("    /kpi     → KPIs opérationnels")
    print("=" * 60 + "\n")
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
