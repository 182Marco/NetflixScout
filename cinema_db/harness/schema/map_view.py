"""The graphical MAP of the schema (CSS and JavaScript) that `render.html` adds to schema.html.

Pure text, no logic of its own about the schema: the script draws from the same JSON the page already embeds (tables, foreign keys, cardinalities,
junction tables, views), which `introspect.py` reads from the SQLite file. No external library, no network: SVG built with the DOM.

What it offers: every table as a node and every foreign key as an edge with ER cardinality symbols (| one, o zero, crow's foot many); a deterministic
force layout; pan (drag the background), zoom (wheel, buttons, + - 0 keys), drag a node; search (tables, columns, descriptions); click a table to
highlight its keys and neighbours, dim the rest and expand its key columns; junction tables, subtype links, optional keys and self references are
drawn differently; the detail panel is shared with the card view.
"""
from __future__ import annotations

CSS = r"""
#map{position:relative;height:calc(100vh - 150px);min-height:520px;overflow:hidden;background:var(--bg);touch-action:none}
@media (max-width:1100px){#map{height:70vh}}
#mapsvg{width:100%;height:100%;display:block;cursor:grab;user-select:none}#mapsvg.panning{cursor:grabbing}
#mapbar{position:absolute;left:12px;top:12px;display:flex;gap:6px;flex-wrap:wrap;z-index:2;align-items:center}
#mapbar button{background:var(--panel)}#mapbar .hint{color:var(--muted);font-size:12px;background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:3px 10px}
#maplegend{position:absolute;left:12px;bottom:12px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px 10px;font-size:11px;color:var(--muted);max-width:360px;line-height:1.7;z-index:2}
#maplegend svg{vertical-align:middle;margin-right:4px}
.node{cursor:pointer}.node rect{stroke:var(--line);stroke-width:1.2}.node text{font-family:ui-monospace,Menlo,monospace;fill:var(--ink);pointer-events:none}
.node .t{font-size:12px;font-weight:700}.node .s{font-size:10px;fill:var(--muted)}.node .c{font-size:10.5px}.node .c .k{font-weight:700}
.node.g-provenance rect{fill:var(--g7)}.node.g-vocabulary rect{fill:var(--g6)}.node.g-entity rect{fill:var(--g1)}.node.g-work rect{fill:var(--g2)}.node.g-people rect{fill:var(--g3)}.node.g-award rect{fill:var(--g4)}.node.g-view rect{fill:var(--g5);stroke-dasharray:4 3}
.node.kind-junction rect{stroke:#d9822b;stroke-width:2.4}.node.kind-fts rect{stroke-dasharray:2 2}
.node.sel rect{stroke:var(--accent);stroke-width:3}.node.rel rect{stroke:var(--accent);stroke-width:2}.node.match rect{stroke:#d69e2e;stroke-width:3}.node.dim{opacity:.18}
.edge{fill:none;stroke:#7f8ea8;stroke-width:1.3}.edge.optional{stroke-dasharray:5 3}.edge.kind-junction{stroke:#d9822b}.edge.kind-subtype{stroke:#8b5cf6}.edge.kind-reads{stroke:#c05656;stroke-dasharray:2 4}
.edge.hl{stroke-width:2.6;stroke:var(--accent)}.edge.hl.kind-junction{stroke:#d9822b}.edge.hl.kind-subtype{stroke:#8b5cf6}.edge.dim{opacity:.08}
.elabel{font:10.5px ui-monospace,Menlo,monospace;fill:var(--ink);paint-order:stroke;stroke:var(--bg);stroke-width:3px;pointer-events:none;display:none}
.elabel.on{display:block}#mapbar button[aria-pressed=true]{background:var(--accent);color:#fff;border-color:var(--accent)}.mk{stroke:var(--muted);fill:none;stroke-width:1.3}.mkfill{fill:var(--panel)}
"""

