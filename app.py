"""DotIQ Intelligent Fulfillment - POC 1 demo app (Screen 2).

Run locally:  uvicorn app:app --reload
On Render:    uvicorn app:app --host 0.0.0.0 --port $PORT

ALL DATA IS ILLUSTRATIVE (synthetic).
The app reads the live Neo4j graph when NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD are set.
If the graph cannot be reached (for example the free instance is paused) it falls back to the
built-in CSV data and says so on screen, so a viewer never sees an error page.
"""
import os
import threading
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

import fulfillment as f
import graph_store

app = FastAPI(title="DotIQ Intelligent Fulfillment - POC 1 (illustrative data)")

# Illustrative "today" figure for the before/after panel. Change it in Render (DEMO_BASELINE_MINUTES).
BASELINE_MINUTES = float(os.environ.get("DEMO_BASELINE_MINUTES", "45"))

SCENARIOS = {
    "ORD-1001": ("Hero scenario", "Three viable paths: fast, cheap-but-slow, and one with stock near its safety level."),
    "ORD-1002": ("Stock shortage", "The fastest source does not have enough stock above its safety level."),
    "ORD-1003": ("Route disruption", "The quickest route is closed (illustrative bridge closure)."),
    "ORD-1004": ("No dispatch slots", "A plant has no loading slots free for this product."),
    "ORD-1005": ("Tight delivery promise", "A very short promise rules out the slower plant."),
}

CACHE_OK_SECONDS = 60      # how long we reuse what we read from the graph
CACHE_FAIL_SECONDS = 30    # how long before we try the graph again after a failure
KEEPALIVE_EVERY = 3600     # at most one keep-alive write per hour

_state = {"net": None, "source": "", "note": "", "expires": 0.0, "last_keepalive": 0.0}
_lock = threading.Lock()


def _run_keepalive():
    try:
        graph_store.keepalive()
    except Exception as e:                      # never let this affect a viewer
        print("keep-alive write failed:", type(e).__name__)


def get_network():
    """Returns (network, source, note). Source is 'graph' or 'builtin'."""
    with _lock:
        now = time.time()
        if _state["net"] is not None and now < _state["expires"]:
            return _state["net"], _state["source"], _state["note"]

        net, source, note, ttl = None, "builtin", "", CACHE_OK_SECONDS
        if graph_store.configured():
            try:
                net = f.build_network(graph_store.fetch_rows())
                source, note = "graph", "Live from the Neo4j graph"
                if now - _state["last_keepalive"] > KEEPALIVE_EVERY:
                    _state["last_keepalive"] = now
                    threading.Thread(target=_run_keepalive, daemon=True).start()
            except Exception as e:
                print("Neo4j read failed:", type(e).__name__, str(e)[:200])
                note = "The graph database did not answer (it may be paused), so built-in demo data is shown"
                ttl = CACHE_FAIL_SECONDS
        else:
            note = "Built-in demo data (no graph connection is set up here)"
        if net is None:
            net = f.load_network_from_csv()
        _state.update(net=net, source=source, note=note, expires=now + ttl)
        return net, source, note


def parse_weights(w):
    if not w:
        return None
    parts = w.split(",")
    if len(parts) != len(f.DEFAULT_WEIGHTS):
        raise HTTPException(400, "Expected 5 comma-separated weights.")
    try:
        return dict(zip(f.DEFAULT_WEIGHTS, [float(x) for x in parts]))
    except ValueError:
        raise HTTPException(400, "Weights must be numbers.")


@app.get("/api/health")
def health():
    _, source, note = get_network()
    return {"status": "ok", "data_source": source, "note": note}


@app.get("/api/orders")
def orders():
    net, source, note = get_network()
    out = []
    for oid in sorted(net.orders):
        o = net.orders[oid]
        d = net.dealers.get(o["dealer_id"], {})
        s = net.skus.get(o["sku_id"], {})
        sc = SCENARIOS.get(oid)
        out.append({
            "order_id": oid,
            "dealer_id": o["dealer_id"],
            "dealer_name": d.get("dealer_name", o["dealer_id"]),
            "sku_id": o["sku_id"],
            "sku_description": s.get("description", o["sku_id"]),
            "quantity_tons": int(o["quantity_tons"]),
            "priority": o["priority"],
            "scenario": sc[0] if sc else None,
        })
    return {"orders": out, "default_weights": f.DEFAULT_WEIGHTS, "data_source": source, "note": note,
            "baseline_minutes": BASELINE_MINUTES}


