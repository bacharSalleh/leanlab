"""leanlab — generic live dashboard for a lab.

Schema-driven: it reads the lab's lab.json (the objective) and results.jsonl
(flexible metrics), so it works for any lab. Shows:
  - PROGRESS chart: the objective metric across experiments + the best-so-far line.
  - RESULTS table: every metric column, best row highlighted.
  - LIVE STREAM: the running agent's messages, tool calls, timings, and cost.
  - SESSIONS: each agent run (worker / director / critic) with its cost.

`Dashboard` builds the state (the testable core); the HTTP handler is a thin shell
over a single `Dashboard` instance. Run:
    uv run python core/monitor.py --lab labs/house-prices
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

RUNNING_WINDOW = 15
PRICES = {"opus": (15.0, 75.0, 1.50), "sonnet": (3.0, 15.0, 0.30),
          "haiku": (0.80, 4.0, 0.08), "fable": (15.0, 75.0, 1.50)}
_DEFAULT_PRICE = (15.0, 75.0, 1.50)


class Dashboard:
    """Builds the live monitor state for one metric lab: results, sessions, and the agent stream."""

    _EXP_RE = re.compile(r"experiments/[A-Za-z0-9_]+\.py")

    def __init__(self, lab):
        self._lab = Path(lab)
        self._meta = {}   # session_meta cache, keyed by transcript path

    # --- lab config ---------------------------------------------------------
    def cfg(self):
        return json.loads((self._lab / "lab.json").read_text())

    def objective(self):
        o = self.cfg().get("objective", {})
        return o.get("metric", "score"), o.get("direction", "max")

    # --- pricing / timestamps (pure helpers) --------------------------------
    @staticmethod
    def _price_for(model):
        name = (model or "").lower()
        for k, r in PRICES.items():
            if k in name:
                return r
        return _DEFAULT_PRICE

    @staticmethod
    def _turn_cost(model, u):
        i, o, cr = Dashboard._price_for(model)
        return (((u.get("input_tokens") or 0) * i + (u.get("output_tokens") or 0) * o
                 + (u.get("cache_read_input_tokens") or 0) * cr
                 + (u.get("cache_creation_input_tokens") or 0) * i * 1.25) / 1e6)

    @staticmethod
    def _parse_ts(ts):
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None

    @staticmethod
    def _clip(t, limit=200000):
        if t is None:
            return ""
        t = str(t)
        return t if len(t) <= limit else t[:limit] + " …(clipped)"

    @staticmethod
    def _stringify(v):
        if isinstance(v, str):
            return v
        try:
            return json.dumps(v, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(v)

    # --- transcripts --------------------------------------------------------
    def transcript_dir(self):
        base = Path.home() / ".claude" / "projects"
        exact = base / str(self._lab).replace("/", "-")
        if exact.is_dir():
            return exact
        matches = sorted(base.glob(f"*{self._lab.name}*"))
        return matches[-1] if matches else exact

    @staticmethod
    def parse_session(path):
        events, first_user, artifact, pending = [], None, None, {}
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            return {"role": "unknown", "artifact": None}, []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind, msg = obj.get("type"), obj.get("message") or {}
            ts = obj.get("timestamp")
            ts_s = Dashboard._parse_ts(ts)
            if kind == "user":
                content = msg.get("content")
                if isinstance(content, str):
                    if first_user is None:
                        first_user = content
                    events.append({"kind": "user", "text": Dashboard._clip(content), "ts": ts})
                elif isinstance(content, list):
                    for b in content:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "tool_result":
                            dur = None
                            start = pending.pop(b.get("tool_use_id"), None)
                            if start is not None and ts_s is not None:
                                dur = round(ts_s - start, 2)
                            events.append({"kind": "result", "ts": ts, "dur": dur,
                                           "text": Dashboard._clip(Dashboard._stringify(b.get("content")))})
                        elif b.get("type") == "text":
                            if first_user is None:
                                first_user = b.get("text", "")
                            events.append({"kind": "user", "text": Dashboard._clip(b.get("text", "")), "ts": ts})
            elif kind == "assistant":
                u = msg.get("usage") or {}
                turn = {"model": msg.get("model"), "in_tok": u.get("input_tokens"),
                        "out_tok": u.get("output_tokens"),
                        "cache_tok": u.get("cache_read_input_tokens"),
                        "cost": round(Dashboard._turn_cost(msg.get("model"), u), 6) if u else None}
                firstb = True
                for b in msg.get("content") or []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text" and b.get("text", "").strip():
                        ev = {"kind": "text", "text": Dashboard._clip(b["text"]), "ts": ts}
                        if firstb:
                            ev.update(turn); firstb = False
                        events.append(ev)
                    elif b.get("type") == "tool_use":
                        raw = Dashboard._stringify(b.get("input"))
                        m = Dashboard._EXP_RE.search(raw)
                        if m and "sample.py" not in m.group(0):
                            artifact = m.group(0)
                        if ts_s is not None and b.get("id"):
                            pending[b["id"]] = ts_s
                        ev = {"kind": "tool", "name": b.get("name", "tool"), "text": Dashboard._clip(raw), "ts": ts}
                        if firstb:
                            ev.update(turn); firstb = False
                        events.append(ev)
        role = "unknown"
        if first_user:
            head = first_user.strip().splitlines()[0].lower()
            # New prompts start "You are the WORKER/DIRECTOR/CRITIC ..."; the older markers
            # ("read director.md", etc.) are kept so historical transcripts still classify.
            if head.startswith("you are the director") or head.startswith("read director.md"):
                role = "director"
            elif head.startswith("you are the critic") or head.startswith("read critic.md"):
                role = "critic"
            elif (head.startswith("you are the worker") or head.startswith("read claude.md")
                  or "exactly one experiment" in head):
                role = "worker"
        return {"role": role, "artifact": artifact}, events

    def session_meta(self, path):
        mt = path.stat().st_mtime
        c = self._meta.get(str(path))
        if c and c[0] == mt:
            return c[1]
        meta, events = self.parse_session(path)
        info = {"role": meta["role"], "artifact": meta["artifact"], "events": len(events),
                "cost": round(sum(e.get("cost") or 0 for e in events), 4)}
        self._meta[str(path)] = (mt, info)
        return info

    def list_sessions(self):
        out, now = [], time.time()
        for p in sorted(self.transcript_dir().glob("*.jsonl"),
                        key=lambda x: x.stat().st_mtime, reverse=True):
            info = self.session_meta(p)
            mt = p.stat().st_mtime
            out.append({"id": p.stem, **info, "mtime": mt, "running": (now - mt) < RUNNING_WINDOW})
        return out

    # --- results ------------------------------------------------------------
    def read_results(self):
        path = self._lab / self.cfg().get("results_file", "results.jsonl")
        if not path.exists():
            return []
        out = []
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return out

    def best_value(self, rows):
        metric, d = self.objective()
        vals = []
        for r in rows:
            try:
                vals.append(float(r.get(metric)))
            except (TypeError, ValueError):
                pass
        if not vals:
            return None
        return min(vals) if d == "min" else max(vals)

    @staticmethod
    def latest_value(rows, metric):
        """The metric of the most recent (last) experiment, or None if unparseable."""
        if not rows:
            return None
        try:
            return float(rows[-1].get(metric))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def total_cost(sessions):
        """Sum the cost across every agent session (worker / director / critic)."""
        return round(sum(s.get("cost") or 0 for s in sessions), 4)

    def build_state(self):
        sessions = self.list_sessions()
        active = next((s["id"] for s in sessions if s["running"]), None) or (sessions[0]["id"] if sessions else None)
        rows = self.read_results()
        metric, d = self.objective()
        return {
            "lab": self.cfg().get("name", self._lab.name),
            "metric": metric, "direction": d,
            "results": rows, "best": self.best_value(rows),
            "latest": self.latest_value(rows, metric), "total_cost": self.total_cost(sessions),
            "sessions": sessions, "active": active,
            "directions": (self._lab / "Director_Notes.md").read_text() if (self._lab / "Director_Notes.md").exists() else "",
            "critique": (self._lab / "Critic_Feedback.md").read_text() if (self._lab / "Critic_Feedback.md").exists() else "",
            "now": time.time(),
        }

    def session_payload(self, sid):
        path = self.transcript_dir() / f"{sid}.jsonl"
        if not path.exists():
            return {"id": sid, "meta": {}, "events": [], "totals": {}}
        meta, events = self.parse_session(path)
        tot = {"in": 0, "out": 0, "cost": 0.0, "turns": 0, "model": None}
        for e in events:
            if e.get("cost") is not None:
                tot["in"] += e.get("in_tok") or 0; tot["out"] += e.get("out_tok") or 0
                tot["cost"] += e.get("cost") or 0; tot["turns"] += 1
                if e.get("model"):
                    tot["model"] = e["model"]
        tot["cost"] = round(tot["cost"], 4)
        return {"id": sid, "meta": meta, "events": events, "totals": tot,
                "running": (time.time() - path.stat().st_mtime) < RUNNING_WINDOW}


# --- module shims (kept for the tests) --------------------------------------
def parse_session(path):
    return Dashboard.parse_session(path)


def latest_value(rows, metric):
    return Dashboard.latest_value(rows, metric)


def total_cost(sessions):
    return Dashboard.total_cost(sessions)


PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<title>leanlab · monitor</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{--bg:#0d1117;--panel:#161b22;--panel2:#1c2230;--border:#2a3240;--text:#e6edf3;
--muted:#8b949e;--accent:#58a6ff;--good:#3fb950;--bad:#f85149;--tool:#a371f7}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{display:flex;align-items:center;gap:14px;padding:10px 16px;background:var(--panel);
border-bottom:1px solid var(--border);position:sticky;top:0;z-index:5}
header h1{font-size:15px;margin:0}.badge{font-size:12px;padding:3px 10px;border-radius:20px;
background:var(--panel2);border:1px solid var(--border);white-space:nowrap}.badge b{color:var(--good)}
.board{max-width:1200px;margin:0 auto;padding:14px;display:flex;flex-direction:column;gap:14px}
.stats{display:flex;gap:12px}
.chip{flex:1;background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:11px 14px;min-width:0}
.chip .k{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.chip .v{font-size:24px;font-weight:500;margin-top:2px;font-variant-numeric:tabular-nums}
.chip .v.good{color:var(--good)}
.card{background:var(--panel);border:1px solid var(--border);border-radius:10px;overflow:hidden}
.card-head{padding:10px 14px;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
cursor:pointer;user-select:none;display:flex;align-items:center;gap:8px;border-bottom:1px solid var(--border)}
.card-head::before{content:'▾';font-size:10px;color:var(--muted)}
.card.collapsed .card-head::before{content:'▸'}
.card.collapsed .card-head{border-bottom:none}
.card.collapsed .card-body{display:none}
.card-head .ht{font-size:11px;color:#6b7686;margin-left:auto;text-transform:none;letter-spacing:0}
.card-body{padding:12px 14px}
.row2{display:flex;gap:14px}.row2 .card{flex:1;min-width:0}
.run{display:flex;height:max(460px,70vh)}
.sesslist{width:236px;flex:0 0 auto;overflow:auto;padding:8px;border-right:1px solid var(--border)}
.streampane{flex:1;min-width:0;display:flex;flex-direction:column;background:#0a0e14}
.streamhead{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);padding:9px 12px 6px}
.stream{flex:1;overflow:auto;padding:0 12px 12px}
.sess{padding:8px 10px;border-radius:8px;border:1px solid var(--border);cursor:pointer;background:var(--panel2);margin-bottom:8px}
.sess:last-child{margin-bottom:0}
.sess.sel{border-color:var(--accent)}.sess .role{font-weight:600;text-transform:capitalize}
.sess .role.worker{color:var(--accent)}.sess .role.director{color:var(--tool)}.sess .role.critic{color:var(--bad)}
.sess .meta{font-size:12px;color:var(--muted);margin-top:2px}
.ev{margin-bottom:10px;border-radius:8px;padding:8px 11px;white-space:pre-wrap;word-break:break-word;max-height:300px;overflow:auto}
.ev.user{background:#11233b;border:1px solid #1f3a5f}.ev.text{background:var(--panel2)}
.ev.tool{background:#1a1430;border:1px solid #3a2a5a;font-family:ui-monospace,Menlo,monospace;font-size:12.5px}
.ev.tool .tn{color:var(--tool);font-weight:600}.ev.result{background:#10161d;border:1px solid var(--border);color:var(--muted);font-family:ui-monospace,Menlo,monospace;font-size:12px}
.ev .lbl{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);display:block;margin-bottom:3px}
.ev .lbl .tm{text-transform:none;letter-spacing:0;color:#6b7686;font-weight:400;float:right}
.tablewrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:12px}th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--border);white-space:nowrap}
th{color:var(--muted);position:sticky;top:0;background:var(--panel)}td.num{text-align:right;font-variant-numeric:tabular-nums}
tr.best td{background:rgba(63,185,80,.13)}pre.dir{white-space:pre-wrap;font-size:12px;margin:0;
max-height:320px;overflow:auto}
.empty{color:var(--muted);font-style:italic;padding:16px;text-align:center}
.chartbox{position:relative;height:300px}
</style></head><body>
<header><h1>🧪 <span id="labName">leanlab</span></h1>
<span class="badge" id="objBadge">objective · —</span>
<span class="badge" id="usageBadge">session · —</span>
<span style="flex:1"></span><span class="badge" id="clock">—</span></header>
<div class="board">
<div class="stats" id="stats"></div>
<section class="card" data-panel="run"><div class="card-head" onclick="toggleFold('run')">Sessions &amp; live stream</div>
<div class="card-body" style="padding:0"><div class="run">
<div class="sesslist" id="sessions"></div>
<div class="streampane"><div class="streamhead" id="streamTitle">Live stream</div>
<div class="stream" id="stream"><div class="empty">Waiting…</div></div></div>
</div></div></section>
<section class="card" data-panel="progress"><div class="card-head" onclick="toggleFold('progress')">Progress</div>
<div class="card-body"><div class="chartbox" id="chart"></div></div></section>
<section class="card" data-panel="results"><div class="card-head" onclick="toggleFold('results')">Results</div>
<div class="card-body"><div class="tablewrap" id="results"></div></div></section>
<div class="row2">
<section class="card" data-panel="critics"><div class="card-head" onclick="toggleFold('critics')">🔴 Critics</div>
<div class="card-body"><pre class="dir" id="critique">—</pre></div></section>
<section class="card" data-panel="director"><div class="card-head" onclick="toggleFold('director')">🧭 Director</div>
<div class="card-body"><pre class="dir" id="directions">—</pre></div></section></div></div>
<script>
let selected=null,follow=true,es=null,lastState=null,wantJump=false;
const $=id=>document.getElementById(id);
function esc(s){const d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML}
function fmtK(n){if(n==null)return'';return n>=1000?(n/1000).toFixed(n>=10000?0:1)+'k':''+n}
function shortModel(m){return m?m.replace(/^claude-/,'').replace(/-\d{8}$/,''):''}
function relTime(s){s=Math.round(s);if(s<10)return'just now';if(s<60)return'under a min ago';
if(s<3600)return Math.floor(s/60)+' min ago';if(s<86400)return Math.floor(s/3600)+' hr ago';return Math.floor(s/86400)+' day ago'}
function evMeta(ev){const t=ev.ts?new Date(ev.ts).toLocaleTimeString():'';const b=[];
if(ev.model)b.push(shortModel(ev.model));if(ev.in_tok!=null||ev.out_tok!=null)b.push(fmtK(ev.in_tok)+'→'+fmtK(ev.out_tok)+' tok');
if(ev.cost)b.push('$'+ev.cost.toFixed(4));if(ev.dur!=null)b.push('⏱ '+ev.dur+'s');
const r=(t||'')+(b.length?' · '+b.join(' · '):'');return r?`<span class="tm">${r}</span>`:''}

const DEFAULT_COLLAPSED={};
function foldState(){try{return JSON.parse(localStorage.getItem('leanlab.folds'))||{}}catch(e){return {}}}
function applyFolds(){const f=foldState();document.querySelectorAll('.card[data-panel]').forEach(c=>{
const k=c.dataset.panel;const col=(k in f)?f[k]:!!DEFAULT_COLLAPSED[k];c.classList.toggle('collapsed',col)})}
function toggleFold(k){const c=document.querySelector('.card[data-panel="'+k+'"]');if(!c)return;
const now=!c.classList.contains('collapsed');c.classList.toggle('collapsed',now);
const f=foldState();f[k]=now;localStorage.setItem('leanlab.folds',JSON.stringify(f))}

function connect(){if(es)es.close();es=new EventSource('/api/stream'+(selected?'?id='+encodeURIComponent(selected):''));
es.addEventListener('open',()=>$('clock').textContent='● streaming');
es.addEventListener('error',()=>$('clock').textContent='○ reconnecting…');
es.addEventListener('state',e=>onState(JSON.parse(e.data)));
es.addEventListener('session',e=>renderStream(JSON.parse(e.data)))}

function chip(k,v,good){return `<div class="chip"><div class="k">${k}</div><div class="v${good?' good':''}">${v}</div></div>`}
function renderStats(st){$('stats').innerHTML=
chip('best '+(st.direction==='min'?'↓':'↑'),st.best==null?'—':st.best,true)+
chip('latest',st.latest==null?'—':st.latest)+
chip('experiments',st.results.length)+
chip('total cost','$'+(st.total_cost||0).toFixed(2))}

function onState(st){lastState=st;
$('labName').textContent=st.lab;
$('objBadge').textContent='objective · '+st.direction+' '+st.metric;
if(follow&&st.active&&st.active!==selected){selected=st.active;wantJump=true;connect();return}
if(!selected&&st.active){selected=st.active;wantJump=true;connect();return}
renderStats(st);renderSessions();renderResults(st);renderChart(st);
$('critique').textContent=st.critique||'—';$('directions').textContent=st.directions||'—'}

function renderSessions(){if(!lastState)return;const now=Date.now()/1000;
$('sessions').innerHTML=lastState.sessions.map(s=>{const run=(now-s.mtime)<15;
const sel=s.id===selected?' sel':'';const art=s.artifact?' · '+s.artifact.replace('experiments/',''):'';
const cost=s.cost?' · $'+s.cost.toFixed(2):'';const when=run?'running':relTime(now-s.mtime);
return `<div class="sess${sel}" onclick="pick('${s.id}')"><div class="role ${s.role}">${s.role}${run?' ●':''}</div>
<div class="meta">${s.events} msgs${cost} · ${when}${art}</div></div>`}).join('')||'<div class="empty">No sessions</div>'}

function renderResults(st){const rows=st.results.slice();if(!rows.length){$('results').innerHTML='<div class="empty">No results yet</div>';return}
const skip=new Set(['tag','best_so_far','notes','ts','experiment_file']);
const cols=[];rows.forEach(r=>Object.keys(r).forEach(k=>{if(!skip.has(k)&&!cols.includes(k))cols.push(k)}));
const m=st.metric;rows.sort((a,b)=>{const x=parseFloat(a[m]),y=parseFloat(b[m]);
if(isNaN(x))return 1;if(isNaN(y))return -1;return st.direction==='min'?x-y:y-x});
let h='<table><tr><th>experiment</th>'+cols.map(c=>`<th>${esc(c)}</th>`).join('')+'</tr>';
for(const r of rows){const isB=parseFloat(r[m])===st.best;
h+=`<tr class="${isB?'best':''}"><td title="${esc(r.notes)}">${esc((r.experiment_file||'').replace('experiments/',''))}</td>`+
cols.map(c=>{let v=r[c];if(v!=null&&typeof v==='object')v=JSON.stringify(v);return `<td class="num">${esc(v)}</td>`}).join('')+'</tr>'}
$('results').innerHTML=h+'</table>'}

let chartObj=null;
function renderChart(st){const box=$('chart'),m=st.metric,rows=st.results||[];
const pts=rows.map(r=>parseFloat(r[m])),valid=pts.filter(v=>!isNaN(v));
if(typeof Chart==='undefined'){box.innerHTML='<div class="empty">chart library unavailable (offline?)</div>';chartObj=null;return}
if(!valid.length){box.innerHTML='<div class="empty">No data yet</div>';chartObj=null;return}
if(!box.querySelector('canvas')){box.innerHTML='<canvas></canvas>';chartObj=null}
const labels=rows.map((r,i)=>(r.experiment_file||('#'+(i+1))).replace('experiments/','').replace(/\.py$/,''));
let best=null;const bestLine=pts.map(v=>{if(!isNaN(v))best=best==null?v:(st.direction==='min'?Math.min(best,v):Math.max(best,v));return best});
const ptCol=pts.map(v=>v===st.best?'#3fb950':'#58a6ff'),ptR=pts.map(v=>v===st.best?6:4);
if(chartObj){const d=chartObj.data;d.labels=labels;d.datasets[0].data=pts;
d.datasets[0].pointBackgroundColor=ptCol;d.datasets[0].pointBorderColor=ptCol;d.datasets[0].pointRadius=ptR;
d.datasets[1].data=bestLine;chartObj.options.scales.y.title.text=st.direction+' '+m;chartObj.update();return}
chartObj=new Chart(box.querySelector('canvas').getContext('2d'),{type:'line',
data:{labels,datasets:[
{label:m,data:pts,borderColor:'#58a6ff',backgroundColor:'#58a6ff',pointBackgroundColor:ptCol,pointBorderColor:ptCol,pointRadius:ptR,pointHoverRadius:7,tension:.25,spanGaps:true},
{label:'best so far',data:bestLine,borderColor:'#3fb950',borderDash:[6,4],pointRadius:0,stepped:true}]},
options:{responsive:true,maintainAspectRatio:false,animation:{duration:300},interaction:{mode:'index',intersect:false},
plugins:{legend:{labels:{color:'#8b949e',boxWidth:12,usePointStyle:true}},
tooltip:{callbacks:{label:c=>c.dataset.label+': '+c.formattedValue}}},
scales:{x:{ticks:{color:'#8b949e',maxRotation:0,autoSkip:true,autoSkipPadding:12},grid:{color:'#222b36'}},
y:{ticks:{color:'#8b949e'},grid:{color:'#222b36'},title:{display:true,text:st.direction+' '+m,color:'#8b949e'}}}}})}

function renderStream(s){$('streamTitle').textContent=(s.meta.role||'session')+' · '+(s.id||'').slice(0,8)+(s.running?' · LIVE':'');
const box=$('stream');const atB=box.scrollHeight-box.scrollTop-box.clientHeight<80;
box.innerHTML=s.events.map(ev=>{const m=evMeta(ev);
if(ev.kind==='tool')return `<div class="ev tool"><span class="lbl">tool ${m}</span><span class="tn">${esc(ev.name)}</span> → ${esc(ev.text)}</div>`;
if(ev.kind==='result')return `<div class="ev result"><span class="lbl">result ${m}</span>${esc(ev.text)}</div>`;
if(ev.kind==='user')return `<div class="ev user"><span class="lbl">prompt ${m}</span>${esc(ev.text)}</div>`;
return `<div class="ev text"><span class="lbl">assistant ${m}</span>${esc(ev.text)}</div>`}).join('')||'<div class="empty">No messages yet…</div>';
const tt=s.totals;if(tt&&tt.turns)$('usageBadge').innerHTML='session · <b>'+fmtK(tt.in+tt.out)+'</b> tok · <b>$'+tt.cost.toFixed(3)+'</b>';
if(wantJump||atB){box.scrollTop=box.scrollHeight;wantJump=false}}

function pick(id){selected=id;follow=false;wantJump=true;connect()}
applyFolds();setInterval(renderSessions,20000);connect();
</script></body></html>"""