JS = r"""
// ---------------- map view (pure SVG; drawn from the embedded structure only) ----------------
const NS='http://www.w3.org/2000/svg';
const mp={nodes:new Map(),edges:[],k:1,tx:0,ty:0,labels:false,source:false,key:'',drag:null,pan:null,moved:false};
const hasCounts=Object.values(D.counts).some(v=>v>0);
const sv=(t,a={},...kids)=>{const e=document.createElementNS(NS,t);for(const[x,y]of Object.entries(a))e.setAttribute(x,y);for(const c of kids)e.append(c);return e};
function mapModel(){
 const nodes=S.tables.filter(t=>state.groups.has(t.group)).map(t=>({name:t.name,group:t.group,kind:t.virtual?'fts':(t.junction?'junction':'table'),rows:D.counts[t.name]||0}));
 if(state.showViews)for(const v of S.views)nodes.push({name:v.name,group:'view',kind:'view',rows:0});
 const names=new Set(nodes.map(n=>n.name)),edges=[];
 S.relationships.forEach((r,i)=>{if(names.has(r.child)&&names.has(r.parent))edges.push({id:'fk'+i,child:r.child,parent:r.parent,cols:r.child_columns.join(', '),pcols:r.parent_columns.join(', '),card:r.cardinality,optional:r.optional,kind:r.kind,prov:r.parent==='source'})});
 if(state.showViews)for(const v of S.views)for(const t of v.reads)if(names.has(t))edges.push({id:'rd-'+v.name+'-'+t,child:v.name,parent:t,cols:'reads',pcols:'',card:'reads',optional:true,kind:'reads'});
 return{nodes,edges};
}
function layoutMap(nodes,edges){
 let seed=20261106;const rnd=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296};
 const groups=[...new Set(nodes.map(n=>n.group))],C={};
 groups.forEach((g,i)=>{const a=2*Math.PI*i/groups.length-Math.PI/2;C[g]={x:430*Math.cos(a),y:330*Math.sin(a)}});
 nodes.forEach(n=>{n.w=Math.max(124,n.name.length*7.6+28);n.h=38;const c=C[n.group];n.x=c.x+(rnd()-.5)*220;n.y=c.y+(rnd()-.5)*220;n.vx=0;n.vy=0});
 const by=new Map(nodes.map(n=>[n.name,n])),deg=new Map();
 const links=edges.filter(e=>e.child!==e.parent&&!e.prov&&by.has(e.child)&&by.has(e.parent)); // provenance links (every table points at `source`) would pull everything to the middle: not part of the layout
 links.forEach(e=>{deg.set(e.child,(deg.get(e.child)||0)+1);deg.set(e.parent,(deg.get(e.parent)||0)+1)});
 const N=nodes.length,STEPS=520;
 for(let it=0;it<STEPS;it++){
  const cool=1-it/STEPS,t=.35+.65*cool;
  for(let i=0;i<N;i++)for(let j=i+1;j<N;j++){const a=nodes[i],b=nodes[j];let dx=b.x-a.x,dy=b.y-a.y,d2=dx*dx+dy*dy+.01,d=Math.sqrt(d2);
   const f=26000/d2;dx/=d;dy/=d;a.vx-=dx*f;a.vy-=dy*f;b.vx+=dx*f;b.vy+=dy*f;
   const ox=(a.w+b.w)/2+30-Math.abs(b.x-a.x),oy=(a.h+b.h)/2+26-Math.abs(b.y-a.y);
   if(ox>0&&oy>0){const push=Math.min(ox,oy)*.5;if(ox<oy){const s=b.x>=a.x?1:-1;a.vx-=s*push;b.vx+=s*push}else{const s=b.y>=a.y?1:-1;a.vy-=s*push;b.vy+=s*push}}}
  for(const e of links){const a=by.get(e.child),b=by.get(e.parent);const dx=b.x-a.x,dy=b.y-a.y,d=Math.sqrt(dx*dx+dy*dy)+.01;
   const rest=(deg.get(e.parent)>9||deg.get(e.child)>9)?300:210,f=(d-rest)*.035;a.vx+=dx/d*f;a.vy+=dy/d*f;b.vx-=dx/d*f;b.vy-=dy/d*f}
  for(const n of nodes){const c=C[n.group];n.vx+=(c.x-n.x)*.006-n.x*.002;n.vy+=(c.y-n.y)*.006-n.y*.002;
   n.vx*=.82;n.vy*=.82;const sp=Math.hypot(n.vx,n.vy),cap=40*t;if(sp>cap){n.vx*=cap/sp;n.vy*=cap/sp}n.x+=n.vx;n.y+=n.vy}
 }
 const cx=nodes.reduce((s,n)=>s+n.x,0)/N,cy=nodes.reduce((s,n)=>s+n.y,0)/N;nodes.forEach(n=>{n.x-=cx;n.y-=cy});
}
function rectPoint(n,tx,ty){const dx=tx-n.x,dy=ty-n.y;if(!dx&&!dy)return{x:n.x,y:n.y};const s=Math.min((n.w/2)/(Math.abs(dx)||1e-9),(n.h/2)/(Math.abs(dy)||1e-9));return{x:n.x+dx*s,y:n.y+dy*s}}
function edgePath(e,idx,total){
 const a=mp.nodes.get(e.parent),b=mp.nodes.get(e.child);
 if(a===b){const x=a.x+a.w/2,y=a.y-a.h/2;return{d:`M${x-26},${y} C${x-26},${y-52} ${x+46},${y-52} ${x+46},${y+8} L${x},${y+8}`,mx:x+46,my:y-38}}
 const off=(idx-(total-1)/2)*54,mx0=(a.x+b.x)/2,my0=(a.y+b.y)/2,dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy)||1,cx=mx0-dy/d*off,cy=my0+dx/d*off;
 const p=rectPoint(a,off?cx:b.x,off?cy:b.y),q=rectPoint(b,off?cx:a.x,off?cy:a.y);
 return{d:off?`M${p.x},${p.y} Q${cx},${cy} ${q.x},${q.y}`:`M${p.x},${p.y} L${q.x},${q.y}`,mx:off?(p.x+2*cx+q.x)/4:(p.x+q.x)/2,my:off?(p.y+2*cy+q.y)/4:(p.y+q.y)/2}
}
function mapDefs(){
 const m=(id,body)=>sv('marker',{id,viewBox:'-14 -7 16 14',refX:'0',refY:'0',markerWidth:'16',markerHeight:'14',markerUnits:'userSpaceOnUse',orient:'auto'},...body);
 const P=(d,c='mk')=>sv('path',{d,class:c});
 return sv('defs',{},
  m('m-one',[P('M-9,-6 L-9,6')]),
  m('m-zeroone',[P('M-9,-6 L-9,6'),sv('circle',{cx:'-16',cy:'0',r:'3.4',class:'mk mkfill'})]),
  m('m-zeromany',[P('M-12,0 L0,-6 M-12,0 L0,0 M-12,0 L0,6'),sv('circle',{cx:'-17',cy:'0',r:'3.4',class:'mk mkfill'})]));
}
function buildMap(){
 const svg=$('#mapsvg');svg.replaceChildren(mapDefs());
 const model=mapModel();mp.key=model.nodes.map(n=>n.name).join('|');mp.nodes=new Map(model.nodes.map(n=>[n.name,n]));mp.edges=model.edges;
 layoutMap(model.nodes,model.edges);
 const vp=sv('g',{id:'vp'}),eg=sv('g',{id:'eg'}),lg=sv('g',{id:'lg'}),ng=sv('g',{id:'ng'});vp.append(eg,lg,ng);svg.append(vp);
 const pair=new Map();model.edges.forEach(e=>{const k=[e.child,e.parent].sort().join('>');(pair.get(k)||pair.set(k,[]).get(k)).push(e)});
 for(const list of pair.values())list.forEach((e,i)=>{e.idx=i;e.total=list.length});
 for(const e of model.edges){
  const p=sv('path',{class:`edge kind-${e.kind}${e.optional&&e.kind!=='reads'?' optional':''}`,id:'e-'+e.id,'data-child':e.child,'data-parent':e.parent,'data-cols':e.cols,'data-parent-cols':e.pcols,'data-card':e.card,'data-optional':String(e.optional),'data-kind':e.kind});
  if(e.kind!=='reads'){p.setAttribute('marker-start',`url(#${e.optional?'m-zeroone':'m-one'})`);p.setAttribute('marker-end',`url(#${e.card==='one_to_one'?'m-zeroone':'m-zeromany'})`)}
  const t=sv('title');t.textContent=e.kind==='reads'?`${e.child} reads ${e.parent}`:`${e.child}.${e.cols} → ${e.parent}.${e.pcols} · ${e.card==='one_to_one'?'one-to-one':'many-to-one'}${e.optional?' · optional':''}${e.kind==='subtype'?' · subtype':''}`;p.append(t);
  p.addEventListener('click',ev=>{ev.stopPropagation();select(e.child)});eg.append(p);
  lg.append(sv('text',{class:'elabel',id:'l-'+e.id,'text-anchor':'middle'}));
  e.el=p;e.lab=lg.lastChild;e.lab.textContent=e.kind==='reads'?'reads':`${e.cols} → ${e.parent}.${e.pcols}`;
 }
 for(const n of model.nodes){
  const g=sv('g',{class:`node g-${n.group} kind-${n.kind}`,id:'n-'+n.name,'data-table':n.name,'data-kind':n.kind});
  const r=sv('rect',{rx:'9',ry:'9'}),t=sv('text',{class:'t','text-anchor':'middle'}),s=sv('text',{class:'s','text-anchor':'middle'});
  t.textContent=n.name;const rows=hasCounts?` · ${n.rows.toLocaleString()} rows`:'';s.textContent=n.kind==='view'?'public view':n.kind==='junction'?`⇄ junction${rows}`:n.kind==='fts'?'FTS5 index':(hasCounts?`${n.rows.toLocaleString()} rows`:(tables[n.name]?.primary_key||[]).length?`PK ${tables[n.name].primary_key.join(', ')}`:'no primary key');
  g.append(r,t,s);const tt=sv('title');tt.textContent=(tables[n.name]||views[n.name]).doc||n.name;g.append(tt);
  g.addEventListener('pointerdown',ev=>{ev.stopPropagation();g.setPointerCapture(ev.pointerId);mp.drag={n,sx:ev.clientX,sy:ev.clientY,ox:n.x,oy:n.y};mp.moved=false});
  g.addEventListener('pointermove',ev=>{if(!mp.drag||mp.drag.n!==n)return;const dx=(ev.clientX-mp.drag.sx)/mp.k,dy=(ev.clientY-mp.drag.sy)/mp.k;if(Math.abs(dx)+Math.abs(dy)>3/mp.k)mp.moved=true;if(mp.moved){n.x=mp.drag.ox+dx;n.y=mp.drag.oy+dy;paintMap()}});
  g.addEventListener('pointerup',ev=>{if(mp.drag&&mp.drag.n===n&&!mp.moved)select(n.name);mp.drag=null});
  g.addEventListener('dblclick',()=>{select(n.name);focusNode(n.name,1.6)});
  ng.append(g);n.el=g;n.rect=r;n.t=t;n.s=s;
 }
 paintMap();fitMap();applyMap();
}
function expandedHeight(n){const t=tables[n.name];if(!t||n.name!==state.sel)return 38;return 38+14*Math.min(keyCols(t).length,12)+(keyCols(t).length?6:0)}
function keyCols(t){return t.columns.filter(c=>c.pk||c.fk)}
function paintMap(){
 for(const n of mp.nodes.values()){
  const sel=n.name===state.sel&&tables[n.name];n.h=sel?expandedHeight(n):38;
  n.el.setAttribute('transform',`translate(${n.x},${n.y})`);
  n.rect.setAttribute('x',-n.w/2);n.rect.setAttribute('y',-n.h/2);n.rect.setAttribute('width',n.w);n.rect.setAttribute('height',n.h);
  n.t.setAttribute('y',-n.h/2+16);n.s.setAttribute('y',-n.h/2+30);
  n.el.querySelectorAll('.c').forEach(x=>x.remove());
  if(sel){let y=-n.h/2+46;for(const c of keyCols(tables[n.name]).slice(0,12)){const tx=sv('text',{class:'c',x:-n.w/2+8,y});
   const k=sv('tspan',{class:'k'});k.textContent=(c.pk?'PK ':'')+(c.fk?'FK ':'');tx.append(k,document.createTextNode(c.name+(c.fk?` → ${c.fk.table}`:'')));n.el.append(tx);y+=14}}
 }
 for(const e of mp.edges){const g=edgePath(e,e.idx,e.total);e.el.setAttribute('d',g.d);e.lab.setAttribute('x',g.mx);e.lab.setAttribute('y',g.my-3)}
 $('#vp')?.setAttribute('transform',`translate(${mp.tx},${mp.ty}) scale(${mp.k})`);
}
function applyMap(){
 if(!$('#mapsvg')||!mp.nodes.size)return;
 const sel=state.sel&&mp.nodes.has(state.sel)?state.sel:null,rel=sel?related(sel):null,q=state.q.trim().toLowerCase();
 const matches=q?new Set(S.tables.concat(S.views).filter(t=>t.name.includes(q)||(t.doc||'').toLowerCase().includes(q)||t.columns.some(c=>c.name.includes(q)||(c.doc||'').toLowerCase().includes(q))).map(t=>t.name)):null;
 for(const n of mp.nodes.values()){n.el.classList.toggle('sel',n.name===sel);n.el.classList.toggle('rel',!!rel&&rel.has(n.name)&&n.name!==sel);
  n.el.classList.toggle('match',!!matches&&matches.has(n.name));
  n.el.classList.toggle('dim',rel?!rel.has(n.name):(!!matches&&!matches.has(n.name)))}
 for(const e of mp.edges){const inc=sel&&(e.child===sel||e.parent===sel),off=e.prov&&!mp.source&&!inc;e.el.style.display=off?'none':'';e.el.classList.toggle('hl',!!inc);e.el.classList.toggle('dim',!!sel&&!inc);e.lab.classList.toggle('on',!off&&(mp.labels||!!inc))}
 const c=$('#mapcount'),nprov=mp.edges.filter(e=>e.prov).length;if(c)c.textContent=matches?`${[...matches].filter(m=>mp.nodes.has(m)).length} match`:`${mp.nodes.size} nodes · ${mp.edges.length} foreign keys (${nprov} to source)`;
 paintMap();
 const top=sel&&mp.nodes.get(sel);if(top)$('#ng').append(top.el);
}
function fitMap(){
 const svg=$('#mapsvg');if(!svg||!mp.nodes.size)return;const W=svg.clientWidth||900,H=svg.clientHeight||600;
 let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;for(const n of mp.nodes.values()){x0=Math.min(x0,n.x-n.w/2);x1=Math.max(x1,n.x+n.w/2);y0=Math.min(y0,n.y-n.h/2);y1=Math.max(y1,n.y+n.h/2)}
 mp.k=Math.max(.12,Math.min(1.4,Math.min(W/(x1-x0+90),H/(y1-y0+90))));mp.tx=W/2-mp.k*(x0+x1)/2;mp.ty=H/2-mp.k*(y0+y1)/2;paintMap();
}
function zoomAt(f,px,py){const svg=$('#mapsvg'),r=svg.getBoundingClientRect();px=px??r.width/2;py=py??r.height/2;const k=Math.max(.1,Math.min(3.5,mp.k*f));mp.tx=px-(px-mp.tx)*k/mp.k;mp.ty=py-(py-mp.ty)*k/mp.k;mp.k=k;paintMap()}
function focusNode(name,k){const n=mp.nodes.get(name),svg=$('#mapsvg');if(!n)return;mp.k=k||Math.max(mp.k,1);mp.tx=svg.clientWidth/2-mp.k*n.x;mp.ty=svg.clientHeight/2-mp.k*n.y;paintMap()}
function mapRefresh(){
 if(!$('#mapsvg')||state.mode!=='map')return;
 const key=mapModel().nodes.map(n=>n.name).join('|');
 if(key!==mp.key||!mp.nodes.size)buildMap();else applyMap();
}
function setMode(m){
 state.mode=m;document.body.dataset.mode=m;$('#canvas').style.display=m==='cards'?'':'none';$('#map').style.display=m==='map'?'':'none';
 $('#mode-map').setAttribute('aria-pressed',m==='map');$('#mode-cards').setAttribute('aria-pressed',m==='cards');$('#all').style.display=m==='cards'?'':'none';
 const h=location.hash.replace(/[#&]?view=[a-z]+/,'');history.replaceState(null,'',(h&&h!=='#'?h+'&':'#')+'view='+m);
 if(m==='map')requestAnimationFrame(()=>{if($('#mapsvg').clientWidth){if(!mp.nodes.size||mapModel().nodes.map(n=>n.name).join('|')!==mp.key)buildMap();else{applyMap()}}});else drawLines();
}
(function initMap(){
 const svg=$('#mapsvg');
 svg.addEventListener('pointerdown',ev=>{if(ev.target.closest('.node'))return;mp.pan={sx:ev.clientX,sy:ev.clientY,tx:mp.tx,ty:mp.ty,moved:false};svg.setPointerCapture(ev.pointerId);svg.classList.add('panning')});
 svg.addEventListener('pointermove',ev=>{if(!mp.pan)return;const dx=ev.clientX-mp.pan.sx,dy=ev.clientY-mp.pan.sy;if(Math.abs(dx)+Math.abs(dy)>3)mp.pan.moved=true;mp.tx=mp.pan.tx+dx;mp.ty=mp.pan.ty+dy;paintMap()});
 svg.addEventListener('pointerup',()=>{if(mp.pan&&!mp.pan.moved&&state.sel){state.sel=null;history.replaceState(null,'',location.hash.replace(/[#&]?t=[a-z_0-9]+/,'')||'#');applySel()}mp.pan=null;svg.classList.remove('panning')});
 svg.addEventListener('wheel',ev=>{ev.preventDefault();const r=svg.getBoundingClientRect();zoomAt(Math.exp(-ev.deltaY*(ev.ctrlKey?.01:.0016)),ev.clientX-r.left,ev.clientY-r.top)},{passive:false});
 $('#zin').addEventListener('click',()=>zoomAt(1.25));$('#zout').addEventListener('click',()=>zoomAt(1/1.25));$('#zfit').addEventListener('click',fitMap);
 $('#zrelayout').addEventListener('click',()=>{mp.key='';buildMap()});
 $('#zlabels').addEventListener('click',e=>{mp.labels=!mp.labels;e.target.setAttribute('aria-pressed',mp.labels);applyMap()});
 $('#zsource').addEventListener('click',e=>{mp.source=!mp.source;e.target.setAttribute('aria-pressed',mp.source);applyMap()});
 $('#mode-map').addEventListener('click',()=>setMode('map'));$('#mode-cards').addEventListener('click',()=>setMode('cards'));
 window.addEventListener('keydown',ev=>{if(state.mode!=='map'||ev.target.tagName==='INPUT')return;if(ev.key==='+'||ev.key==='=')zoomAt(1.25);else if(ev.key==='-')zoomAt(1/1.25);else if(ev.key==='0')fitMap();else if(ev.key==='Escape'){state.sel=null;applySel()}});
 window.addEventListener('resize',()=>{if(state.mode==='map')fitMap()});
 $('#q').addEventListener('keydown',ev=>{if(ev.key==='Enter'&&state.mode==='map'){const q=state.q.trim().toLowerCase();const hit=[...mp.nodes.keys()].find(n=>n.includes(q))||[...mp.nodes.values()].find(n=>$('#n-'+n.name)?.classList.contains('match'))?.name;if(hit){select(hit);focusNode(hit,1.3)}}});
})();
"""

