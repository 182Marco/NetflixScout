"""Renders schema.mmd (Mermaid ER) and schema.html (one self-contained file) from `introspect()` output. Pure functions.

The HTML carries the full structure as JSON in <script id="schema-data">; the page is drawn from that JSON by a small script
with no external library. A test compares the embedded JSON and the Mermaid text with a fresh introspection of the database.
"""
from __future__ import annotations

import json
import re
from html import escape
from typing import Any

_MERMAID_BAD = re.compile(r'["\n\r]')


def mermaid(info: dict[str, Any]) -> str:
    s = info["structure"]
    lines = [
        "%% Generated from the SQLite schema by cinema_db/harness/schema/generate.py: do not edit.",
        f"%% schema_version={s['schema_version']} structure_digest={info['structure_digest']}",
        "erDiagram",
    ]
    for t in s["tables"]:
        lines.append(f"    {t['name']} {{")
        for c in t["columns"]:
            keys = []
            if c["pk"]:
                keys.append("PK")
            if c["fk"]:
                keys.append("FK")
            if c["unique"] and not c["pk"]:
                keys.append("UK")
            key = (" " + ", ".join(keys)) if keys else ""
            doc = _MERMAID_BAD.sub(" ", (c["doc"] or "")).strip()
            lines.append(f"        {(c['type'] or 'ANY')} {c['name']}{key}" + (f' "{doc}"' if doc else ""))
        lines.append("    }")
    for r in s["relationships"]:
        left = "|o" if r["optional"] else "||"
        right = "o|" if r["cardinality"] == "one_to_one" else "o{"
        label = ", ".join(r["child_columns"])
        lines.append(f'    {r["parent"]} {left}--{right} {r["child"]} : "{label}"')
    return "\n".join(lines) + "\n"