_DASH = None  # the Dashboard, set in main()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError, TimeoutError):
            pass

    def _send(self, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _sse(self, event, payload):
        self.wfile.write(f"event: {event}\ndata: {payload}\n\n".encode())
        self.wfile.flush()

    def stream(self, sid):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        last_sig = last_mt = None
        last_ping = 0.0
        try:
            while True:
                st = _DASH.build_state()
                sig = (tuple((s["id"], round(s["mtime"], 2), s["running"]) for s in st["sessions"]),
                       st["active"], st["best"], hash(st["directions"]), hash(st["critique"]),
                       len(st["results"]))
                if sig != last_sig:
                    self._sse("state", json.dumps(st)); last_sig = sig
                if sid:
                    p = _DASH.transcript_dir() / f"{sid}.jsonl"
                    mt = p.stat().st_mtime if p.exists() else None
                    if mt != last_mt:
                        self._sse("session", json.dumps(_DASH.session_payload(sid))); last_mt = mt
                if time.time() - last_ping > 15:
                    self.wfile.write(b": ping\n\n"); self.wfile.flush(); last_ping = time.time()
                time.sleep(1)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def do_GET(self):
        route = urlparse(self.path)
        try:
            if route.path == "/":
                self._send(PAGE, "text/html; charset=utf-8")
            elif route.path == "/api/stream":
                self.stream(parse_qs(route.query).get("id", [""])[0])
            elif route.path == "/api/state":
                self._send(json.dumps(_DASH.build_state()))
            elif route.path == "/api/session":
                self._send(json.dumps(_DASH.session_payload(parse_qs(route.query).get("id", [""])[0])))
            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001
            try:
                self.send_error(500, str(exc))
            except OSError:
                pass

    def log_message(self, *a):
        pass


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def main():
    global _DASH
    p = argparse.ArgumentParser(description="leanlab dashboard")
    p.add_argument("--lab", required=True)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-open", action="store_true")
    args = p.parse_args()
    lab = Path(args.lab).resolve()
    if not (lab / "lab.json").exists():
        print(f"ERROR: no lab.json in {lab}", file=sys.stderr)
        sys.exit(1)
    _DASH = Dashboard(lab)
    url = f"http://127.0.0.1:{args.port}"
    print(f"leanlab monitor: {url}  (lab: {lab.name})")
    if not args.no_open:
        webbrowser.open(url)
    try:
        QuietServer(("127.0.0.1", args.port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