BODY = r"""<div id="map"><svg id="mapsvg" role="img" aria-label="Map of the database tables and their foreign keys"></svg>
<div id="mapbar"><button id="zin" title="Zoom in (+)">＋</button><button id="zout" title="Zoom out (-)">－</button><button id="zfit" title="Fit the whole schema (0)">Fit</button><button id="zrelayout" title="Compute the layout again">Re-layout</button><button id="zlabels" aria-pressed="false" title="Show the columns of every foreign key">Edge labels</button><button id="zsource" aria-pressed="false" title="Every table has a source_id key to the source table: hidden by default, shown when you select a table">Source links</button><span class="hint" id="mapcount"></span><span class="hint">drag: pan · wheel: zoom · drag a table to move it · click: highlight its keys</span></div>
<div id="maplegend"><div><svg width="38" height="12"><path d="M2,6 L30,6" class="edge" stroke="#7f8ea8"/></svg>foreign key (child → parent), <b>1</b> bar = one, <b>o</b> = zero, crow's foot = many</div><div><svg width="38" height="12"><path d="M2,6 L30,6" class="edge optional" stroke="#7f8ea8"/></svg>dashed: optional key (can be empty)</div><div><svg width="38" height="12"><path d="M2,6 L30,6" class="edge kind-junction"/></svg>orange: junction table (many-to-many)</div><div><svg width="38" height="12"><path d="M2,6 L30,6" class="edge kind-subtype"/></svg>purple: subtype of <code>entity</code> (one-to-one)</div><div>keys to <code>source</code> (provenance of every row) are hidden until you select a table or press <b>Source links</b></div></div>
</div>"""