def html(info: dict[str, Any]) -> str:
    payload = {"structure": info["structure"], "structure_digest": info["structure_digest"], "counts": info["counts"], "sources": info["sources"]}
    data = json.dumps(payload, sort_keys=True, ensure_ascii=False).replace("</", "<\\/")
    return _TEMPLATE.replace("__DATA__", data).replace("__TITLE__", escape("Cinema database schema")).replace("__DIGEST__", info["structure_digest"][:16])


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="schema-digest" content="__DIGEST__">
<title>__TITLE__</title>
<style>
:root{--bg:#f6f7f9;--panel:#fff;--ink:#1c2230;--muted:#5d677a;--line:#d5dae3;--accent:#2b6cb0;--hl:#fff3c4;--pk:#b7791f;--fk:#2b6cb0;--uq:#2f855a;--g1:#e8f0fb;--g2:#eaf6ee;--g3:#fdf1e3;--g4:#f3ecfa;--g5:#fbeaea;--g6:#e6f4f6;--g7:#eef0f3}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#10141b;--panel:#171d27;--ink:#e6e9ef;--muted:#9aa5b8;--line:#2a3342;--accent:#6aa9f0;--hl:#4a3f12;--pk:#e0b04a;--fk:#6aa9f0;--uq:#5fc08a;--g1:#172338;--g2:#16281f;--g3:#2d2417;--g4:#251d33;--g5:#331c1c;--g6:#15292d;--g7:#1c2230}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
header{padding:16px;border-bottom:1px solid var(--line);background:var(--panel);position:sticky;top:0;z-index:5}
h1{font-size:18px;margin:0 0 4px}.sub{color:var(--muted);font-size:12px}
.bar{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px;align-items:center}
input[type=search]{padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);min-width:220px}
button,.chip{font:inherit;border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:999px;padding:3px 10px;cursor:pointer}
.chip[aria-pressed=true]{background:var(--accent);color:#fff;border-color:var(--accent)}
main{display:grid;grid-template-columns:minmax(0,1fr) 560px;gap:0}
@media (max-width:1100px){main{grid-template-columns:1fr}#detail{position:static;max-height:none}}
#canvas{position:relative;padding:16px;overflow:auto}
#lines{position:absolute;left:0;top:0;pointer-events:none;overflow:visible}
.cols{display:flex;flex-wrap:wrap;gap:16px 18px;align-items:flex-start}
.col{display:flex;flex-direction:column;gap:10px;width:228px}
.col h2{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:0 0 2px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;overflow:hidden;cursor:pointer}
.card.dim{opacity:.25}.card.sel{outline:2px solid var(--accent)}.card.rel{background:var(--hl)}
.card h3{margin:0;padding:5px 8px;font-size:13px;font-family:ui-monospace,Menlo,monospace}
.card .n{float:right;color:var(--muted);font-weight:400;font-size:11px}
.card ul{list-style:none;margin:0;padding:3px 8px 6px;font-size:12px;font-family:ui-monospace,Menlo,monospace}
.card li{display:flex;gap:6px;white-space:nowrap}.card li .t{color:var(--muted);margin-left:auto;padding-left:8px}
.b{font-size:10px;font-weight:700;padding:0 4px;border-radius:3px;color:#fff}.b.pk{background:var(--pk)}.b.fk{background:var(--fk)}.b.uq{background:var(--uq)}
.g-provenance h3{background:var(--g7)}.g-vocabulary h3{background:var(--g6)}.g-entity h3{background:var(--g1)}.g-work h3{background:var(--g2)}.g-people h3{background:var(--g3)}.g-award h3{background:var(--g4)}.g-view h3{background:var(--g5)}
#detail{border-left:1px solid var(--line);background:var(--panel);padding:14px;position:sticky;top:96px;max-height:calc(100vh - 96px);overflow:auto}
#detail h2{margin:0 0 4px;font-size:16px;font-family:ui-monospace,Menlo,monospace}#detail h4{margin:14px 0 4px;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
table{border-collapse:collapse;width:100%;font-size:12px}th,td{border-bottom:1px solid var(--line);padding:3px 6px;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{color:var(--muted);font-weight:600;white-space:nowrap}td.mono{white-space:nowrap;overflow-wrap:normal}
code,.mono{font-family:ui-monospace,Menlo,monospace}pre{white-space:pre-wrap;background:var(--bg);padding:8px;border-radius:6px;font-size:11px}
a.link{color:var(--accent);cursor:pointer;text-decoration:underline}.muted{color:var(--muted)}
.legend{display:flex;gap:10px;flex-wrap:wrap;font-size:12px;color:var(--muted)}
</style>
</head>
<body>
<header>
<h1>Cinema database schema</h1>
<div class="sub" id="meta"></div>
<div class="bar">
<input type="search" id="q" placeholder="Search table, column or description" aria-label="Search">
<span id="chips"></span>
<button id="all" aria-pressed="false">Show all relations</button>
<button id="views" aria-pressed="false">Public views</button>
</div>
<div class="legend" style="margin-top:8px"><span><span class="b pk">PK</span> primary key</span><span><span class="b fk">FK</span> foreign key (click to follow)</span><span><span class="b uq">UQ</span> unique</span><span>Click a table for columns, keys, indexes, checks and relations.</span></div>
</header>
<main><div id="canvas"><svg id="lines" width="0" height="0"></svg><div class="cols" id="cols"></div></div><aside id="detail"></aside></main>
<script type="application/json" id="schema-data">__DATA__</script>
<script>
"use strict";
const D=JSON.parse(document.getElementById('schema-data').textContent),S=D.structure;
const tables=Object.fromEntries(S.tables.map(t=>[t.name,t])),views=Object.fromEntries(S.views.map(v=>[v.name,v]));
const state={sel:null,all:false,showViews:false,groups:new Set(Object.keys(S.groups)),q:''};
const $=(s,r=document)=>r.querySelector(s),el=(t,a={},...k)=>{const e=document.createElement(t);for(const[x,y]of Object.entries(a))x==='class'?e.className=y:x.startsWith('on')?e.addEventListener(x.slice(2),y):e.setAttribute(x,y);for(const c of k)e.append(c);return e};
const total=S.tables.reduce((a,t)=>a+(D.counts[t.name]||0),0);
$('#meta').textContent=`schema v${S.schema_version} · ${S.tables.length} tables · ${S.views.length} public views · ${S.relationships.length} foreign keys · ${S.many_to_many.length} many-to-many · digest ${D.structure_digest.slice(0,12)} · ${total} rows`;
function relsOf(n){return S.relationships.filter(r=>r.child===n||r.parent===n)}
function related(n){const s=new Set([n]);relsOf(n).forEach(r=>{s.add(r.child);s.add(r.parent)});return s}
function visible(t){if(!state.groups.has(t.group))return false;if(!state.q)return true;const q=state.q.toLowerCase();return t.name.includes(q)||(t.doc||'').toLowerCase().includes(q)||t.columns.some(c=>c.name.includes(q)||(c.doc||'').toLowerCase().includes(q))}
function card(t,isView){
 const keyish=isView?t.columns.slice(0,6):t.columns.filter(c=>c.pk||c.fk).concat(t.columns.filter(c=>!c.pk&&!c.fk).slice(0,3));
 const ul=el('ul');for(const c of keyish){const li=el('li',{},c.name);if(!isView){if(c.pk)li.append(el('span',{class:'b pk'},'PK'));if(c.fk)li.append(el('span',{class:'b fk'},'FK'));if(c.unique&&!c.pk)li.append(el('span',{class:'b uq'},'UQ'))}li.append(el('span',{class:'t'},c.type||''));ul.append(li)}
 if(t.columns.length>keyish.length)ul.append(el('li',{class:'muted'},`… ${t.columns.length-keyish.length} more`));
 const c=el('div',{class:`card g-${t.group}`,id:'c-'+t.name,onclick:()=>select(t.name)},el('h3',{},t.name,el('span',{class:'n'},isView?'view':String(D.counts[t.name]??''))),ul);return c}
function render(){
 const cols=$('#cols');cols.replaceChildren();
 for(const g of S.group_order){const label=S.groups[g];
  if(g==='view'&&!state.showViews)continue;
  const items=(g==='view'?S.views:S.tables.filter(t=>t.group===g)).filter(t=>g==='view'||visible(t));
  if(!items.length||!state.groups.has(g))continue;
  const col=el('div',{class:'col'},el('h2',{},label));items.forEach(t=>col.append(card(t,g==='view')));cols.append(col)}
 applySel();
}
function applySel(){
 const rel=state.sel&&tables[state.sel]?related(state.sel):null;
 document.querySelectorAll('.card').forEach(c=>{const n=c.id.slice(2);c.classList.toggle('sel',n===state.sel);c.classList.toggle('rel',!!rel&&rel.has(n)&&n!==state.sel);c.classList.toggle('dim',!!rel&&!rel.has(n))});
 drawLines();detail();
}
function drawLines(){
 const svg=$('#lines'),cv=$('#canvas');svg.replaceChildren();svg.setAttribute('width',cv.scrollWidth);svg.setAttribute('height',cv.scrollHeight);
 const rels=state.all?S.relationships:(state.sel?relsOf(state.sel):[]);const base=cv.getBoundingClientRect();
 for(const r of rels){const a=$('#c-'+r.child),b=$('#c-'+r.parent);if(!a||!b||r.child===r.parent)continue;
  const A=a.getBoundingClientRect(),B=b.getBoundingClientRect();const ax=A.left+A.width/2<B.left+B.width/2?A.right:A.left,bx=A.left+A.width/2<B.left+B.width/2?B.left:B.right;
  const ay=A.top+16,by=B.top+16,x1=ax-base.left+cv.scrollLeft,y1=ay-base.top+cv.scrollTop,x2=bx-base.left+cv.scrollLeft,y2=by-base.top+cv.scrollTop,mx=(x1+x2)/2;
  const p=document.createElementNS('http://www.w3.org/2000/svg','path');p.setAttribute('d',`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`);p.setAttribute('fill','none');p.setAttribute('stroke',r.optional?'#8aa4c8':'#2b6cb0');p.setAttribute('stroke-width',state.all?'1':'1.6');if(r.optional)p.setAttribute('stroke-dasharray','4 3');p.setAttribute('opacity',state.all?'.45':'.9');svg.append(p);
  const d=document.createElementNS('http://www.w3.org/2000/svg','circle');d.setAttribute('cx',x1);d.setAttribute('cy',y1);d.setAttribute('r',3);d.setAttribute('fill','#2b6cb0');svg.append(d)}
}
function select(n){state.sel=n;history.replaceState(null,'','#t='+n);if(!document.getElementById('c-'+n)){if(views[n])state.showViews=true;render()}else applySel();$('#c-'+n)?.scrollIntoView({block:'nearest',inline:'nearest'})}
function badge(c){return[c.pk?'PK':'',c.fk?'FK':'',c.unique&&!c.pk?'UQ':''].filter(Boolean).join(' ')}
function detail(){
 const d=$('#detail');d.replaceChildren();const n=state.sel;
 if(!n){d.append(el('h2',{},'How to read this'),el('p',{class:'muted'},'Every table has a primary key, typed columns, real foreign keys and a source for each row. Works (films, series, seasons, episodes, source novels) share one table; names, identifiers and provenance hang off a common entity key. Click a table to see everything about it.'),
  el('h4',{},'Many-to-many links'),...S.many_to_many.map(m=>el('div',{},el('a',{class:'link',onclick:()=>select(m.a)},m.a),' ↔ ',el('a',{class:'link',onclick:()=>select(m.b)},m.b),' via ',el('a',{class:'link',onclick:()=>select(m.via)},m.via))),
  el('h4',{},'Sources in this database'),sourcesTable());return}
 const t=tables[n]||views[n];const isView=!!views[n];
 d.append(el('h2',{},t.name),el('div',{class:'muted'},t.doc||''));
 if(isView){d.append(el('h4',{},'Reads base tables'),el('div',{},...t.reads.flatMap(r=>[el('a',{class:'link',onclick:()=>select(r)},r),' '])))}
 const ct=el('table');ct.append(el('tr',{},...['Column','Type',isView?'':'Keys','Null','Description'].map(h=>el('th',{},h))));
 for(const c of t.columns){const fk=c.fk?el('a',{class:'link',onclick:()=>select(c.fk.table)},` → ${c.fk.table}.${c.fk.column}`):'';ct.append(el('tr',{},el('td',{class:'mono'},c.name),el('td',{class:'mono'},c.type||''),el('td',{},isView?'':badge(c),fk),el('td',{},isView?'':(c.not_null?'NOT NULL':'null')),el('td',{},c.doc||'')))}
 d.append(el('h4',{},`Columns (${t.columns.length})`),ct);
 if(isView){d.append(el('h4',{},'Definition'),el('pre',{},t.sql));return}
 const pk=t.primary_key.join(', ');d.append(el('h4',{},'Keys'),el('div',{class:'mono'},`PRIMARY KEY (${pk})`));
 t.unique.filter(u=>u.join()!==t.primary_key.join()).forEach(u=>d.append(el('div',{class:'mono'},`UNIQUE (${u.join(', ')})`)));
 t.foreign_keys.forEach(f=>d.append(el('div',{class:'mono'},`FOREIGN KEY (${f.columns.join(', ')}) → `,el('a',{class:'link',onclick:()=>select(f.ref_table)},f.ref_table),`(${f.ref_columns.join(', ')})`)));
 if(t.checks.length){d.append(el('h4',{},'Checks'));t.checks.forEach(c=>d.append(el('div',{class:'mono'},c)))}
 if(t.indexes.length){d.append(el('h4',{},'Indexes'));t.indexes.forEach(i=>d.append(el('div',{class:'mono'},`${i.unique?'UNIQUE ':''}${i.name} (${i.columns.join(', ')})${i.partial?' · partial':''}`)))}
 const out=S.relationships.filter(r=>r.parent===n&&r.child!==n),inn=S.relationships.filter(r=>r.child===n);
 d.append(el('h4',{},'Relations'));
 inn.forEach(r=>d.append(el('div',{},`${r.child_columns.join(', ')} → `,el('a',{class:'link',onclick:()=>select(r.parent)},r.parent),` · ${r.cardinality==='one_to_one'?'one-to-one':'many-to-one'}${r.optional?' (optional)':''}${r.kind==='subtype'?' · subtype of':''}`)));
 out.forEach(r=>d.append(el('div',{},el('a',{class:'link',onclick:()=>select(r.child)},r.child),` (${r.child_columns.join(', ')}) → this · ${r.cardinality==='one_to_one'?'one-to-one':'one-to-many'}`)));
 S.many_to_many.filter(m=>m.a===n||m.b===n||m.via===n).forEach(m=>d.append(el('div',{},'many-to-many: ',m.a,' ↔ ',m.b,' via ',m.via)));
 const vs=S.views.filter(v=>v.reads.includes(n));if(vs.length){d.append(el('h4',{},'Read by public views'));vs.forEach(v=>d.append(el('a',{class:'link',onclick:()=>select(v.name)},v.name+' ')))}
 d.append(el('h4',{},'Rows'),el('div',{},String(D.counts[n]??0)),el('h4',{},'DDL'),el('pre',{},t.sql));
}
function sourcesTable(){
 if(!D.sources.length)return el('div',{class:'muted'},'No source registered yet (schema-only build). Each source row records licence, usage scope, attribution and snapshot hash; every fact row points to one.');
 const t=el('table');t.append(el('tr',{},...['Name','Kind','Licence','Scope','Attribution'].map(h=>el('th',{},h))));
 D.sources.forEach(s=>t.append(el('tr',{},el('td',{},s.name),el('td',{},s.kind),el('td',{},s.license),el('td',{},s.usage_scope),el('td',{},s.attribution_required?'required':'no'))));return t}
const chips=$('#chips');S.group_order.filter(g=>g!=='view').map(g=>[g,S.groups[g]]).forEach(([g,l])=>{const b=el('button',{class:'chip','aria-pressed':'true',onclick:()=>{state.groups.has(g)?state.groups.delete(g):state.groups.add(g);b.setAttribute('aria-pressed',state.groups.has(g));render()}},l);chips.append(b)});
$('#q').addEventListener('input',e=>{state.q=e.target.value;render()});
$('#all').addEventListener('click',e=>{state.all=!state.all;e.target.setAttribute('aria-pressed',state.all);drawLines()});
$('#views').addEventListener('click',e=>{state.showViews=!state.showViews;e.target.setAttribute('aria-pressed',state.showViews);state.groups.add('view');render()});
window.addEventListener('resize',drawLines);$('#canvas').addEventListener('scroll',drawLines);
const m=location.hash.match(/t=([a-z_]+)/);if(m){state.sel=m[1];if(views[m[1]]){state.showViews=true;$('#views').setAttribute('aria-pressed','true')}}
if(location.hash.includes('all')){state.all=true;$('#all').setAttribute('aria-pressed','true')}
render();
</script>
</body>
</html>
"""