@app.get("/api/evaluate/{order_id}")
def evaluate(order_id: str, w: str = ""):
    net, source, note = get_network()
    if order_id not in net.orders:
        raise HTTPException(404, "Unknown order.")
    try:
        res = f.evaluate_order(net, order_id, parse_weights(w))
    except ValueError as e:
        raise HTTPException(400, str(e))
    sc = SCENARIOS.get(order_id)
    res.update(data_source=source, note=note, baseline_minutes=BASELINE_MINUTES,
               scenario=sc[0] if sc else None, scenario_note=sc[1] if sc else None)
    return res


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DotIQ Intelligent Fulfillment (POC 1)</title>
<style>
  :root{
    --bg:#f4f6fa; --card:#ffffff; --ink:#0f172a; --muted:#5b6b82; --line:#e3e8f0;
    --brand:#1d4ed8; --ok:#16a34a; --okbg:#e8f7ee; --bad:#dc2626; --badbg:#fdecec; --warn:#b45309; --warnbg:#fef3c7;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
  header{background:#0b1b3a;color:#fff;padding:14px 16px}
  .wrap{max-width:1080px;margin:0 auto;padding:0 16px}
  header .wrap{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;justify-content:space-between;padding:0}
  .brand{font-weight:700;font-size:18px;letter-spacing:.2px}
  .brand small{display:block;font-weight:400;font-size:13px;opacity:.8}
  .badge{font-size:12px;border-radius:999px;padding:4px 10px;background:#1e3a8a;color:#dbeafe}
  .badge.warn{background:var(--warnbg);color:var(--warn)}
  .notice{background:#eef2ff;color:#334155;font-size:13px;padding:8px 16px;border-bottom:1px solid var(--line)}
  main{padding:16px 0 40px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}
  h2{font-size:16px;margin:0 0 10px}
  h3{font-size:14px;margin:0 0 6px}
  label{font-weight:600;font-size:13px;color:var(--muted);display:block;margin-bottom:6px}
  select{width:100%;padding:10px;border:1px solid #c9d3e3;border-radius:8px;font-size:15px;background:#fff}
  .pill{display:inline-block;font-size:12px;border-radius:999px;padding:2px 9px;background:#e0e7ff;color:#3730a3;margin-right:6px}
  .pill.g{background:var(--okbg);color:#166534}.pill.r{background:var(--badbg);color:#991b1b}
  .muted{color:var(--muted)}
  .grid2{display:grid;grid-template-columns:1.4fr 1fr;gap:16px}
  @media (max-width:820px){.grid2{grid-template-columns:1fr}}
  .reco{border-left:6px solid var(--ok)}
  .reco .big{font-size:24px;font-weight:700;margin:2px 0 8px}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:10px 0}
  .kpi{background:#f8fafc;border:1px solid var(--line);border-radius:10px;padding:8px 10px}
  .kpi b{display:block;font-size:18px}.kpi span{font-size:12px;color:var(--muted)}
  ul.plain{margin:6px 0 0;padding-left:18px}ul.plain li{margin:3px 0}
  .bar{height:12px;border-radius:6px;background:#e5eaf3;overflow:hidden}
  .bar i{display:block;height:100%;background:var(--brand)}
  .ba-row{margin:10px 0}.ba-row .lbl{display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px}
  table{width:100%;border-collapse:collapse;font-size:14px}
  th,td{padding:8px 6px;text-align:left;border-bottom:1px solid var(--line);vertical-align:middle}
  th{font-size:12px;color:var(--muted);font-weight:600}
  .tablewrap{overflow-x:auto}
  tr.top td{background:var(--okbg)}
  .ex{border-left:5px solid var(--bad);background:var(--badbg);border-radius:8px;padding:8px 12px;margin-bottom:8px}
  .breakdown{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}
  .bd{border:1px solid var(--line);border-radius:10px;padding:10px}
  .bd .row{display:grid;grid-template-columns:110px 1fr 34px;gap:6px;align-items:center;font-size:12px;margin:4px 0}
  .slider{display:grid;grid-template-columns:130px 1fr 44px;gap:10px;align-items:center;margin:8px 0;font-size:14px}
  input[type=range]{width:100%}
  button{border:1px solid #c9d3e3;background:#fff;border-radius:8px;padding:6px 12px;font-size:13px;cursor:pointer}
  #loading{padding:30px 16px;text-align:center;color:var(--muted)}
  .spin{display:inline-block;width:18px;height:18px;border:3px solid #c7d2fe;border-top-color:var(--brand);border-radius:50%;animation:s 1s linear infinite;vertical-align:-3px;margin-right:8px}
  @keyframes s{to{transform:rotate(360deg)}}
  svg{width:100%;height:auto;display:block}
  #map{overflow-x:auto}
  @media (max-width:700px){#map svg{min-width:640px}}
  .legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--muted);margin-top:8px}
  .legend span::before{content:"";display:inline-block;width:22px;border-top:3px solid;margin-right:6px;vertical-align:middle}
  .legend .l1::before{border-color:#16a34a}.legend .l2::before{border-color:#64748b}.legend .l3::before{border-color:#dc2626;border-top-style:dashed}
  footer{font-size:12px;color:var(--muted);padding:0 0 30px}
  details summary{cursor:pointer;font-weight:600}
  .land{padding:0;overflow:hidden}
  .land-h{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:14px 16px;background:linear-gradient(135deg,#0f172a,#1e3a8a);color:#fff}
  .land-h h2{margin:0;font-size:17px}.land-h small{display:block;color:#bfdbfe;font-weight:400;font-size:12px;margin-top:2px}
  .land-h button{background:rgba(255,255,255,.14);color:#fff;border:1px solid rgba(255,255,255,.3);border-radius:8px;padding:5px 12px;cursor:pointer;font-size:13px}
  .strip{display:flex;flex-wrap:wrap;gap:8px;padding:12px 16px;background:#f8fafc;border-bottom:1px solid var(--line)}
  .strip div{flex:1 1 90px;text-align:center}.strip b{display:block;font-size:17px;color:var(--brand)}.strip span{font-size:11px;color:var(--muted)}
  .lbody{padding:16px}
  .cols{display:grid;grid-template-columns:1.25fr .8fr 1fr;gap:14px;align-items:stretch}
  .colh{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:700;margin-bottom:8px}
  .dom{border:1px solid var(--line);border-radius:10px;padding:7px 10px;margin-bottom:6px;background:#fff;position:relative}
  .dom b{font-size:13px}.dom em{display:block;font-style:normal;font-size:11.5px;color:var(--muted)}
  .dom .rel{display:block;font-size:11.5px;color:#1e3a8a;margin-top:2px}
  .dom.poc{border-color:#86efac;background:var(--okbg)}
  .dom.poc b::after{content:" \2605 POC 1";color:#15803d;font-size:11px;font-weight:700}
  .hub{display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;border-radius:14px;background:radial-gradient(circle at 50% 40%,#dbeafe,#eff6ff);border:1px solid #bfdbfe;padding:14px}
  .hub svg{width:100%;max-width:200px}
  .hub b{font-size:15px;color:#1e3a8a}.hub span{font-size:12px;color:#334155}
  .outs .o{border-left:4px solid var(--brand);background:#f8fafc;border-radius:8px;padding:8px 10px;margin-bottom:8px;font-size:13px}
  .outs .o.hi{border-color:var(--ok);background:var(--okbg)}
  .outs .o small{display:block;color:var(--muted);font-size:11.5px}
  .arrow{display:none;text-align:center;color:var(--brand);font-size:22px;line-height:1}
  .msg{margin-top:12px;padding:10px 14px;border-radius:10px;background:#eef2ff;color:#1e293b;font-size:14px}
  .fine{font-size:11.5px;color:var(--muted);margin-top:8px}
  @media (max-width:800px){.cols{grid-template-columns:1fr}.arrow{display:block}}
</style>
</head>
<body>
<header><div class="wrap">
  <div class="brand">DotIQ &middot; Intelligent Fulfillment<small>Proof of concept 1 &middot; cement supply chain &middot; one region</small></div>
  <div id="badge" class="badge">Loading&hellip;</div>
</div></header>
<div class="notice"><div class="wrap">Illustrative demo. All data is synthetic and does not come from any company's systems. Source systems shown are <b>candidate systems, to be confirmed in discovery</b>.</div></div>

<main><div class="wrap">
  <section class="card land" id="land">
    <div class="land-h"><div><h2>The bigger picture: one connected view across your domains</h2><small>Project Setu &middot; a leading Indian cement manufacturer &middot; built from public information</small></div><button id="landbtn" type="button">Hide</button></div>
    <div id="landbody">
      <div class="strip">
        <div><b>15</b><span>plants</span></div><div><b>49.5 MTPA</b><span>cement capacity</span></div>
        <div><b>8,600+</b><span>primary trucks</span></div><div><b>550+</b><span>warehouses</span></div>
        <div><b>350+</b><span>districts served</span></div><div><b>2,900+</b><span>daily truck moves</span></div>
        <div><b>10,015</b><span>active dealers</span></div>
      </div>
      <div class="lbody">
        <div class="cols">
          <div>
            <div class="colh">1 &middot; Domains and systems they run today</div>
            <div class="dom poc"><b>Logistics &amp; fulfillment</b><em>TMS, spot bidding, vehicle tracking, plant logistics</em><span class="rel">&rarr; order &rarr; stock &rarr; plant/warehouse &rarr; route &rarr; delivery</span></div>
            <div class="dom poc"><b>Dealer / order ecosystem</b><em>Suvidha dealer app</em><span class="rel">&rarr; dealer &rarr; order &rarr; product &rarr; market</span></div>
            <div class="dom poc"><b>Core ERP &amp; procurement</b><em>SAP (HANA), Ariba</em><span class="rel">&rarr; orders, materials, suppliers, operational entities</span></div>
            <div class="dom poc"><b>Manufacturing / plant</b><em>Smart plant apps, paperless weighbridge, QR / geofencing</em><span class="rel">&rarr; capacity, constraints, plant state and change</span></div>
            <div class="dom poc"><b>Data &amp; analytics</b><em>Data lake, BI, AI-driven analytics</em><span class="rel">&rarr; signals. DotIQ adds relationships, state, change, provenance</span></div>
            <div class="dom"><b>Sales execution</b><em>Sales-force apps, Smart-D</em><span class="rel">&rarr; demand signals, account and territory context</span></div>
            <div class="dom"><b>AI / automation</b><em>DIA bots, RPA</em><span class="rel">&rarr; consumers of DotIQ context and reasoning</span></div>
            <div class="dom"><b>HR / workforce</b><em>Oracle HRIS, Nalanda learning</em><span class="rel">&rarr; future people, role and knowledge context</span></div>
          </div>
          <div>
            <div class="arrow">&darr;</div>
            <div class="colh" style="text-align:center">2 &middot; DotIQ</div>
            <div class="hub">
              <svg viewBox="0 0 200 170" aria-hidden="true">
                <g stroke="#93c5fd" stroke-width="1.6">
                  <line x1="100" y1="85" x2="30" y2="30"/><line x1="100" y1="85" x2="170" y2="30"/><line x1="100" y1="85" x2="20" y2="90"/>
                  <line x1="100" y1="85" x2="180" y2="90"/><line x1="100" y1="85" x2="45" y2="145"/><line x1="100" y1="85" x2="155" y2="145"/>
                  <line x1="30" y1="30" x2="20" y2="90"/><line x1="170" y1="30" x2="180" y2="90"/><line x1="45" y1="145" x2="155" y2="145"/>
                </g>
                <g fill="#1d4ed8"><circle cx="30" cy="30" r="9"/><circle cx="170" cy="30" r="9"/><circle cx="20" cy="90" r="8"/><circle cx="180" cy="90" r="8"/><circle cx="45" cy="145" r="9"/><circle cx="155" cy="145" r="9"/></g>
                <circle cx="100" cy="85" r="20" fill="#16a34a"/><text x="100" y="89" text-anchor="middle" font-size="11" fill="#fff" font-weight="700">DotIQ</text>
              </svg>
              <b>Context graph</b>
              <span>relationships &middot; current state &middot; change &middot; source of every fact</span>
            </div>
          </div>
          <div class="outs">
            <div class="arrow">&darr;</div>
            <div class="colh">3 &middot; What you get</div>
            <div class="o hi"><b>POC 1: Intelligent Fulfillment</b><small>The best feasible path for an order, and why. Live in the demo below.</small></div>
            <div class="o"><b>Explainable decisions</b><small>Every recommendation traces back to its source system.</small></div>
            <div class="o"><b>Change awareness</b><small>Disruptions, stock and capacity changes flow into the answer.</small></div>
            <div class="o"><b>Ready for more use cases</b><small>Same graph, next questions: demand, plant, dealer service.</small></div>
          </div>
        </div>
        <div class="msg"><b>Your systems stay as they are.</b> DotIQ connects what they already know and reasons across it.</div>
        <div class="fine">Public-evidence map, not an internally validated application inventory. Product versions, integrations, ownership and data models to be confirmed during discovery. This section is explanatory and does not drive the recommendation below.</div>
      </div>
    </div>
  </section>
  <section class="card">
    <label for="order">Choose an incoming order</label>
    <select id="order" aria-label="Choose an incoming order"></select>
    <div id="orderinfo" style="margin-top:10px"></div>
  </section>

  <div id="loading"><span class="spin"></span>Waking up the demo&hellip; the first load can take up to a minute.</div>
  <div id="error" class="card" style="display:none"></div>

  <div id="content" style="display:none">
    <div class="grid2">
      <section class="card reco" id="reco"></section>
      <section class="card" id="ba"></section>
    </div>

    <section class="card">
      <h2>How this order can reach the dealer</h2>
      <div id="map"></div>
      <div class="legend"><span class="l1">Recommended</span><span class="l2">Viable alternative</span><span class="l3">Ruled out</span></div>
    </section>

    <section class="card"><h2>Ranked paths</h2><div class="tablewrap" id="table"></div></section>
    <section class="card" id="excludedCard"><h2>Paths ruled out, and why</h2><div id="excluded"></div></section>

    <section class="card"><h2>How each score is built</h2><div class="breakdown" id="breakdown"></div></section>

    <section class="card"><h2>Where each fact comes from</h2><div id="prov"></div></section>

    <section class="card">
      <h2>What matters most?</h2>
      <p class="muted" style="margin-top:0">Move the sliders and the recommendation updates instantly. Shares are re-balanced to add up to 100%.</p>
      <div id="sliders"></div>
      <button id="reset" type="button">Reset to default</button>
    </section>
  </div>

  <footer>
    Scores run from 40 (weakest viable path) to 100 (strongest) on each factor. Standard orders lean toward low cost; High and Strategic orders lean toward speed.
    The "today" decision time is an illustrative placeholder to be measured with the customer; the DotIQ time is the measured calculation time and excludes network time.
  </footer>
</div></main>

<script>
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const inr = (n) => '₹' + Number(n).toLocaleString('en-IN');
const FACTORS = [['delivery_time','Delivery time'],['freight_cost','Freight cost'],['inventory_risk','Inventory risk'],['capacity','Capacity'],['service_priority','Service priority']];
let META = null, weights = {}, timer = null, seq = 0, current = null;

function pathNames(p, res){
  const ids = [p.legs[0].from].concat(p.legs.slice(1).map((l) => l.from));
  return ids.map((id) => res.places[id].name).join(' → ');
}
function shortReason(p){ return (p.reasons[0] || '').split(':')[0]; }
function fmtMs(ms){ return ms < 1 ? '<1 ms' : ms < 1000 ? Math.round(ms) + ' ms' : (ms/1000).toFixed(1) + ' s'; }

function renderBadge(m){
  const b = $('badge');
  b.textContent = m.data_source === 'graph' ? 'Live from the Neo4j graph' : 'Built-in demo data';
  b.className = 'badge' + (m.data_source === 'graph' ? '' : ' warn');
  b.title = m.note || '';
}

function renderInfo(res){
  let h = '<span class="pill">' + esc(res.priority) + ' priority</span>' +
          '<span class="pill">Promised within ' + res.promised_max_hours + ' h</span>';
  if (res.scenario) h += '<span class="pill g">' + esc(res.scenario) + '</span>';
  if (res.scenario_note) h += '<div class="muted" style="margin-top:6px">' + esc(res.scenario_note) + '</div>';
  $('orderinfo').innerHTML = h;
}

function renderReco(res){
  const el = $('reco');
  if (!res.ranked.length){
    el.style.borderLeftColor = 'var(--bad)';
    el.innerHTML = '<h2>No feasible path</h2><p>Every option is ruled out. This order needs a planner.</p>';
    return;
  }
  el.style.borderLeftColor = 'var(--ok)';
  const p = res.ranked[0];
  el.innerHTML =
    '<div class="muted">Recommended path</div>' +
    '<div class="big">' + esc(pathNames(p, res)) + '</div>' +
    '<div class="kpis">' +
      '<div class="kpi"><b>' + p.hours + ' h</b><span>Delivery time (promise: ' + res.promised_max_hours + ' h)</span></div>' +
      '<div class="kpi"><b>' + inr(p.rupees_per_ton) + '</b><span>Freight per ton (' + inr(p.total_freight_inr) + ' total)</span></div>' +
      '<div class="kpi"><b>' + p.stock_left + ' t</b><span>Stock left above safety level</span></div>' +
      '<div class="kpi"><b>' + (p.secondary_movement ? 'Via depot' : 'None') + '</b><span>Extra handling (secondary movement)</span></div>' +
    '</div>' +
    '<h3>Why this path</h3><ul class="plain">' + res.explanation.slice(1).map((l) => '<li>' + esc(l) + '</li>').join('') + '</ul>';
}

function renderBA(res){
  const base = res.baseline_minutes, ms = res.decision_time_ms;
  const pct = Math.max(0.8, Math.min(100, ms / (base * 60000) * 100));
  $('ba').innerHTML =
    '<h2>Time to decide</h2>' +
    '<div class="ba-row"><div class="lbl"><span>Today, planner by hand <span class="pill">illustrative</span></span><b>about ' + base + ' min</b></div><div class="bar"><i style="width:100%;background:#94a3b8"></i></div></div>' +
    '<div class="ba-row"><div class="lbl"><span>With DotIQ</span><b>' + fmtMs(ms) + '</b></div><div class="bar"><i style="width:' + pct + '%;background:var(--ok)"></i></div></div>' +
    '<p class="muted" style="font-size:13px;margin-bottom:0">Faster, explained decisions shorten order-to-dispatch time. The real baseline gets measured with the customer during discovery.</p>';
}

function node(x, y, w, h, title, sub, fill, stroke){
  return '<g><rect x="'+x+'" y="'+y+'" width="'+w+'" height="'+h+'" rx="10" fill="'+fill+'" stroke="'+stroke+'" stroke-width="1.5"/>' +
    '<text x="'+(x+w/2)+'" y="'+(y+h/2-4)+'" text-anchor="middle" font-size="14" font-weight="700" fill="#0f172a">'+esc(title)+'</text>' +
    '<text x="'+(x+w/2)+'" y="'+(y+h/2+14)+'" text-anchor="middle" font-size="11.5" fill="#475569">'+esc(sub)+'</text></g>';
}
function edgeLabel(x, y, text){
  const w = text.length * 6.3 + 10;
  return '<g><rect x="'+(x-w/2)+'" y="'+(y-11)+'" width="'+w+'" height="18" rx="4" fill="#fff" opacity=".92"/>' +
    '<text x="'+x+'" y="'+(y+2)+'" text-anchor="middle" font-size="11.5" fill="#334155">'+esc(text)+'</text></g>';
}
function legText(l){ return (l.mode === 'Rail' ? 'Rail · ' : '') + l.hours + ' h · ' + inr(l.rupees_per_ton) + '/t'; }

function renderMap(res){
  const all = res.ranked.concat(res.excluded);
  const rowH = 96, top = 24, W = 840, H = Math.max(230, top + all.length * rowH);
  const dY = H / 2, dX = 690, dealer = res.places[res.dealer_id];
  const cols = {ok:'#16a34a', alt:'#64748b', bad:'#dc2626'};
  let s = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Map of the candidate paths to the dealer"><defs>';
  for (const k in cols) s += '<marker id="ar-'+k+'" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="'+cols[k]+'"/></marker>';
  s += '</defs>';
  let edges = '', nodes = '', labels = '';
  all.forEach((p, i) => {
    const y = top + i * rowH + 30;
    const kind = !p.feasible ? 'bad' : (p.rank === 1 ? 'ok' : 'alt');
    const c = cols[kind], sw = kind === 'ok' ? 4 : 2, dash = kind === 'bad' ? ' stroke-dasharray="7 5"' : '';
    const src = res.places[p.legs[0].from];
    const sub = p.feasible ? (p.stock_left + ' t left above safety') : ('✕ ' + shortReason(p));
    const fill = !p.feasible ? '#fdecec' : (p.rank === 1 ? '#e8f7ee' : '#f1f5f9');
    nodes += node(20, y - 30, 160, 60, src.name, sub, fill, c);
    const line = (x1, y1, x2, y2) => '<line x1="'+x1+'" y1="'+y1+'" x2="'+x2+'" y2="'+y2+'" stroke="'+c+'" stroke-width="'+sw+'"'+dash+' marker-end="url(#ar-'+kind+')"/>';
    if (p.legs.length === 1){
      edges += line(180, y, dX, dY);
      labels += edgeLabel(180 + (dX - 180) * .42, y + (dY - y) * .42 - 4, legText(p.legs[0]));
    } else {
      const depot = res.places[p.legs[1].from];
      edges += line(180, y, 340, y) + line(500, y, dX, dY);
      nodes += node(340, y - 30, 160, 60, depot.name, 'Rail depot', fill, c);
      labels += edgeLabel(260, y - 14, legText(p.legs[0])) + edgeLabel(500 + (dX - 500) * .22, y + (dY - y) * .22 - 4, legText(p.legs[1]));
    }
  });
  nodes += node(dX, dY - 36, 140, 72, dealer.name, 'Delivery point', '#dbeafe', '#1d4ed8');
  $('map').innerHTML = s + edges + nodes + labels + '</svg>';
}

function renderTable(res){
  if (!res.ranked.length){ $('table').innerHTML = '<p class="muted">No feasible paths.</p>'; return; }
  let h = '<table><thead><tr><th>Rank</th><th>Path</th><th>Time</th><th>Freight / ton</th><th>Order freight</th><th>Stock left</th><th>Extra handling</th><th style="min-width:130px">Score</th></tr></thead><tbody>';
  res.ranked.forEach((p) => {
    h += '<tr class="' + (p.rank === 1 ? 'top' : '') + '"><td>' + p.rank + '</td><td><b>' + esc(pathNames(p, res)) + '</b></td>' +
      '<td>' + p.hours + ' h</td><td>' + inr(p.rupees_per_ton) + '</td><td>' + inr(p.total_freight_inr) + '</td><td>' + p.stock_left + ' t</td>' +
      '<td>' + (p.secondary_movement ? 'Via depot' : '—') + '</td>' +
      '<td><b>' + p.total_score.toFixed(1) + '</b><div class="bar" style="margin-top:4px"><i style="width:' + p.total_score + '%"></i></div></td></tr>';
  });
  $('table').innerHTML = h + '</tbody></table>';
}

function renderExcluded(res){
  $('excludedCard').style.display = res.excluded.length ? '' : 'none';
  $('excluded').innerHTML = res.excluded.map((p) =>
    '<div class="ex"><b>' + esc(pathNames(p, res)) + '</b> <span class="muted">(' + p.hours + ' h, ' + inr(p.rupees_per_ton) + '/ton)</span><ul class="plain">' +
    p.reasons.map((r) => '<li>' + esc(r) + '</li>').join('') + '</ul></div>').join('');
}

function renderBreakdown(res){
  const w = res.weights_used;
  $('breakdown').innerHTML = res.ranked.map((p) =>
    '<div class="bd"><h3>' + esc(pathNames(p, res)) + ' <span class="muted">· ' + p.total_score.toFixed(1) + '</span></h3>' +
    FACTORS.map(([k, name]) =>
      '<div class="row"><span>' + name + ' <span class="muted">' + Math.round(w[k]) + '%</span></span><div class="bar"><i style="width:' + p.scores[k] + '%"></i></div><span>' + Math.round(p.scores[k]) + '</span></div>').join('') +
    '</div>').join('');
}

function renderProv(res){
  if (!res.ranked.length){ $('prov').innerHTML = '<p class="muted">Nothing to show.</p>'; return; }
  const p = res.ranked[0];
  $('prov').innerHTML = '<p class="muted" style="margin-top:0">Facts behind the recommended path. Systems named are candidates, to be confirmed in discovery.</p>' +
    '<div class="tablewrap"><table><thead><tr><th>Fact</th><th>Value</th><th>Candidate source system</th></tr></thead><tbody>' +
    p.facts.map((f) => '<tr><td>' + esc(f[0]) + '</td><td><b>' + esc(f[1]) + '</b></td><td class="muted">' + esc(f[2]) + '</td></tr>').join('') + '</tbody></table></div>';
}

function renderSliders(){
  const total = FACTORS.reduce((a, [k]) => a + Number(weights[k]), 0) || 1;
  $('sliders').innerHTML = FACTORS.map(([k, name]) =>
    '<div class="slider"><span>' + name + '</span><input type="range" min="0" max="100" step="5" value="' + weights[k] + '" data-k="' + k + '" aria-label="' + name + '"><b id="pc-' + k + '">' + Math.round(weights[k] / total * 100) + '%</b></div>').join('');
  document.querySelectorAll('#sliders input').forEach((inp) => inp.addEventListener('input', () => {
    weights[inp.dataset.k] = Number(inp.value);
    const t = FACTORS.reduce((a, [k]) => a + Number(weights[k]), 0) || 1;
    FACTORS.forEach(([k]) => { $('pc-' + k).textContent = Math.round(weights[k] / t * 100) + '%'; });
    clearTimeout(timer); timer = setTimeout(evaluate, 250);
  }));
}

function showError(msg){
  $('loading').style.display = 'none';
  $('content').style.display = 'none';
  $('error').style.display = 'block';
  $('error').innerHTML = '<h2>The demo is not answering right now</h2><p>' + esc(msg) + '</p><p class="muted">Please wait a minute and refresh the page.</p>';
}

function render(res){
  current = res;
  $('loading').style.display = 'none'; $('error').style.display = 'none'; $('content').style.display = 'block';
  renderBadge(res); renderInfo(res); renderReco(res); renderBA(res); renderMap(res);
  renderTable(res); renderExcluded(res); renderBreakdown(res); renderProv(res);
}

async function evaluate(){
  const my = ++seq;
  try {
    const w = FACTORS.map(([k]) => weights[k]).join(',');
    const r = await fetch('/api/evaluate/' + encodeURIComponent($('order').value) + '?w=' + w);
    if (!r.ok) throw new Error('The server answered with an error (' + r.status + ').');
    const res = await r.json();
    if (my === seq) render(res);
  } catch (e) { if (my === seq) showError(e.message); }
}

async function init(){
  try {
    const r = await fetch('/api/orders');
    if (!r.ok) throw new Error('The server answered with an error (' + r.status + ').');
    META = await r.json();
    weights = Object.assign({}, META.default_weights);
    $('order').innerHTML = META.orders.map((o) =>
      '<option value="' + esc(o.order_id) + '">' + esc(o.order_id) + ' — ' + o.quantity_tons + ' t ' + esc(o.sku_description) + ' → ' + esc(o.dealer_name) +
      (o.scenario ? '   [' + esc(o.scenario) + ']' : '') + '</option>').join('');
    renderBadge(META); renderSliders();
    $('order').addEventListener('change', evaluate);
    $('reset').addEventListener('click', () => { weights = Object.assign({}, META.default_weights); renderSliders(); evaluate(); });
    await evaluate();
  } catch (e) { showError(e.message); }
}
init();

document.getElementById('landbtn').addEventListener('click', function(){
  var b=document.getElementById('landbody'), h=b.style.display==='none';
  b.style.display=h?'':'none'; this.textContent=h?'Hide':'Show';
});
</script>
</body>
</html>
"""
