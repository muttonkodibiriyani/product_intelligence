/* Product Intelligence · analytics mockup. Illustrative sample data only. */
const PRESETS=[
 {id:'lead',name:{en:'Leadership summary',ar:'ملخص القيادة'},preset:true,w:[['kpiIndex',3,1],['kpiMatched',3,1],['kpiPromo',3,1],['kpiStock',3,1],['index',8,3],['feed',4,3],['gapdist',6,3],['promoheat',6,3],['matrix',12,4]]},
 {id:'price',name:{en:'Pricing desk',ar:'مكتب التسعير'},preset:true,w:[['kpiIndex',3,1],['kpiGap',3,1],['kpiMatched',3,1],['kpiLaunch',3,1],['index',12,3],['gapdist',5,3],['gaps',7,3],['ladder',12,4],['packsize',12,3]]},
 {id:'promo',name:{en:'Promotions desk',ar:'مكتب العروض'},preset:true,w:[['kpiPromo',4,1],['kpiIndex',4,1],['kpiGap',4,1],['promocal',12,3],['promoheat',6,3],['gaps',6,3]]},
 {id:'range',name:{en:'Range & availability',ar:'التشكيلة والتوفر'},preset:true,w:[['kpiMatched',4,1],['kpiStock',4,1],['kpiLaunch',4,1],['matrix',8,4],['feed',4,4],['avail',6,3],['stockouts',6,3],['shades',12,3]]}
];
const S={lang:'en',route:'dashboard',param:null,range:[89,DAYS-1],f:{brand:new Set(),cat:new Set(),band:new Set(),shade:new Set()},ret:new Set(['u','s']),sel:null,
 pins:['h0','h2','h4'],views:[],viewId:'lead',layout:null,edit:false,dirty:false,pop:null,wmenu:null,drill:null,preview:'live',loading:false,
 ex:{sort:'gap',mode:'grid',limit:36,q:''},tbl:{},gapMode:'exact',heatR:'s',idxMode:'rel',feedType:'all',ask:0,cite:null,gal:0,crumb:null,saveAs:false,addOpen:false,toast:null};
const LS='pi.mockup.views.v2';
try{const v=JSON.parse(localStorage.getItem(LS)||'null');if(Array.isArray(v))S.views=v}catch(e){}
const allViews=()=>[...PRESETS,...S.views];
const viewById=id=>allViews().find(v=>v.id===id)||PRESETS[0];
S.layout=viewById(S.viewId).w.map(x=>x.slice());

const t=k=>{const v=I18N[S.lang][k];return v!==undefined?v:(I18N.en[k]!==undefined?I18N.en[k]:k)};
const L=o=>o&&typeof o==='object'&&('en' in o)?(o[S.lang]||o.en):o;
const AR_MON=['يناير','فبراير','مارس','أبريل','مايو','يونيو','يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر'],EN_MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const fmtD=d=>`${d.getUTCDate()} ${(S.lang==='ar'?AR_MON:EN_MON)[d.getUTCMonth()]}`;
const fmtN=(v,dp=0)=>v==null||isNaN(v)?'—':v.toLocaleString('en-US',{minimumFractionDigits:dp,maximumFractionDigits:dp});
const aed=(v,dp=0)=>v==null?'—':(S.lang==='ar'?`${fmtN(v,dp)} د.إ`:`AED ${fmtN(v,dp)}`);
const pct=(v,dp=1,sign=true)=>v==null||isNaN(v)?'—':`${sign&&v>0?'+':''}${v.toFixed(dp)}%`;
const RN=k=>k==='u'?t('ulta'):t('sephora');
const RC=k=>k==='u'?C_U:C_S;
const $=s=>document.querySelector(s);
const median=a=>{if(!a.length)return null;const s=[...a].sort((x,y)=>x-y),m=s.length>>1;return s.length%2?s[m]:(s[m-1]+s[m])/2};
const ICON={
 check:'<svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
 mail:'<svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true"><rect x="2" y="3.5" width="12" height="9" rx="2" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M2.5 4.5L8 9l5.5-4.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>',
 info:'<svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.6" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M8 7.3v4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><circle cx="8" cy="4.9" r=".95" fill="currentColor"/></svg>',
 shield:'<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.8l5 2v3.6c0 3.2-2.2 5.4-5 6.8-2.8-1.4-5-3.6-5-6.8V3.8z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M6 8h4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
 clock:'<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M8 4.8V8l2.2 1.4" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linecap="round"/></svg>',
 dash:'<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.4" stroke-dasharray="2.4 2"/><path d="M5.5 8h5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
 filter:'<svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="M2 4h12M4.5 8h7M7 12h2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
 eye:'<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z" fill="none" stroke="currentColor" stroke-width="1.3"/><circle cx="8" cy="8" r="2" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>',
 grip:'<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><g fill="currentColor"><circle cx="4.5" cy="3" r="1.2"/><circle cx="9.5" cy="3" r="1.2"/><circle cx="4.5" cy="7" r="1.2"/><circle cx="9.5" cy="7" r="1.2"/><circle cx="4.5" cy="11" r="1.2"/><circle cx="9.5" cy="11" r="1.2"/></g></svg>',
 more:'<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><g fill="currentColor"><circle cx="3.5" cy="8" r="1.4"/><circle cx="8" cy="8" r="1.4"/><circle cx="12.5" cy="8" r="1.4"/></g></svg>',
 x:'<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
 pin:'<svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="M10.5 1.8l3.7 3.7-2.2.8-2.4 2.4.3 3.1-1.3 1.3-2.6-2.6L2.6 13.9l-.5-.5 3.4-3.4-2.6-2.6 1.3-1.3 3.1.3 2.4-2.4z" fill="currentColor"/></svg>',
 chev:'<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 3.5l3 3 3-3" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/></svg>',
 plus:'<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M6 1.5v9M1.5 6h9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
 arrow:'<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" class="flipx"><path d="M4 2l4 4-4 4" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round"/></svg>',
 cal:'<svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><rect x="2" y="3" width="12" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3" stroke="currentColor" stroke-width="1.4"/></svg>'
};

/* ---------- filtering & context ---------- */
function curPrice(p,k,d){if(!p.d[k])return null;for(let i=d;i>=0;i--){const v=p.d[k].price[i];if(v!=null)return v}return null}
function minCur(p,d){const v=[...S.ret].map(k=>curPrice(p,k,d)).filter(x=>x!=null);return v.length?Math.min(...v):null}
function listedInRange(p,k,a,b){return !!(p.d[k]&&p.first[k]<=b&&p.last[k]>=a)}
function passes(p,skip,a,b){const f=S.f;
  if(skip!=='brand'&&f.brand.size&&!f.brand.has(p.brand))return false;
  if(skip!=='cat'&&f.cat.size&&!f.cat.has(p.cat))return false;
  if(skip!=='shade'&&f.shade.size&&!p.fam.some(x=>f.shade.has(x)))return false;
  if(skip!=='ret'&&![...S.ret].some(k=>listedInRange(p,k,a,b)))return false;
  if(skip!=='band'&&f.band.size){const m=minCur(p,b);if(m==null||![...f.band].some(x=>{const B=BANDS.find(y=>y[0]===x);return m>=B[1]&&m<=B[2]}))return false}
  if(skip!=='sel'&&S.sel&&!S.sel.ids.has(p.id))return false;
  return true}
let CTX=null;
function ctx(){if(CTX)return CTX;const [a,b]=S.range;const Pall=PRODUCTS.filter(p=>passes(p,'sel',a,b));const P=S.sel?Pall.filter(p=>S.sel.ids.has(p.id)):Pall;
  const c={a,b,P,Pall,src:k=>S.sel&&S.sel.src===k?Pall:P,U:S.ret.has('u'),Sx:S.ret.has('s')};
  c.forced=S.preview==='empty'?[]:null;if(c.forced){c.P=[];c.Pall=[];c.src=()=>[]}
  CTX=c;return c}
function indexSeries(P,a,b){const basket=P.filter(p=>p.sameSize&&p.first.u<=a&&p.first.s<=a&&p.last.u>=b&&p.last.s>=b);
  const rel=new Array(DAYS).fill(null),u=new Array(DAYS).fill(null),s=new Array(DAYS).fill(null);if(!basket.length)return {rel,u,s,n:0,basket};
  const su=new Array(DAYS).fill(0),ss=new Array(DAYS).fill(0);
  basket.forEach(p=>{for(let d=0;d<DAYS;d++){const x=p.d.u.price[d],y=p.d.s.price[d];if(x!=null&&y!=null){su[d]+=x;ss[d]+=y}}});
  for(let d=0;d<DAYS;d++)if(su[d])rel[d]=+(ss[d]/su[d]*100).toFixed(2);
  for(let d=a;d<=b;d++){if(su[a])u[d]=+(su[d]/su[a]*100).toFixed(2);if(ss[a])s[d]=+(ss[d]/ss[a]*100).toFixed(2)}
  return {rel,u,s,n:basket.length,basket}}
const gapOf=(p,d,mode)=>{if(mode==='unit'){const x=unitAt(p,'u',d),y=unitAt(p,'s',d);return x!=null&&y!=null?(x-y)/y*100:null}
  if(!p.sameSize)return null;const x=priceAt(p,'u',d),y=priceAt(p,'s',d);return x!=null&&y!=null?(x-y)/y*100:null};
const GAP_BINS=[[-1e9,-15],[-15,-10],[-10,-5],[-5,-2],[-2,-1e-9],[0,0],[1e-9,2],[2,5],[5,10],[10,15],[15,1e9]];
const GAP_LAB=['≤−15','−15','−10','−5','−2','0','+2','+5','+10','+15','≥15'];
const binOf=g=>GAP_BINS.findIndex(([lo,hi])=>g===0?lo===0&&hi===0:(g>lo&&g<=hi)||(lo===-1e9&&g<=hi)||(hi===1e9&&g>lo));
function promoWindows(p,k,a,b){return p.promos.filter(x=>x.r===k&&x.b>=a&&x.a<=b)}
const FREQ=['1','2','3','4+'],DEPTHB=['<15%','15–24%','25–34%','35–44%','45%+'];
const depthIdx=v=>v<15?0:v<25?1:v<35?2:v<45?3:4;
function launchesIn(P,a,b){const ev=[];P.forEach(p=>RR.forEach(k=>{if(!p.d[k]||!S.ret.has(k))return;if(p.first[k]>a&&p.first[k]<=b&&!heldAt(p,k,p.first[k]-1))ev.push({p,k,type:'new',d:p.first[k]});if(p.last[k]<DAYS-1&&p.last[k]>=a&&p.last[k]<b&&!heldAt(p,k,p.last[k]+1))ev.push({p,k,type:'gone',d:p.last[k]+1})}));return ev.sort((x,y)=>y.d-x.d)}
function outSince(p,k,d){let i=d;while(i>0&&stockAt(p,k,i-1)===3)i--;return i}

/* ---------- small components ---------- */
const stockTag=(st)=>{const k=['na','in','low','out','unk'][st||0];return `<span class="stock st-${k}"><i></i>${t('stock')[k]}</span>`};
const gapSpan=g=>g==null?'<span class="muted">—</span>':`<span class="num ${g>0.05?'gap-pos':g<-0.05?'gap-neg':'muted'}">${pct(g)}</span>`;
/* The retailer's image when the snapshot has one; the browser rendering when it has none or it fails to load. */
const pic=p=>p.img?`<img class="pphoto" src="${esc(p.img)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" width="200" height="200"><span hidden>${productSVG(p,'')}</span>`:productSVG(p,'');
document.addEventListener('error',e=>{const i=e.target;if(i&&i.classList&&i.classList.contains('pphoto')){i.hidden=true;const f=i.nextElementSibling;if(f)f.hidden=false}},true);
const thumb=p=>`<span class="thumb">${pic(p)}</span>`;
const pcell=(p,sub)=>`<div class="pcell">${thumb(p)}<div class="pcx"><div class="bn">${esc(p.brand)}</div><div class="pn">${esc(p.name)}</div>${sub?`<div class="muted xs">${sub}</div>`:''}</div></div>`;
const pinBtn=(p,label)=>{const on=S.pins.includes(p.id);return `<button class="iconbtn pinb${on?' on':''}" data-pin="${p.id}" aria-pressed="${on}" aria-label="${on?t('unpin'):t('pin')}: ${esc(p.brand+' '+p.name)}" ${tipAttr([on?t('unpin'):t('pin')])}>${ICON.pin}${label?`<span>${on?t('pinned'):t('pin')}</span>`:''}</button>`};
const evBtn=(p,k,label)=>`<button class="linkbtn" data-ev="${p.id}" data-r="${k}">${label||t('evidence')}</button>`;
const seg=(name,opts,cur)=>`<div class="seg" role="group">${opts.map(([v,l])=>`<button data-seg="${name}" data-v="${v}" aria-pressed="${cur===v}">${l}</button>`).join('')}</div>`;
const legendUS=(dash)=>`<div class="legend">${S.ret.has('u')?`<span><i style="background:${C_U}"></i>${t('ulta')}</span>`:''}${S.ret.has('s')?`<span><i class="${dash?'dash':''}" style="background:${C_S}"></i>${t('sephora')}</span>`:''}</div>`;
function emptyState(msg){return `<div class="wempty"><b>${t('emptyT')}</b><span>${msg||t('emptyP')}</span><button class="btn sm" data-reset>${t('resetFilters')}</button></div>`}
function table(id,cols,rows,o={}){
  const st=S.tbl[id]||(S.tbl[id]={sort:o.sort||null,dir:o.dir||-1,q:'',limit:o.limit||8});
  let r=rows;if(st.q){const q=st.q.toLowerCase();r=r.filter(x=>(o.text?o.text(x):'').toLowerCase().includes(q))}
  if(st.sort){const c=cols.find(c=>c.k===st.sort);if(c&&c.v)r=[...r].sort((x,y)=>{const a=c.v(x),b=c.v(y);if(a==null)return 1;if(b==null)return -1;return (typeof a==='string'?a.localeCompare(b):a-b)*st.dir})}
  const shown=r.slice(0,st.limit);
  return `${o.filter!==false?`<div class="tfilter"><input type="search" id="tf-${id}" data-tq="${id}" value="${esc(st.q)}" placeholder="${t('filterRows')}" aria-label="${t('filterRows')}"><span class="muted xs num">${t('rowsOf')(shown.length,r.length)}</span></div>`:''}
  <table class="data"><thead><tr>${cols.map(c=>`<th class="${c.align==='r'?'r':''}" ${c.v?`aria-sort="${st.sort===c.k?(st.dir>0?'ascending':'descending'):'none'}"`:''}>${c.v?`<button class="th" data-sort="${id}" data-k="${c.k}">${c.label}<span class="sa">${st.sort===c.k?(st.dir>0?'↑':'↓'):'↕'}</span></button>`:c.label}</th>`).join('')}</tr></thead>
  <tbody>${shown.length?shown.map(x=>`<tr class="${o.rowProd?'click':''}" ${o.rowProd?`data-prod="${o.rowProd(x)}" tabindex="0"`:''}>${cols.map(c=>`<td class="${c.align==='r'?'r num':''}">${c.f(x)}</td>`).join('')}</tr>`).join(''):`<tr><td colspan="${cols.length}" class="muted" style="text-align:center;padding:24px">${t('noRows')}</td></tr>`}</tbody></table>
  ${r.length>shown.length?`<div class="tmore"><button class="linkbtn" data-tmore="${id}">${t('showMore')(Math.min(20,r.length-shown.length))}</button></div>`:''}`}

/* ---------- widgets ---------- */
const ROWH=120,GAP=20;
function mainW(){const m=document.querySelector('.main');return m?Math.max(640,m.clientWidth-64):1100}
function wPx(w){const col=(mainW()-11*GAP)/12;return Math.round(w*col+(w-1)*GAP-34)}
function hPx(h){return h*ROWH+(h-1)*GAP-60}
const W={
 kpiIndex:{kpi:true,drill:'index',minW:2,dw:3,dh:1,title:()=>t('kIndex'),r(c){const ix=indexSeries(c.P,c.a,c.b);const v=ix.rel[c.b],v0=ix.rel[c.a];
   if(v==null)return kpi(t('kIndex'),'—',t('kIndexNone'));return kpi(t('kIndex'),fmtN(v,1),t('kIndexSub'),v0!=null&&c.a<c.b?`${pct(v-v0,1).replace('%','')} ${t('pts')} ${t('vsStart')}`:'',v-v0>0?'up':'down',t('basketN')(ix.n))}},
 kpiGap:{kpi:true,drill:'gap',minW:2,dw:3,dh:1,title:()=>t('kGap'),r(c){const g=c.P.map(p=>gapOf(p,c.b,'exact')).filter(x=>x!=null);const m=median(g);
   return kpi(t('kGap'),m==null?'—':pct(m),`${t('kGapSub')} · n=${g.length}`,g.length?`${t('ultaCheaper')} ${g.filter(x=>x<0).length} · ${t('same')} ${g.filter(x=>x===0).length} · ${t('sephoraCheaper')} ${g.filter(x=>x>0).length}`:'')}},
 kpiMatched:{kpi:true,drill:'matched',minW:2,dw:3,dh:1,title:()=>t('kMatched'),r(c){const both=c.P.filter(p=>listedAt(p,'u',c.b)&&listedAt(p,'s',c.b)).length,u=c.P.filter(p=>listedAt(p,'u',c.b)).length,s=c.P.filter(p=>listedAt(p,'s',c.b)).length;
   return kpi(t('kMatched'),fmtN(both),t('kMatchedSub')(u,s),`${t('overlap')} ${u+s-both?(both/(u+s-both)*100).toFixed(0):0}%`)}},
 kpiPromo:{kpi:true,drill:'promo',minW:2,dw:3,dh:1,title:()=>t('kPromo'),r(c){const sh=k=>{const L=c.P.filter(p=>listedAt(p,k,c.b));return L.length?L.filter(p=>promoAt(p,k,c.b)).length/L.length*100:null};
   return kpi(t('kPromo'),`${c.U?`${fmtN(sh('u'),0)}%<small>${t('ulta')}</small>`:''} ${c.Sx?`${fmtN(sh('s'),0)}%<small>${t('sephora')}</small>`:''}`,t('kPromoSub'))}},
 kpiStock:{kpi:true,drill:'stock',minW:2,dw:3,dh:1,title:()=>t('kStock'),r(c){const n=k=>c.P.filter(p=>stockAt(p,k,c.b)===3).length,nu=k=>c.P.filter(p=>stockAt(p,k,c.b)===4).length;
   return kpi(t('kStock'),`${c.U?`${n('u')}<small>${t('ulta')}</small>`:''} ${c.Sx?`${n('s')}<small>${t('sephora')}</small>`:''}`,t('kStockSub'),(nu('u')+nu('s'))?`${nu('u')+nu('s')} ${t('notObsShort')}`:'')}},
 kpiLaunch:{kpi:true,drill:'launch',minW:2,dw:3,dh:1,title:()=>t('kLaunch'),r(c){const ev=launchesIn(c.P,c.a,c.b);const n=k=>ev.filter(e=>e.type==='new'&&e.k===k).length;
   return kpi(t('kLaunch'),`${c.U?`${n('u')}<small>${t('ulta')}</small>`:''} ${c.Sx?`${n('s')}<small>${t('sephora')}</small>`:''}`,t('inRange'),`${ev.filter(e=>e.type==='gone').length} ${t('delisted')}`)}},
 index:{minW:5,dw:8,dh:3,title:()=>t('wIndex'),sub:()=>t(S.idxMode==='rel'?'wIndexSubRel':'wIndexSubAbs'),
  act:()=>seg('idxMode',[['rel',t('relative')],['abs',t('eachStart')]],S.idxMode),
  r(c,w,h){const ix=indexSeries(c.P,c.a,c.b);if(!ix.n)return emptyState(t('noBasket'));const W_=wPx(w),H=hPx(h);const ctxH=h>=3?46:0;
   const series=S.idxMode==='rel'?[{name:t('sephoraVsUlta'),color:C_S,vals:ix.rel}]:[c.U&&{name:t('ulta'),color:C_U,vals:ix.u},c.Sx&&{name:t('sephora'),color:C_S,dash:true,vals:ix.s}].filter(Boolean);
   const bands=NOT_OBS.filter(n=>!n.cats).map(n=>({a:n.a,b:n.b,label:L(n.why)}));
   return `<div class="chart">${lineChart({id:'ix-'+w+h,w:W_,h:H-ctxH-26,a:c.a,b:c.b,series,ref:100,fmt:v=>fmtN(v,1),title:t('wIndex'),bands})}</div>
    ${ctxH?`<div class="chart ctxwrap">${contextStrip({id:'ixc-'+w+h,w:W_,vals:ix.rel,a:c.a,b:c.b})}</div>`:''}
    <div class="wfoot">${S.idxMode==='rel'?`<div class="legend"><span><i style="background:${C_S}"></i>${t('sephoraVsUlta')}</span><span><i class="ref"></i>${t('parity')}</span></div>`:legendUS(true)}<span class="muted xs">${t('brushHint')}</span></div>`}},
 gapdist:{minW:4,dw:6,dh:3,title:()=>t('wGapDist'),sub:()=>t(S.gapMode==='exact'?'wGapDistSubExact':'wGapDistSubUnit'),
  act:()=>seg('gapMode',[['exact',t('exactMatch')],['unit',t('perUnit')]],S.gapMode),
  r(c,w,h){const P=c.src('gapdist');const counts=new Array(GAP_BINS.length).fill(0);const gs=[];P.forEach(p=>{const g=gapOf(p,c.b,S.gapMode);if(g==null)return;gs.push(g);counts[binOf(g)]++});
   if(!gs.length)return emptyState(t('noMatched'));
   const sel=S.sel&&S.sel.src==='gapdist'?S.sel.key:null;const cols=GAP_LAB.map((_,i)=>i<5?C_U:i===5?'#B3ADA3':C_S);
   return `<div class="chart">${bars({w:wPx(w),h:hPx(h)-48,cats:GAP_LAB,series:[{name:t('products'),color:C_U,vals:counts}],colors:cols,sel,act:i=>'gap:'+i,title:t('wGapDist'),tipTitle:i=>binLabel(i),tipExtra:t('clickFilter'),maxBar:34})}</div>
   <div class="wfoot"><div class="legend"><span><span class="sw" style="background:${C_U}"></span>${t('ultaCheaper')} · ${gs.filter(g=>g<0).length}</span><span><span class="sw" style="background:#B3ADA3"></span>${t('same')} · ${gs.filter(g=>g===0).length}</span><span><span class="sw" style="background:${C_S}"></span>${t('sephoraCheaper')} · ${gs.filter(g=>g>0).length}</span></div><span class="muted xs">${t('median')} ${pct(median(gs))}</span></div>`}},
 gaps:{minW:5,dw:7,dh:3,title:()=>t('wGaps'),sub:()=>t('wGapsSub'),
  r(c,w,h){const P=c.P.filter(p=>gapOf(p,c.b,'exact')!=null);if(!P.length)return emptyState(t('noMatched'));
   const lim=Math.max(3,Math.floor((hPx(h)-70)/52));if(!S.tbl.gapsW)S.tbl.gapsW={sort:'abs',dir:-1,q:'',limit:lim};else S.tbl.gapsW.limit=Math.max(S.tbl.gapsW.limit,lim);
   return table('gapsW',[
    {k:'p',label:t('product'),f:p=>pcell(p,`${szT(p.size.u,p)}`),v:p=>p.brand+p.name},
    {k:'u',label:t('ulta'),align:'r',f:p=>aed(priceAt(p,'u',c.b)),v:p=>priceAt(p,'u',c.b)},
    {k:'s',label:t('sephora'),align:'r',f:p=>aed(priceAt(p,'s',c.b)),v:p=>priceAt(p,'s',c.b)},
    {k:'abs',label:t('gap'),align:'r',f:p=>gapSpan(gapOf(p,c.b,'exact')),v:p=>Math.abs(gapOf(p,c.b,'exact'))},
    {k:'pin',label:'',f:p=>pinBtn(p)}],P,{text:p=>p.brand+' '+p.name,rowProd:p=>p.id})}},
 ladder:{minW:8,dw:12,dh:4,title:()=>t('wLadder'),sub:()=>t('wLadderSub'),
  r(c,w,h){const P=c.src('ladder');if(!P.length)return emptyState();const cats=CATS.filter(k=>P.some(p=>p.cat===k));const W_=wPx(w),l=132,r=20,rp=r,top=26,lane=14,rowH=lane*2+14;const H=top+cats.length*rowH+34;
   const all=P.flatMap(p=>RR.filter(k=>S.ret.has(k)).map(k=>priceAt(p,k,c.b))).filter(v=>v!=null);if(!all.length)return emptyState();
   const lo=Math.log(Math.max(15,Math.min(...all)*.9)),hi=Math.log(Math.max(...all)*1.1);const x=v=>l+(Math.log(v)-lo)/(hi-lo)*(W_-l-r);
   let s=`<svg viewBox="0 0 ${W_} ${H}" role="img" aria-label="${esc(t('wLadder'))}" class="ladder">`;
   [25,50,100,200,400,800].filter(v=>Math.log(v)>=lo&&Math.log(v)<=hi).forEach(v=>s+=`<line x1="${x(v)}" x2="${x(v)}" y1="${top-6}" y2="${H-30}" stroke="${GRID}"/><text x="${x(v)}" y="${H-16}" font-size="11" text-anchor="middle" fill="${AX}">${v}</text>`);
   s+=`<text x="${l+(W_-l-r)/2}" y="${H-2}" font-size="11" text-anchor="middle" fill="#5B6275" font-weight="600">${esc(t('priceAxis'))}</text><text x="8" y="14" font-size="11" fill="#5B6275" font-weight="600">${esc(t('catAxis'))}</text>`;
   const sel=S.sel&&S.sel.src==='ladder'?S.sel.key:null;
   cats.forEach((k,i)=>{const y0=top+i*rowH;const dim=sel&&sel!==k;
    s+=`<g opacity="${dim?.35:1}"><rect x="0" y="${y0}" width="${l-10}" height="${rowH-8}" rx="6" fill="${sel===k?'#EFEBFB':'transparent'}" class="hit act" data-act="lad:${k}" tabindex="0" role="button" ${tipAttr([t('cat')[k],t('clickFilter')])}/><text x="8" y="${y0+rowH/2}" font-size="11.5" fill="#1E2226" font-weight="600" pointer-events="none">${esc(t('cat')[k])}</text>`;
    RR.filter(r=>S.ret.has(r)).forEach((r,j)=>{const yy=y0+4+j*lane+lane/2;const vals=[];s+=`<line x1="${l}" x2="${W_-rp}" y1="${yy}" y2="${yy}" stroke="#F1F2F6"/>`;
     P.filter(p=>p.cat===k).forEach(p=>{const v=priceAt(p,r,c.b);if(v==null)return;vals.push(v);s+=`<circle cx="${x(v).toFixed(1)}" cy="${yy}" r="4.5" fill="${RC(r)}" fill-opacity=".32" stroke="${RC(r)}" stroke-opacity=".45" stroke-width=".8" class="dot" data-prod="${p.id}" ${tipAttr([p.brand+' · '+p.name,`${RN(r)}: ${aed(v)}`,p.size[r]?`${szT(p.size[r],p)} · ${aed(v/p.size[r],2)}/${p.unit}`:szT(p.size[r],p)])}/>`});
     const m=median(vals);if(m)s+=`<g class="med" data-tip="${esc(`${t('cat')[k]} · ${RN(r)}\n${t('medianL')}: ${aed(m)} · n=${vals.length}`)}" style="pointer-events:all"><rect x="${(x(m)-3).toFixed(1)}" y="${yy-8}" width="6" height="16" rx="3" fill="${RC(r)}" stroke="#fff" stroke-width="1.5"/></g>`});
    s+='</g>'});
   return `<div class="chart">${s}</svg></div><div class="wfoot"><div class="legend">${legendUS().replace(/^<div class="legend">|<\/div>$/g,'')}<span><span class="sw med" aria-hidden="true"></span>${t('medianL')}</span></div><span class="muted xs">${t('ladderHint')}</span></div>`}},
 promocal:{minW:8,dw:12,dh:3,title:()=>t('wPromoCal'),sub:()=>t('wPromoCalSub'),r(c,w,h){return promoCal(c,wPx(w))}},
 promoheat:{minW:4,dw:6,dh:3,title:()=>t('wPromoHeat'),sub:()=>t('wPromoHeatSub'),
  act:()=>seg('heatR',[c0('u'),c0('s')].filter(Boolean),S.heatR),
  r(c,w,h){const k=S.heatR;const P=c.src('promoheat');const vals=FREQ.map(()=>DEPTHB.map(()=>0));const ids=FREQ.map(()=>DEPTHB.map(()=>[]));
   P.forEach(p=>{const ws=promoWindows(p,k,c.a,c.b);if(!ws.length)return;const f=Math.min(3,ws.length-1),d=depthIdx(Math.max(...ws.map(x=>x.pct)));vals[f][d]++;ids[f][d].push(p.id)});
   const tot=vals.flat().reduce((a,b)=>a+b,0);if(!tot)return emptyState(t('noPromos'));
   const sel=S.sel&&S.sel.src==='promoheat'?S.sel.key.split(':').slice(1).map(Number):null;
   const cw=Math.min(96,(wPx(w)-120)/DEPTHB.length),rh=Math.min(44,(hPx(h)-70)/FREQ.length);
   return `<div class="chart">${heatmap({rows:FREQ.map(f=>t('timesN')(f)),cols:DEPTHB,vals,color:RC(k),cw,rh,l:116,act:(i,j)=>`heat:${k}:${i}:${j}`,sel,tip:v=>`${v} ${t('products')} · ${t('clickFilter')}`,title:t('wPromoHeat')})}</div>
    <div class="wfoot"><span class="muted xs">${t('heatAxis')}</span><span class="muted xs num">${tot} ${t('productsOnPromo')} · ${RN(k)}</span></div>`}},
 matrix:{minW:6,dw:12,dh:4,title:()=>t('wMatrix'),sub:()=>t('wMatrixSub'),r(c,w,h){return matrix(c,w)}},
 shades:{minW:4,dw:6,dh:3,title:()=>t('wShades'),sub:()=>t('wShadesSub'),r(c,w,h){return shadesChart(c,w,h)}},
 stockouts:{minW:5,dw:6,dh:3,title:()=>t('wStock'),sub:()=>t('wStockSub'),r(c,w,h){const rows=[];c.P.forEach(p=>RR.forEach(k=>{if(S.ret.has(k)&&stockAt(p,k,c.b)===3)rows.push({p,k,since:outSince(p,k,c.b)})}));
   if(!rows.length)return emptyState(t('noStockouts'));const o=k=>k==='u'?'s':'u';
   return table('stockW',[{k:'p',label:t('product'),f:x=>pcell(x.p),v:x=>x.p.brand},{k:'k',label:t('retailer'),f:x=>`<span class="rdot" style="--c:${RC(x.k)}">${RN(x.k)}</span>`,v:x=>x.k},
    {k:'d',label:t('daysOut'),align:'r',f:x=>`${c.b-x.since+1}`,v:x=>c.b-x.since},{k:'o',label:t('otherRetailer'),f:x=>{const st=stockAt(x.p,o(x.k),c.b);return st?`${stockTag(st)} <span class="muted xs">${aed(priceAt(x.p,o(x.k),c.b))}</span>`:`<span class="muted xs">${t('notListed')}</span>`}}],
    rows,{sort:'d',limit:Math.max(3,Math.floor((hPx(h)-70)/52)),text:x=>x.p.brand+' '+x.p.name,rowProd:x=>x.p.id})}},
 avail:{minW:5,dw:6,dh:3,title:()=>t('wAvail'),sub:()=>t('wAvailSub'),r(c,w,h){if(!c.P.length)return emptyState();
   const ser=RR.filter(k=>S.ret.has(k)).map(k=>{const v=new Array(DAYS).fill(null);for(let d=c.a;d<=c.b;d++){let n=0,i=0,unk=0;c.P.forEach(p=>{const s=stockAt(p,k,d);if(!s)return;if(s===4){unk++;return}n++;if(s!==3)i++});v[d]=n&&!(unk>n*.5)?+(i/n*100).toFixed(1):null}return {name:RN(k),color:RC(k),dash:k==='s',vals:v}});
   const bands=NOT_OBS.map(n=>({a:n.a,b:n.b,label:RN(n.r)+': '+L(n.why)}));
   return `<div class="chart">${lineChart({id:'av-'+w+h,w:wPx(w),h:hPx(h)-34,a:c.a,b:c.b,series:ser,fmt:v=>fmtN(v,1)+'%',title:t('wAvail'),bands})}</div><div class="wfoot">${legendUS(true)}<span class="muted xs"><span class="hatchsw"></span> ${t('notObsLegend')}</span></div>`}},
 feed:{minW:3,dw:4,dh:3,title:()=>t('wFeed'),sub:()=>t('wFeedSub'),act:()=>seg('feedType',[['all',t('all')],['new',t('newL')],['gone',t('delistedL')]],S.feedType),
  r(c,w,h){let ev=launchesIn(c.P,c.a,c.b);if(S.feedType!=='all')ev=ev.filter(e=>e.type===S.feedType);if(!ev.length)return emptyState(t('noEvents'));
   return `<ul class="feed">${ev.slice(0,40).map(e=>`<li><button class="feedrow" data-prod="${e.p.id}">${thumb(e.p)}<span class="fx"><span class="ft"><span class="badge ${e.type==='new'?(e.k==='u'?'b-blush':'b-sky'):'b-grey'}">${e.type==='new'?t('newAt')(RN(e.k)):t('goneAt')(RN(e.k))}</span><span class="muted xs">${fmtD(dayDate(e.d))}</span></span><b>${esc(e.p.brand)}</b><span class="muted">${esc(e.p.name)}</span></span><span class="num fp">${aed(curPrice(e.p,e.k,e.d))}</span></button></li>`).join('')}</ul>`}},
 packsize:{minW:6,dw:12,dh:3,title:()=>t('wPack'),sub:()=>t('wPackSub'),r(c,w,h){const rows=[];c.P.forEach(p=>p.sizeChg.forEach(e=>{if(S.ret.has(e.r)&&e.d>=c.a&&e.d<=c.b){const pb=priceAt(p,e.r,e.d-1),pa=priceAt(p,e.r,e.d);if(pb==null||pa==null)return;rows.push({p,e,pb,pa,du:((pa/e.to)/(pb/e.from)-1)*100})}}));
   if(!rows.length)return emptyState(t('noPack'));
   return table('packW',[{k:'p',label:t('product'),f:x=>pcell(x.p),v:x=>x.p.brand},{k:'k',label:t('retailer'),f:x=>`<span class="rdot" style="--c:${RC(x.e.r)}">${RN(x.e.r)}</span>`},{k:'d',label:t('date'),f:x=>fmtD(dayDate(x.e.d)),v:x=>x.e.d},
    {k:'sz',label:t('size'),f:x=>`<span class="num">${x.e.from} → <b>${x.e.to}</b> ${x.p.unit}</span>`},{k:'pr',label:t('price'),align:'r',f:x=>`${aed(x.pb)} → ${aed(x.pa)}`},{k:'du',label:t('unitChange'),align:'r',f:x=>`<b class="gap-pos">${pct(x.du)}</b>`,v:x=>x.du}],rows,{sort:'du',limit:Math.max(3,Math.floor((hPx(h)-70)/52)),text:x=>x.p.brand+' '+x.p.name,rowProd:x=>x.p.id})}}
};
function c0(k){return S.ret.has(k)?[k,RN(k)]:null}
function kpi(label,val,sub,foot,dir,tip){return `<div class="kpi2"><div class="kl">${label}${tip?`<span class="info" data-tip="${esc(tip)}" aria-hidden="true">${ICON.info}</span><span class="vh">${esc(tip)}</span>`:''}</div><div class="kv num${(String(val).match(/<small>/g)||[]).length>1?' two':''}">${val}</div><div class="ks">${sub}</div>${foot?`<div class="kf num">${foot}</div>`:''}</div>`}
function binLabel(i){const [lo,hi]=GAP_BINS[i];if(lo===0&&hi===0)return t('samePrice');if(lo===-1e9)return `≤ −15% · ${t('ultaCheaper')}`;if(hi===1e9)return `> +15% · ${t('sephoraCheaper')}`;return `${lo>0?'+':''}${Math.round(lo)}% … ${hi>0?'+':''}${Math.round(hi)}% · ${lo<0?t('ultaCheaper'):t('sephoraCheaper')}`}
function promoCal(c,W_){
  const camps=CAMPAIGNS.filter(x=>S.ret.has(x.r)&&x.b>=c.a&&x.a<=c.b).sort((x,y)=>x.r.localeCompare(y.r)||x.a-y.a);if(!camps.length)return emptyState(t('noPromos'));
  const l=Math.min(250,W_*.3),r=10,rowH=26,top=26,H=top+camps.length*rowH+12,n=c.b-c.a+1,x=d=>l+(Math.max(c.a,Math.min(c.b+1,d))-c.a)/n*(W_-l-r);
  const col={pct:'#F2C6D1',bundle:'#CFE3F3',gwp:'#CDEBDC',member:'#DDD4F0',unclassified:'#F5E6B3'},ink={pct:'#8E2F4B',bundle:'#27557F',gwp:'#1F6446',member:'#4E3F7E',unclassified:'#6E520E'};
  const sel=S.sel&&S.sel.src==='promocal'?S.sel.key:null;
  let s=`<svg viewBox="0 0 ${W_} ${H}" role="img" aria-label="${esc(t('wPromoCal'))}">`;const step=n>120?28:n>45?14:7;
  for(let d=c.a;d<=c.b;d+=step)s+=`<line x1="${x(d)}" x2="${x(d)}" y1="${top-6}" y2="${H-8}" stroke="${GRID}"/><text x="${x(d)+3}" y="14" font-size="10.5" fill="${AX}">${fmtD(dayDate(d))}</text>`;
  let prev=null;camps.forEach((cp,i)=>{const y=top+i*rowH;if(prev&&prev!==cp.r)s+=`<line x1="0" x2="${W_}" y1="${y-2}" y2="${y-2}" stroke="#E4E0D8"/>`;prev=cp.r;
   const n0=PRODUCTS.filter(p=>p.promos.some(z=>z.c===cp.id)).length;const dim=sel&&sel!==cp.id;
   s+=`<g opacity="${dim?.35:1}"><circle cx="6" cy="${y+10}" r="4" fill="${RC(cp.r)}"/><text x="16" y="${y+14}" font-size="11.5" fill="#1E2226">${esc(clip(L(cp.name),Math.floor((l-20)/6.2)))}</text>`;
   const x0=x(cp.a),x1=x(cp.b+1);s+=`<rect x="${x0}" y="${y+2}" width="${Math.max(3,x1-x0)}" height="${rowH-8}" rx="4" fill="${col[cp.mech]}" ${sel===cp.id?'stroke="#1E2226" stroke-width="1.5"':''}/>`;
   const lab=`${t('mech')[cp.mech]}${cp.depth?` · ${cp.depth[0]===cp.depth[1]?cp.depth[0]:cp.depth[0]+'–'+cp.depth[1]}%`:''}`;if(x1-x0>lab.length*6+10)s+=`<text x="${x0+6}" y="${y+15}" font-size="10.5" font-weight="600" fill="${ink[cp.mech]}" pointer-events="none">${esc(lab)}</text>`;
   s+=`<rect class="hit${n0?' act':''}" x="${x0}" y="${y+2}" width="${Math.max(3,x1-x0)}" height="${rowH-8}" fill="transparent" ${tipAttr([L(cp.name),`${RN(cp.r)} · ${cp.start} → ${cp.end}`,lab,n0?`${n0} ${t('products')} · ${t('clickFilter')}`:t('notLinked')])} ${n0?`data-act="pc:${cp.id}" tabindex="0" role="button"`:''}/></g>`});
  if(c.b===DAYS-1)s+=`<line x1="${x(c.b+1)-1}" x2="${x(c.b+1)-1}" y1="${top-8}" y2="${H-6}" stroke="#1E2226" stroke-width="1.4"/><text x="${x(c.b+1)-4}" y="${top-10}" font-size="10.5" text-anchor="end" font-weight="700" fill="#1E2226">${t('today')}</text>`;
  return `<div class="chart">${s}</svg></div><div class="wfoot"><div class="legend">${Object.keys(col).map(k=>`<span><span class="sw" style="background:${col[k]}"></span>${t('mech')[k]}</span>`).join('')}</div></div>`}
const szT=(v,p)=>v==null||v===''?t('sizeNA'):`\u2066${v}${p.unit?' '+esc(p.unit):''}\u2069`;
const clip=(s,n)=>s.length>n?s.slice(0,Math.max(3,n-1))+'…':s;
function matrix(c,w){const P=c.src('matrix');if(!P.length)return emptyState();const cats=CATS.filter(k=>P.some(p=>p.cat===k));
  const brands=[...new Set(P.map(p=>p.brand))].map(b=>[b,P.filter(p=>p.brand===b).length]).sort((a,b)=>b[1]-a[1]).map(x=>x[0]);
  const sel=S.sel&&S.sel.src==='matrix'?S.sel.key:null;
  const cell=(b,k)=>{const Q=P.filter(p=>p.brand===b&&p.cat===k);if(!Q.length)return `<td class="mx0"><span aria-hidden="true">·</span></td>`;
    const u=Q.filter(p=>p.listed.u&&!p.listed.s).length,s=Q.filter(p=>p.listed.s&&!p.listed.u).length,bo=Q.length-u-s;const key=b+'|'+k;
    return `<td><button class="mxc${sel===key?' sel':''}${sel&&sel!==key?' dim':''}" data-act="mx:${esc(key)}" ${tipAttr([b+' · '+t('cat')[k],`${t('both')}: ${bo}`,`${t('uOnly')}: ${u}`,`${t('sOnly')}: ${s}`,t('clickFilter')])}><span class="mxbar"><i style="flex:${u};background:${C_U}"></i><i style="flex:${bo};background:#CFC6E6"></i><i style="flex:${s};background:${C_S}"></i></span><span class="num">${Q.length}</span></button></td>`};
  return `<div class="mxwrap"><table class="mx"><thead><tr><th></th>${cats.map(k=>`<th>${esc(t('cat')[k])}</th>`).join('')}<th class="r">${t('total')}</th></tr></thead><tbody>
   ${brands.map(b=>{const Q=P.filter(p=>p.brand===b);const bu=Q.filter(p=>p.listed.u&&!p.listed.s).length,bs=Q.filter(p=>p.listed.s&&!p.listed.u).length;
    return `<tr><th scope="row">${esc(b)}${DS.real&&!bothOk()?'':bu===Q.length?` <span class="badge b-blush xs">${t('uOnly')}</span>`:bs===Q.length?` <span class="badge b-sky xs">${t('sOnly')}</span>`:''}</th>${cats.map(k=>cell(b,k)).join('')}<td class="r num muted">${Q.length}</td></tr>`}).join('')}</tbody></table></div>
   <div class="wfoot"><div class="legend"><span><span class="sw" style="background:${C_U}"></span>${t('uOnly')}</span><span><span class="sw" style="background:#CFC6E6"></span>${t('both')}</span><span><span class="sw" style="background:${C_S}"></span>${t('sOnly')}</span></div><span class="muted xs">${t('clickFilter')}</span></div>`}
function shadesChart(c,w,h){const P=c.P.filter(p=>p.shadeCount.u>2&&p.shadeCount.s>2);if(!P.length)return emptyState(t('noShades'));
  const rows=[...P].sort((a,b)=>Math.abs(b.shadeCount.s-b.shadeCount.u)-Math.abs(a.shadeCount.s-a.shadeCount.u)||b.shadeCount.s-a.shadeCount.s);
  const W_=wPx(w),l=Math.min(260,W_*.38),r=36,rh=28,n=Math.max(3,Math.floor((hPx(h)-60)/rh)),sh=rows.slice(0,n),H=20+sh.length*rh;const mx=Math.max(...sh.map(p=>Math.max(p.shadeCount.u,p.shadeCount.s)));const sc=niceScale(0,mx,4);const x=v=>l+v/sc.hi*(W_-l-r);
  let s=`<svg viewBox="0 0 ${W_} ${H}" role="img" aria-label="${esc(t('wShades'))}">`;for(let v=0;v<=sc.hi;v+=sc.step)s+=`<line x1="${x(v)}" x2="${x(v)}" y1="4" y2="${H-16}" stroke="${GRID}"/><text x="${x(v)}" y="${H-3}" font-size="10" text-anchor="middle" fill="${AX}">${v}</text>`;
  sh.forEach((p,i)=>{const y=12+i*rh,u=p.shadeCount.u,sv=p.shadeCount.s;s+=`<g class="dot" data-prod="${p.id}" ${tipAttr([p.brand+' · '+p.name,`${t('ulta')}: ${u} ${t('shadesW')}`,`${t('sephora')}: ${sv} ${t('shadesW')}`])}><rect x="0" y="${y-10}" width="${W_}" height="${rh-4}" fill="transparent"/><text x="0" y="${y+4}" font-size="11" fill="#1E2226"><tspan font-weight="600">${esc(clip(p.brand,18))}</tspan><tspan fill="${AX}"> ${esc(clip(p.name,Math.max(8,Math.floor((l-110)/5.8))))}</tspan></text>
   <line x1="${x(u)}" x2="${x(sv)}" y1="${y}" y2="${y}" stroke="#D6D0C6" stroke-width="3"/><circle cx="${x(u)}" cy="${y}" r="5.5" fill="${C_U}"/><rect x="${x(sv)-5}" y="${y-5}" width="10" height="10" rx="2" fill="${C_S}"/>${u!==sv?`<text x="${x(Math.max(u,sv))+10}" y="${y+4}" font-size="10.5" font-weight="650" fill="#3C434B">${sv-u>0?'+':''}${sv-u}</text>`:''}</g>`});
  return `<div class="chart">${s}</svg></div><div class="wfoot"><div class="legend"><span><span class="sw" style="background:${C_U};border-radius:50%"></span>${t('ulta')}</span><span><span class="sw" style="background:${C_S}"></span>${t('sephora')}</span></div><span class="muted xs">${t('shadesFoot')(rows.length)}</span></div>`}

function widget(item,i,edit,fixed){const [k,w,h]=item;const def=W[k];if(!def)return '';const c=ctx();
  const loading=S.loading||S.preview==='loading';const stale=S.preview==='stale';const gt=gate(def.needs);
  let body;if(loading)body=`<div class="skel">${def.kpi?'<i style="width:40%"></i><i style="width:60%;height:26px"></i><i style="width:80%"></i>':'<i style="width:35%"></i><i style="height:calc(100% - 48px)"></i>'}</div>`;else if(gt)body=gateState(gt,def.kpi);else{try{body=def.r(c,w,h)}catch(e){console.error(e);body=`<div class="wempty"><b>${t('errT')}</b></div>`}}
  const ctl=edit?`<div class="wctl"><span class="grip" ${tipAttr([t('dragHint')])} aria-hidden="true">${ICON.grip}</span><button class="iconbtn" data-wmenu="${i}" aria-haspopup="menu" aria-expanded="${S.wmenu===i}" aria-label="${t('widgetMenu')}: ${esc(def.title())}">${ICON.more}</button>${S.wmenu===i?wmenu(i,item):''}</div>`:'';
  const staleBar=stale?`<div class="stalebar"><span class="dot"></span>${t('staleMsg')}</div>`:'';
  const style=fixed?`grid-column:span ${w};grid-row:span ${h}`:`grid-column:span ${w};grid-row:span ${h}`;
  if(def.kpi)return `<section class="widget kpiw${edit?' editing':''}${stale?' stale':''}" data-wi="${i}" style="${style}" ${edit?'draggable="true"':''} aria-label="${esc(def.title())}">${ctl}${gt&&!loading?`<div class="kpibtn static"><div class="kl">${esc(def.title())}</div>${body}</div>`:loading?body:`<button class="kpibtn" ${edit?'tabindex="-1"':''} data-drill="${def.drill}" aria-label="${esc(def.title())}: ${t('drillHint')}">${body}<span class="drillhint">${t('drill')} ${ICON.arrow}</span></button>`}${staleBar}${edit?`<span class="rs" data-rs="${i}" aria-hidden="true"></span>`:''}</section>`;
  return `<section class="widget${edit?' editing':''}${stale?' stale':''}" data-wi="${i}" style="${style}" ${edit?'draggable="true"':''} aria-label="${esc(def.title())}"><header class="wh"><div class="wt"><h3>${def.title()}</h3>${def.sub?`<p>${def.sub()}</p>`:''}</div><div class="wa">${!loading&&def.act?def.act():''}</div>${ctl}</header>${staleBar}<div class="wb">${body}</div>${edit?`<span class="rs" data-rs="${i}" aria-hidden="true"></span>`:''}</section>`}
function wmenu(i,item){const [k,w,h]=item,min=W[k].minW||3,n=S.layout.length;
  const b=(act,label,dis)=>`<button role="menuitem" data-wact="${act}" data-i="${i}" ${dis?'disabled':''}>${label}</button>`;
  return `<div class="menu" role="menu">${b('prev',t('moveEarlier'),i===0)}${b('next',t('moveLater'),i===n-1)}<hr>${b('wider',t('wider')+` <span class="muted">${w}/12</span>`,w>=12)}${b('narrower',t('narrower'),w<=min)}${b('taller',t('taller')+` <span class="muted">${h}</span>`,h>=5)}${b('shorter',t('shorter'),h<=1)}<hr>${b('remove',`<span class="danger">${t('removeW')}</span>`)}</div>`}

/* ---------- filter bar ---------- */
function facetCount(key,v){const [a,b]=S.range;return PRODUCTS.filter(p=>passes(p,key,a,b)&&(key==='brand'?p.brand===v:key==='cat'?p.cat===v:key==='shade'?p.fam.includes(v):(()=>{const B=BANDS.find(x=>x[0]===v),m=minCur(p,b);return m!=null&&m>=B[1]&&m<=B[2]})())).length}
function facets(){return [['brand',t('brand'),BRAND_LIST.map(b=>[b,b]),true],['cat',t('category'),CATS.map(k=>[k,t('cat')[k]])],['band',t('band'),BANDS.map(x=>[x[0],(S.lang==='ar'?'':'AED ')+x[0]])],['shade',t('shadeFam'),FAMS.map(k=>[k,t('fam')[k]])]]}
function filterPanel(px=''){return facets().map(([key,label,opts,search])=>`<section class="fsec"><div class="fsh"><h3 class="dh">${label}</h3>${S.f[key].size?`<button class="linkbtn" data-fclear="${key}">${t('clear')}</button>`:''}</div>${search?`<input type="search" class="popq" id="${px}pq-${key}" placeholder="${t('searchBrand')}" aria-label="${t('searchBrand')}" value="${esc(S.popq||'')}" data-popq="1">`:''}<div class="popl${search?' tall':''}" role="group" aria-label="${esc(label)}">${opts.filter(([v,l])=>!search||!S.popq||l.toLowerCase().includes(S.popq.toLowerCase())).map(([v,l])=>[v,l,facetCount(key,v)]).sort((x,y)=>key==='brand'?(S.f.brand.has(y[0])-S.f.brand.has(x[0]))||(!!y[2]-!!x[2]):0).map(([v,l,cn])=>{return `<label class="${cn?'':'zero'}"><input type="checkbox" id="${px}cb-${key}-${esc(v).replace(/[^a-z0-9]/gi,'')}" data-f="${key}" value="${esc(v)}" ${S.f[key].has(v)?'checked':''}><span>${esc(l)}</span><span class="c num">${cn}</span></label>`}).join('')}</div></section>`).join('')}
function filterBar(){const c=ctx();const [a,b]=S.range;const span=b-a+1;const preset=b===DAYS-1&&[30,90,180].includes(span)?span:null;
  const nf=Object.values(S.f).reduce((n,x)=>n+x.size,0);
  const chips=[];Object.entries(S.f).forEach(([k,set])=>set.forEach(v=>chips.push(`<button class="chip" data-unf="${k}" data-v="${esc(v)}" aria-label="${t('removeFilter')}: ${esc(v)}">${esc(k==='cat'?t('cat')[v]:k==='shade'?t('fam')[v]:k==='band'?(S.lang==='ar'?'':'AED ')+v:v)} ${ICON.x}</button>`)));
  const MAXC=4,more=chips.length-MAXC;const shown=chips.slice(0,MAXC);if(more>0)shown.push(`<button class="chip more" data-fdrawer>+${more}</button>`);
  if(S.sel)shown.push(`<button class="chip sel" data-unsel aria-label="${t('clearSel')}"><b>${t('selection')}</b> ${esc(S.sel.label)} · ${S.sel.ids.size} ${ICON.x}</button>`);
  if(!preset)shown.push(`<button class="chip" data-range="90" aria-label="${t('resetRange')}">${ICON.cal} ${fmtD(dayDate(a))} – ${fmtD(dayDate(b))} ${ICON.x}</button>`);
  const any=nf||S.sel||!preset||S.ret.size<2;
  return `<div class="filterbar" role="region" aria-label="${t('filters')}"><div class="fbrow">
   <button class="fbtn${nf?' on':''}" id="fb-open" data-fdrawer aria-haspopup="dialog">${ICON.filter}<span>${t('filtersBtn')}</span>${nf?`<span class="cnt">${nf}</span>`:''}</button>
   <div class="seg ret" role="group" aria-label="${t('retailer')}">${RR.map(k=>`<button data-ret="${k}" aria-pressed="${S.ret.has(k)}"><i style="background:${RC(k)}"></i>${RN(k)}</button>`).join('')}</div>
   <div class="seg" role="group" aria-label="${t('dateRange')}">${[30,90,180].map(n=>`<button data-range="${n}" aria-pressed="${preset===n}">${t('lastN')(n)}</button>`).join('')}</div>
   ${shown.length?`<span class="fchips">${shown.join('')}</span>`:''}
   <span class="spacer"></span><span class="muted xs num" aria-live="polite">${t('inScope')(c.P.length,PRODUCTS.length)}</span>${any?`<button class="linkbtn" data-reset>${t('resetAll')}</button>`:''}</div></div>`}

/* ---------- data gating (honest states) ---------- */
const CAP_FIELD={promotions:'promo',stock:'stock',shades:'shades',campaigns:'promo',sizes:'size'};
const retOk=k=>!DS.real||DS.rOk[k];
const bothOk=()=>retOk('u')&&retOk('s');
function retNote(k){const r=DS.rets&&DS.rets[k];return r&&r.note?L(r.note):t('retUnavailable')}
/* plain-language retailer status: short line on screen, detail behind an info icon; internal notes (paths, PRs, commits) never shown */
const SEC_RE=/cloudflare|challenge|captcha|\bbot\b|site security|\bwaf\b|تحدّي|تحدي|حماية/i;
function retStatus(k){return ((DS.rets&&DS.rets[k])||{}).status||'pending'}
function retSec(k){const r=(DS.rets&&DS.rets[k])||{};return r.reasonCode==='site_security'||SEC_RE.test(r.note?(r.note.en||'')+' '+(r.note.ar||''):'')}
function retShort(k){const st=retStatus(k);if(!retOk(k))return st==='blocked'||st==='warn'?`${retSec(k)?t('stSec'):t('stUnavail')} · ${t('retest')}`:t('statusName')[st]||esc(st);
  const n=fmtN(PRODUCTS.filter(p=>p.listed[k]).length);return st==='partial'?t('stPartialN')(n):t('stOkN')(n)}
function plainNote(x){return (x||'').split(/(?<=[.;؛])\s+/).filter(z=>z&&!/[\w-]+\/[\w./-]+\.\w{2,4}|PR\s*#|\b[0-9a-f]{7,40}\b|^\s*(Source|المصدر)\s*:|recon|الاستطلاع|database|قاعدة البيانات|collector|المُجمِّع|cool-off/i.test(z)).join(' ')}
function retDetail(k){if(!retOk(k))return retSec(k)?t('secDetail'):(plainNote(retNote(k))||t('retUnavailable'));const c=retCov(k);return retStatus(k)==='partial'?t('partialDetail')(fmtN(c.n))+(c.est?' '+covText(k)+'.':''):t('okDetail')}
function info(tip){return `<button type="button" class="info" data-tip="${esc(tip)}" aria-label="${esc(t('moreInfo')+': '+tip)}">${ICON.info}</button>`}
function gate(n){if(!n||!DS.real)return null;
  if(n.both&&!bothOk()){const k=!retOk('u')?'u':'s';return {t:`${RN(k)}: ${retSec(k)?t('stSec'):t('stUnavail')}`,ts:`${RN(k)}: ${retSec(k)?t('blockedShort'):t('stUnavail')}`,m:retDetail(k),k,kind:'bad'}}
  if(n.any&&!RR.some(k=>retOk(k)&&S.ret.has(k)))return {t:t('noRetailer'),m:'',kind:'warn'};
  if(n.history&&DS.N<2)return {t:t('needsHistory'),m:t('needsHistoryP')(cutoffShort()),kind:'wait'};
  for(const c of n.caps||[])if(!DS.caps[c]){const st=DS.fieldStatus[CAP_FIELD[c]]||'not_collected';if(st==='ok')return {t:t('needsHistory'),m:t('needsHistoryP')(cutoffShort()),kind:'wait'};return {t:`${t('capName')[c]}: ${t('fs')[st]}`,m:t('fsP')[st],kind:'warn'}}
  return null}
function gateState(g,compact){return `<div class="wempty gate${compact?' compact':''}"><span class="gi ${g.kind||'wait'}">${ICON[g.kind==='bad'?'shield':g.kind==='warn'?'dash':'clock']}</span><span class="gl"><b>${esc(compact&&g.ts||g.t)}</b>${g.m?info(g.m):''}</span>${g.k&&!compact?`<a class="linkbtn" href="#/coverage">${t('seeCoverage')}</a>`:''}</div>`}
const NEEDS={kpiIndex:{both:1},kpiGap:{both:1},kpiMatched:{both:1},kpiPromo:{caps:['promotions']},kpiStock:{caps:['stock']},kpiLaunch:{history:1},
  index:{both:1,history:1},gapdist:{both:1},gaps:{both:1},ladder:{any:1},promocal:{caps:['campaigns']},promoheat:{history:1,caps:['promotions']},promodepth:{caps:['promotions']},
  matrix:{any:1},shades:{both:1,caps:['shades']},stockouts:{caps:['stock']},avail:{history:1,caps:['stock']},feed:{history:1},packsize:{history:1,caps:['sizes']},kpiCatalog:{},early:{}};
function cutoffShort(){const d=new Date(DS.meta.cutoff);return isNaN(d)?esc(DS.meta.cutoff):`${fmtD(d)} ${d.getUTCFullYear()}`}
function cutoffLong(){const d=new Date(DS.meta.cutoff);if(isNaN(d))return esc(DS.meta.cutoff);return `${fmtD(d)} ${d.getUTCFullYear()}, ${String(d.getUTCHours()).padStart(2,'0')}:${String(d.getUTCMinutes()).padStart(2,'0')} UTC`}
function dataLabel(){if(!DS.real)return `<span class="mocklabel" role="note">${t('mockLabel')}</span>`;
  const m=DS.meta;return `<span class="mocklabel real${m.test?' test':''}" role="note">${m.test?`<b>${t('testFixture')}</b> · `:''}${t('srcLabel')(RR.filter(k=>retOk(k)).map(RN).join(S.lang==='ar'?'، ':', ')||'—')} · ${t('cutoffLabel')(cutoffLong())}${info(t('badgeTip')(m.matchStage==='first-pass'?t('firstPass'):t('reviewedMatches')))}</span>`}

/* snapshot-friendly widgets */
Object.assign(W,{
 kpiCatalog:{kpi:true,drill:'catalog',minW:2,dw:3,dh:1,title:()=>t('kCatalog'),r(c){const n=k=>c.P.filter(p=>listedAt(p,k,c.b)||(DS.N<2&&p.listed[k])).length,np=k=>DS.N<2?c.P.filter(p=>p.listed[k]&&!listedAt(p,k,c.b)).length:0;const ks=RR.filter(k=>retOk(k)&&S.ret.has(k));
   return kpi(t('kCatalog'),ks.map(k=>`${fmtN(n(k))}<small>${RN(k)}</small>`).join(' ')||'—',t('kCatalogSub')(new Set(c.P.map(p=>p.brand)).size,new Set(c.P.map(p=>p.cat)).size),'','',RR.map(k=>{if(!retOk(k))return `${RN(k)}: ${retShort(k)}`;const a=[(DS.rets[k]||{}).status==='partial'?covText(k):'',S.ret.has(k)&&np(k)?t('noPriceN')(fmtN(np(k))):''].filter(Boolean);return a.length?`${RN(k)}: ${a.join(S.lang==='ar'?'، ':', ')}`:''}).filter(Boolean).join(' · '))}},
 promodepth:{minW:4,dw:6,dh:3,title:()=>t('wPromoDepth'),sub:()=>t('wPromoDepthSub'),r(c,w,h){const ks=RR.filter(k=>retOk(k)&&S.ret.has(k));const P=c.src('promodepth');
   const series=ks.map(k=>({name:RN(k),color:RC(k),vals:DEPTHB.map((_,i)=>P.filter(p=>{const v=promoAt(p,k,c.b);return v>0&&depthIdx(v)===i}).length)}));
   if(!series.some(s=>s.vals.some(v=>v)))return emptyState(t('noPromosNow'));const sel=S.sel&&S.sel.src==='promodepth'?S.sel.key:null;
   return `<div class="chart">${bars({w:wPx(w),h:hPx(h)-40,cats:DEPTHB,series,sel,act:i=>'pd:'+i,title:t('wPromoDepth'),tipTitle:i=>`${t('discount')} ${DEPTHB[i]}`,tipExtra:t('clickFilter'),maxBar:40})}</div><div class="wfoot">${legendUS()}<span class="muted xs">${t('asOf')} ${fmtD(dayDate(c.b))}</span></div>`}},
 early:{minW:3,dw:4,dh:4,title:()=>t('wEarly'),sub:()=>t('wEarlySub'),r(c,w,h){const blocked=RR.filter(k=>DS.real&&!retOk(k));
   return `${blocked.map(k=>`<div class="retstate"><span class="rdot" style="--c:${RC(k)}">${RN(k)}</span><span class="gl"><b>${retShort(k)}</b>${info(retDetail(k))}</span></div>`).join('')||`<div class="retstate ok"><b>${t('allRetOk')}</b></div>`}
   ${earlyList(6)}`}}
});
Object.entries(NEEDS).forEach(([k,n])=>{if(W[k])W[k].needs=n});
/* available-now widgets: one retailer, one snapshot. Shown when panels that need both retailers or history are gated. */
const liveR=()=>RR.filter(k=>retOk(k)&&S.ret.has(k));
const pricesOf=(P,k,d)=>P.map(p=>curPrice(p,k,d)).filter(v=>v!=null);
const quant=(a,f)=>{if(!a.length)return null;const s=[...a].sort((x,y)=>x-y),i=(s.length-1)*f,lo=Math.floor(i);return s[lo]+(s[Math.min(lo+1,s.length-1)]-s[lo])*(i-lo)};
const rateOf=p=>{for(const k of liveR()){const r=p.rating[k];if(r&&r[1]>0)return r}return null};
const SETF_KEYS=['brand','cat','band','shade'];
const setfBtn=(spec,label)=>`<button class="linkbtn strong" data-setf="${esc(spec)}">${esc(label)}</button>`;
function groupRows(c,key){const ks=liveR(),m=new Map();c.P.forEach(p=>{const v=key(p);if(!m.has(v))m.set(v,[]);m.get(v).push(p)});
  return [...m].map(([v,P])=>{const pr=ks.flatMap(k=>pricesOf(P,k,c.b)),rs=P.map(rateOf).filter(Boolean);
    return {v,P,n:P.length,brands:new Set(P.map(p=>p.brand)).size,cats:new Set(P.map(p=>p.cat)).size,med:median(pr),lo:pr.length?Math.min(...pr):null,hi:pr.length?Math.max(...pr):null,q1:quant(pr,.25),q3:quant(pr,.75),
     rat:rs.length?rs.reduce((a,r)=>a+r[0]*r[1],0)/rs.reduce((a,r)=>a+r[1],0):null,reviews:rs.reduce((a,r)=>a+r[1],0)}})}
const rangeT=(a,b)=>a==null?'—':`${aed(a)} – ${fmtN(b)}`;
Object.assign(W,{
 kpiMedPrice:{kpi:true,drill:'catalog',minW:2,dw:3,dh:1,title:()=>t('kMedPrice'),r(c){const ks=liveR();const pr=k=>pricesOf(c.P,k,c.b);
   const all=ks.flatMap(pr);return kpi(t('kMedPrice'),ks.map(k=>`${aed(median(pr(k)))}<small>${RN(k)}</small>`).join(' ')||'—',t('kMedPriceSub')(fmtN(all.length)),all.length?`${t('midHalf')} ${rangeT(quant(all,.25),quant(all,.75))}`:'')}},
 kpiBrands:{kpi:true,drill:'catalog',minW:2,dw:3,dh:1,title:()=>t('kBrands'),r(c){const g=groupRows(c,p=>p.brand).sort((a,b)=>b.n-a.n);
   return kpi(t('kBrands'),fmtN(g.length),g.length?t('kBrandsSub')(esc(g[0].v),fmtN(g[0].n)):'',g.length>2?t('top3Share')(fmtN(g.slice(0,3).reduce((a,x)=>a+x.n,0)/c.P.length*100,0)):'')}},
 kpiRating:{kpi:true,drill:'catalog',minW:2,dw:3,dh:1,title:()=>t('kRating'),r(c){const rs=c.P.map(rateOf).filter(Boolean),rev=rs.reduce((a,r)=>a+r[1],0);
   const avg=rev?rs.reduce((a,r)=>a+r[0]*r[1],0)/rev:null;return kpi(t('kRating'),avg==null?'—':`${fmtN(avg,2)}<small>/ 5</small>`,t('kRatingSub')(fmtN(rs.length),rev.toLocaleString('en-US',{notation:'compact',maximumFractionDigits:1})),rs.length?t('lowRated')(fmtN(rs.filter(r=>r[0]<4).length)):'')}},
 bandgrid:{minW:6,dw:12,dh:3,title:()=>t('wBandGrid'),sub:()=>t('wBandGridSub'),r(c){const ks=liveR();if(!c.P.length||!ks.length)return emptyState();
   const cats=CATS.filter(k=>c.P.some(p=>p.cat===k));const bandOf=p=>{const m=minCur(p,c.b);return m==null?null:BANDS.findIndex(B=>m>=B[1]&&m<=B[2])};
   const cnt=cats.map(k=>BANDS.map((_,i)=>c.P.filter(p=>p.cat===k&&bandOf(p)===i).length));const mx=Math.max(1,...cnt.flat());
   const tot=BANDS.map((_,i)=>cnt.reduce((a,r)=>a+r[i],0)),all=tot.reduce((a,b)=>a+b,0);const bl=x=>(S.lang==='ar'?'':'AED ')+x[0];
   return `<div class="tscroll"><table class="data bandg"><thead><tr><th>${t('category')}</th>${BANDS.map(B=>`<th class="r">${setfBtn('band:'+B[0],bl(B))}</th>`).join('')}<th class="r">${t('total')}</th></tr></thead><tbody>
    ${cats.map((k,ci)=>{const rt=cnt[ci].reduce((a,b)=>a+b,0);return `<tr><td>${setfBtn('cat:'+k,t('cat')[k])}</td>${cnt[ci].map((v,i)=>`<td class="r num"><button class="hcell" data-setf="${esc('cat:'+k+'|band:'+BANDS[i][0])}" style="--a:${(v/mx).toFixed(2)}" aria-label="${esc(t('cat')[k]+', '+bl(BANDS[i])+': '+v)}" ${v?'':'disabled'}>${v||'·'}</button><span class="pc">${rt?fmtN(v/rt*100,0)+'%':''}</span></td>`).join('')}<td class="r num"><b>${fmtN(rt)}</b></td></tr>`}).join('')}
    <tr class="tot"><td>${t('total')}</td>${tot.map(v=>`<td class="r num"><b>${fmtN(v)}</b><span class="pc">${all?fmtN(v/all*100,0)+'%':''}</span></td>`).join('')}<td class="r num"><b>${fmtN(all)}</b></td></tr></tbody></table></div>
    <div class="wfoot"><span class="muted xs">${t('bandFoot')}</span></div>`}},
 brandtbl:{minW:6,dw:12,dh:4,title:()=>t('wBrands'),sub:()=>t('wBrandsSub'),r(c){const rows=groupRows(c,p=>p.brand);if(!rows.length)return emptyState();
   if(!S.tbl.brandT)S.tbl.brandT={sort:'n',dir:-1,q:'',limit:10};
   return `<div class="tscroll">${table('brandT',[{k:'v',label:t('brand'),f:x=>setfBtn('brand:'+x.v,x.v),v:x=>x.v},{k:'n',label:t('productsH'),align:'r',f:x=>fmtN(x.n),v:x=>x.n},{k:'c',label:t('categories'),align:'r',f:x=>x.cats,v:x=>x.cats},
    {k:'m',label:t('medianL'),align:'r',f:x=>aed(x.med),v:x=>x.med},{k:'r',label:t('priceRange'),align:'r',f:x=>rangeT(x.lo,x.hi),v:x=>x.hi},{k:'rt',label:t('ratingL'),align:'r',f:x=>x.rat==null?'—':`${fmtN(x.rat,2)} <span class="muted xs">(${fmtN(x.reviews)})</span>`,v:x=>x.rat}],rows,{text:x=>x.v})}</div>`}},
 cattbl:{minW:6,dw:12,dh:3,title:()=>t('wCats'),sub:()=>t('wCatsSub'),r(c){const rows=groupRows(c,p=>p.cat).sort((a,b)=>CATS.indexOf(a.v)-CATS.indexOf(b.v));if(!rows.length)return emptyState();
   return `<div class="tscroll"><table class="data"><thead><tr><th>${t('category')}</th><th class="r">${t('productsH')}</th><th class="r">${t('brandsL')}</th><th class="r">${t('medianL')}</th><th class="r">${t('midHalf')}</th><th class="r">${t('priceRange')}</th><th class="r">${t('ratingL')}</th></tr></thead><tbody>
    ${rows.map(x=>`<tr><td>${setfBtn('cat:'+x.v,t('cat')[x.v])}</td><td class="r num">${fmtN(x.n)}</td><td class="r num">${x.brands}</td><td class="r num">${aed(x.med)}</td><td class="r num">${rangeT(x.q1,x.q3)}</td><td class="r num">${rangeT(x.lo,x.hi)}</td><td class="r num">${x.rat==null?'—':fmtN(x.rat,2)}</td></tr>`).join('')}</tbody></table></div>`}},
 shadetop:{minW:6,dw:12,dh:4,title:()=>t('wShadeTop'),sub:()=>t('wShadeTopSub'),r(c){const ks=liveR();const sc=p=>Math.max(0,...ks.map(k=>p.shadeCount[k]||0));
   const rows=c.P.filter(p=>sc(p)>1);if(!rows.length)return emptyState(t('noShades'));if(!S.tbl.shadeT)S.tbl.shadeT={sort:'sc',dir:-1,q:'',limit:10};
   return `<div class="tscroll">${table('shadeT',[{k:'p',label:t('product'),f:p=>pcell(p,t('cat')[p.cat]),v:p=>p.brand+p.name},{k:'sc',label:t('shadesW'),align:'r',f:p=>fmtN(sc(p)),v:sc},
    {k:'pr',label:t('price'),align:'r',f:p=>aed(minCur(p,c.b)),v:p=>minCur(p,c.b)}],rows,{text:p=>p.brand+' '+p.name,rowProd:p=>p.id})}</div>
    <div class="wfoot"><span class="muted xs">${t('shadeTopFoot')(fmtN(rows.length),fmtN(c.P.length))}</span></div>`}}
});
['kpiMedPrice','kpiBrands','kpiRating','bandgrid','brandtbl','cattbl','shadetop'].forEach(k=>{NEEDS[k]={any:1};W[k].needs=NEEDS[k]});
/* Fixed pages: on real data, drop gated panels, add what this snapshot can show, and list what is missing in one card. */
function pageGrid(items,alts){if(!DS.real)return fixedGrid(items);
  const g=it=>gate(W[it[0]].needs);const ok=items.filter(it=>!g(it)),off=items.filter(g);
  if(off.length)alts.forEach(it=>{if(!g(it)&&!ok.some(o=>o[0]===it[0]))ok.push(it)});
  const kp=ok.filter(it=>W[it[0]].kpi).slice(0,4),rest=ok.filter(it=>!W[it[0]].kpi),kw=kp.length?Math.max(3,Math.floor(12/kp.length)):3;
  /* real data leads; what waits on data is one compact strip at the bottom, never a hero card */
  return fixedGrid([...kp.map(it=>[it[0],kw,1]),...rest])+comingCard(off)}
function comingCard(off){if(!off.length)return '';const seen=new Map();off.forEach(it=>{const r=gate(W[it[0]].needs).t;if(!seen.has(r))seen.set(r,[]);seen.get(r).push(W[it[0]].title())});
  return `<section class="card coming" aria-labelledby="coming-h"><div class="ch"><span class="gi wait">${ICON.clock}</span><div><h2 id="coming-h">${t('comingT')}</h2><p class="muted">${t('comingP')}</p></div></div>
   <ul class="clist">${[...seen].map(([r,ws])=>`<li><b>${esc(ws.join(' · '))}</b><span>${esc(r)}</span></li>`).join('')}</ul>
   <p class="cnext">${t('comingNext')}</p>
   <p class="cnow"><span class="muted">${t('useNow')}</span> <a href="#/explorer">${t('nExplorer')}</a> · <a href="#/pricing">${t('nPricing')}</a> · <a href="#/assortment">${t('nAssort')}</a> · <a href="#/coverage">${t('nCoverage')}</a></p></section>`}
function earlyList(n){const E=DS.early||[];if(!E.length)return DS.real?`<p class="muted xs">${t('noEarly')}</p>`:'';
  return `<div class="early"><div class="elab"><span class="badge b-butter">${t('earlyLabel')(E[0].at?fmtD(new Date(E[0].at)):cutoffShort())}</span><span class="muted xs">${t('earlyNote')}</span></div><ul>${E.slice(0,n).map(e=>`<li>${thumb(e.p)}<span class="fx"><b>${esc(e.p.brand)}</b><span class="muted">${esc(e.p.name)}${e.size?` · ${e.size} ${e.p.unit}`:''}</span></span><span class="num">${aed(e.price)}</span></li>`).join('')}</ul></div>`}
function retCov(k){const r=DS.rets[k]||{};const n=PRODUCTS.filter(p=>p.listed[k]).length;return {n,est:r.catalogEstimate||null,pc:r.catalogEstimate?Math.min(100,n/r.catalogEstimate*100):null}}
function covText(k){const c=retCov(k);return c.est?t('covObs')(fmtN(c.n),fmtN(c.est),c.pc.toFixed(0)):t('covObsN')(fmtN(c.n))}
function retBanner(){if(!DS.real||RR.every(k=>retOk(k)&&retStatus(k)==='ok'))return '';
  return `<div class="statusrow" role="status">${RR.map(k=>`<span class="rstat ${!retOk(k)?'bad':retStatus(k)==='partial'?'warn':'ok'}"><span class="rdot" style="--c:${RC(k)}">${RN(k)}</span><span class="st">${retShort(k)}</span>${info(retDetail(k))}</span>`).join('')}${S.route!=='coverage'?`<a class="linkbtn" href="#/coverage">${t('details')}</a>`:''}</div>`}

/* ---------- navigation & shell ---------- */
const NAV=[['dashboard','nDash'],['explorer','nExplorer'],['pricing','nPricing'],['promotions','nPromo'],['assortment','nAssort'],['availability','nAvail'],['compare','nCompare'],['assistant','nAssistant'],['coverage','nCoverage']];
const NAVICO={dashboard:'M3 3h6v8H3zM11 3h6v5h-6zM11 10h6v7h-6zM3 13h6v4H3z',explorer:'M3 3h6v6H3zM11 3h6v6h-6zM3 11h6v6H3zM11 11h6v6h-6z',pricing:'M3 16l4-5 3 3 7-9',promotions:'M4 4h12v12H4zM4 8h12M8 4v12',assortment:'M3 4h14M3 8h14M3 12h14M3 16h14M7 3v14M12 3v14',availability:'M3 10h3l2-5 4 10 2-5h3',compare:'M3 4h6v12H3zM11 4h6v12h-6z',assistant:'M4 4h12v9H9l-4 3v-3H4z',coverage:'M10 3l6 3v4c0 4-3 6-6 7-3-1-6-3-6-7V6z'};
function shell(inner){const hosted=!!APP.hosted;
  return `<a class="skip" href="#main">${t('skip')}</a><div class="app">
  <aside class="side"><div class="brandmark"><span class="logo" aria-hidden="true"><i></i><i></i></span><div><b>${t('appName')}</b><span>${t('appSub')}</span></div></div>
   <nav class="nav" aria-label="${t('primary')}">${NAV.map(([r,k])=>`<a href="#/${r}" ${S.route===r||(r==='explorer'&&S.route==='product')?'aria-current="page"':''}><svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true"><path d="${NAVICO[r]}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg><span>${t(k)}</span>${r==='compare'&&S.pins.length?`<span class="cnt">${S.pins.length}</span>`:''}</a>`).join('')}</nav>
   <div class="sidefoot"><div class="dsinfo"><span class="muted xs">${t('dataset')}</span><b class="xs">${DS.real?(DS.meta.test?t('testFixture'):t('snapshot')):t('sampleData')}</b></div>${!APP.hosted?`<div class="dsswitch" role="group" aria-label="${t('previewDataset')}"><span class="muted xs">${t('previewDataset')}</span><button data-fixture="0" aria-pressed="${!DS.real}">${t('dsSample')}</button><button data-fixture="1" aria-pressed="${DS.real&&!DS.rOk.u}">${t('dsFixture')}</button><button data-fixture="2" aria-pressed="${DS.real&&DS.rOk.u}">${t('dsFixtureP')}</button></div>`:''}</div></aside>
  <div class="mainwrap"><header class="topbar"><div class="crumbs">${crumbs()}</div>${dataLabel()}<span class="spacer"></span>
   <button class="btn ghost sm" id="langbtn" lang="${S.lang==='en'?'ar':'en'}">${S.lang==='en'?'العربية':'English'}</button>${hosted?`<span class="who muted xs">${esc(APP.email||'')}</span><button class="btn ghost sm" data-signout>${t('signOut')}</button>`:''}</header>
   <main class="main" id="main" tabindex="-1">${retBanner()}${inner}</main></div></div>
  ${tray()}${drawer()}${S.toast?`<div class="toast" role="status">${esc(S.toast)}</div>`:''}`}
function crumbs(){const r=S.route;if(r==='product'){const p=byId[S.param];return `<a href="#/explorer">${t('nExplorer')}</a><span aria-hidden="true">/</span><span>${p?esc(p.brand+' '+p.name):t('notFound')}</span>`}
  const n=NAV.find(x=>x[0]===r);return `<span>${n?t(n[1]):''}</span>`}
function pagehead(title,sub,right){return `<div class="pagehead"><div><h1>${title}</h1>${sub?`<p>${sub}</p>`:''}</div>${right?`<div class="phr">${right}</div>`:''}</div>`}
function tray(){if(!S.pins.length)return '';const P=S.pins.map(id=>byId[id]).filter(Boolean);
  return `<div class="tray" role="region" aria-label="${t('compareTray')}"><span class="tl">${t('compareTray')} <span class="muted num">${P.length}/4</span></span><div class="tps">${P.map(p=>`<div class="tp">${thumb(p)}<span class="tpn"><b>${esc(p.brand)}</b><span>${esc(clip(p.name,26))}</span></span><button class="iconbtn" data-pin="${p.id}" aria-label="${t('unpin')}: ${esc(p.name)}">${ICON.x}</button></div>`).join('')}${P.length<4?`<a class="tp add" href="#/explorer">${ICON.plus} ${t('addProduct')}</a>`:''}</div><a class="btn primary sm" href="#/compare">${t('compareN')(P.length)}</a><button class="linkbtn" data-clearpins>${t('clear')}</button></div>`}

/* ---------- dashboard ---------- */
function vDashboard(){const v=viewById(S.viewId);const own=!v.preset;
  const tabs=`<div class="viewbar"><div class="tabs" role="tablist" aria-label="${t('savedViews')}">${allViews().map(x=>`<button role="tab" aria-selected="${x.id===S.viewId}" data-view="${x.id}">${esc(L(x.name))}${x.id===S.viewId&&S.dirty?'<span class="dirty" aria-label="unsaved">•</span>':''}</button>`).join('')}</div>
   <div class="vact">${S.edit?`<button class="btn sm" data-addw>${ICON.plus} ${t('addWidget')}</button>
     <label class="sel sm"><span class="muted xs">${t('preview')}</span><select id="prevsel" data-preview aria-label="${t('previewState')}">${['live','loading','stale','empty'].map(x=>`<option value="${x}" ${S.preview===x?'selected':''}>${t('pv')[x]}</option>`).join('')}</select></label>
     <button class="btn sm" data-resetview ${S.dirty?'':'disabled'}>${t('discard')}</button>${own?`<button class="btn sm" data-delview>${t('deleteView')}</button>`:''}${own?`<button class="btn sm" data-save>${t('save')}</button>`:''}<button class="btn sm" data-saveas>${t('saveAs')}</button><button class="btn sm primary" data-edit>${t('doneEdit')}</button>`
     :`${S.dirty?`<button class="btn sm" data-saveas>${t('saveAs')}</button>`:''}<button class="btn sm" data-edit>${t('customize')}</button>`}</div></div>
   ${S.saveAs?`<form class="saveas" data-saveform><label for="vname">${t('viewName')}</label><input id="vname" required maxlength="40" value="${esc(L(v.name)+(v.preset?' · '+t('copy'):''))}"><button class="btn sm primary" type="submit">${t('save')}</button><button class="btn sm" type="button" data-cancelsave>${t('cancel')}</button></form>`:''}`;
  const grid=DS.real&&!S.edit&&S.layout.length?pageGrid(S.layout,DASH_ALTS):S.layout.length?`<div class="dgrid${S.edit?' edit':''}" id="dgrid">${S.layout.map((it,i)=>widget(it,i,S.edit)).join('')}</div>`:`<div class="wempty big"><b>${t('noWidgets')}</b><span>${t('noWidgetsP')}</span><button class="btn primary" data-addw>${ICON.plus} ${t('addWidget')}</button></div>`;
  return pagehead(t('nDash'),DS.real?t('dashSubReal'):t('dashSub'))+tabs+filterBar()+(S.edit?`<p class="edithint muted xs">${t('editHint')}</p>`:'')+grid}
/* What a dashboard tab shows from today's snapshot when its own widgets wait on data. */
const DASH_ALTS=[['kpiCatalog',3,1],['kpiMedPrice',3,1],['kpiBrands',3,1],['kpiRating',3,1],['ladder',12,4],['bandgrid',12,5],['cattbl',12,4],['brandtbl',12,5]];
function fixedGrid(items){return `<div class="dgrid">${items.map((it,i)=>widget(it,'f'+i,false)).join('')}</div>`}
function vPricing(){return pagehead(t('nPricing'),t('pricingSub'))+filterBar()+pageGrid([['kpiIndex',3,1],['kpiGap',3,1],['kpiMatched',3,1],['kpiCatalog',3,1],['index',12,3],['gapdist',5,3],['gaps',7,3],['ladder',12,4]],[['kpiMedPrice',3,1],['kpiBrands',3,1],['kpiRating',3,1],['bandgrid',12,5],['cattbl',12,4],['brandtbl',12,5]])}
function vPromotions(){return pagehead(t('nPromo'),t('promoSub'))+filterBar()+pageGrid([['promocal',12,3],['promoheat',6,3],['promodepth',6,3]],[['kpiCatalog',3,1],['kpiMedPrice',3,1],['bandgrid',12,5]])+markdownCard()}
function vAssortment(){return pagehead(t('nAssort'),t('assortSub'))+filterBar()+pageGrid([['matrix',12,4],['shades',12,3]],[['shadetop',12,5],['brandtbl',12,5]])+exclusives()}
function vAvailability(){return pagehead(t('nAvail'),t('availSub'))+filterBar()+pageGrid([['avail',12,3],['stockouts',6,3],['feed',6,3],['packsize',12,3]],[['kpiCatalog',3,1],['kpiBrands',3,1],['cattbl',12,4]])}
function markdownCard(){const c=ctx();const g=gate({history:1,caps:['promotions']});if(g&&DS.real)return '';
  let body;if(g)body=gateState(g);else{const rows=[];c.P.forEach(p=>RR.forEach(k=>{if(!S.ret.has(k)||!retOk(k))return;const pr=promoAt(p,k,c.b);if(!pr)return;const now=priceAt(p,k,c.b),reg=regAt(p,k,c.b);const d0=Math.max(0,c.b-30),ref=regAt(p,k,d0)||priceAt(p,k,d0);if(!now||!ref)return;
    const tru=(1-now/ref)*100;rows.push({p,k,pr,now,reg,ref,tru,diff:pr-tru})}));
   body=rows.length?table('mkd',[{k:'p',label:t('product'),f:x=>pcell(x.p),v:x=>x.p.brand},{k:'k',label:t('retailer'),f:x=>`<span class="rdot" style="--c:${RC(x.k)}">${RN(x.k)}</span>`},{k:'pr',label:t('stated'),align:'r',f:x=>`${x.pr}%`,v:x=>x.pr},{k:'ref',label:t('ref30'),align:'r',f:x=>aed(x.ref),v:x=>x.ref},{k:'now',label:t('now'),align:'r',f:x=>aed(x.now),v:x=>x.now},{k:'tru',label:t('trueMd'),align:'r',f:x=>`<b>${x.tru.toFixed(0)}%</b>`,v:x=>x.tru},{k:'diff',label:t('overstated'),align:'r',f:x=>x.diff>2?`<span class="badge b-butter">${x.diff.toFixed(0)} ${t('pts')}</span>`:'<span class="muted">—</span>',v:x=>x.diff},{k:'e',label:'',f:x=>evBtn(x.p,x.k)}],rows,{sort:'diff',limit:8,text:x=>x.p.brand+' '+x.p.name,rowProd:x=>x.p.id}):emptyState(t('noPromosNow'))}
  return `<section class="card mt"><header class="wh"><div class="wt"><h3>${t('mdTitle')}</h3><p>${t('mdSub')}</p></div></header>${body}</section>`}
function exclusives(){const c=ctx();if(DS.real&&!bothOk())return '';
  const col=k=>{const o=k==='u'?'s':'u';const P=c.P.filter(p=>p.listed[k]&&!p.listed[o]);const B=[...new Set(P.map(p=>p.brand))].map(b=>[b,P.filter(p=>p.brand===b).length]).sort((a,b)=>b[1]-a[1]);
   return `<section class="card"><header class="wh"><div class="wt"><h3>${t('onlyAt')(RN(k))}</h3><p>${t('onlyAtSub')(P.length,B.length)}</p></div></header>${B.length?`<ul class="blist">${B.map(([b,n])=>`<li><button class="linkbtn" data-fbrand="${esc(b)}">${esc(b)}</button><span class="bar"><i style="width:${n/B[0][1]*100}%;background:${RC(k)}"></i></span><span class="num muted">${n}</span></li>`).join('')}</ul>`:emptyState()}</section>`};
  return `<div class="grid g2 mt">${col('u')}${col('s')}</div>`}

/* ---------- explorer ---------- */
const SORTS=['gap','priceAsc','priceDesc','brand','shades','newest'];
function exRows(){const c=ctx();let P=c.P;const q=S.ex.q.trim().toLowerCase();if(q)P=P.filter(p=>(p.brand+' '+p.name+' '+t('cat')[p.cat]).toLowerCase().includes(q));
  const g=p=>gapOf(p,c.b,'exact'),m=p=>minCur(p,c.b);
  const sorters={gap:(a,b)=>(Math.abs(g(b)??-1))-(Math.abs(g(a)??-1)),priceAsc:(a,b)=>(m(a)??1e9)-(m(b)??1e9),priceDesc:(a,b)=>(m(b)??-1)-(m(a)??-1),brand:(a,b)=>a.brand.localeCompare(b.brand)||a.name.localeCompare(b.name),shades:(a,b)=>Math.max(b.shadeCount.u,b.shadeCount.s)-Math.max(a.shadeCount.u,a.shadeCount.s),newest:(a,b)=>Math.max(b.first.u??-1,b.first.s??-1)-Math.max(a.first.u??-1,a.first.s??-1)};
  return [...P].sort(sorters[S.ex.sort]||sorters.brand)}
function priceRow(p,k,d){if(DS.real&&!retOk(k))return `<div class="prow na"><span class="rdot" style="--c:${RC(k)}">${RN(k)}</span><span class="muted xs">${t('awaitingShort')}</span></div>`;
  if(!listedAt(p,k,d))return `<div class="prow na"><span class="rdot" style="--c:${RC(k)}">${RN(k)}</span><span class="muted xs">${t('notListed')}</span></div>`;
  const pr=promoAt(p,k,d),reg=regAt(p,k,d),v=priceAt(p,k,d);
  return `<div class="prow"><span class="rdot" style="--c:${RC(k)}">${RN(k)}</span><span class="num"><b>${aed(v)}</b>${pr&&reg&&reg>v?` <s class="muted">${aed(reg)}</s>`:''}</span>${pr?`<span class="badge b-blush xs">−${pr}%</span>`:''}</div>`}
function pcard(p,d){const g=gapOf(p,d,'exact'),gu=gapOf(p,d,'unit');const sh=p.shades.slice(0,6);const sc=Math.max(p.shadeCount.u,p.shadeCount.s);
  return `<article class="pcard"><a class="pimg" href="#/product/${p.id}" aria-label="${esc(p.brand+' '+p.name)}">${pic(p)}</a>
   <div class="pbody"><div class="bn">${esc(p.brand)}</div><a class="pn" href="#/product/${p.id}">${esc(p.name)}</a><div class="muted xs">${t('cat')[p.cat]} · ${szT(p.size.u||p.size.s,p)}${p.size.u&&p.size.s&&p.size.u!==p.size.s?` / ${szT(p.size.s,p)}`:''}</div>
   <div class="prices">${RR.map(k=>priceRow(p,k,d)).join('')}</div>
   <div class="pfoot">${g!=null?`<span ${tipAttr([t('gapExplain')])}>${t('gap')} ${gapSpan(g)}</span>`:gu!=null?`<span ${tipAttr([t('unitGapExplain')])}>${t('perUnitShort')} ${gapSpan(gu)}</span>`:'<span></span>'}
   ${sh.length?`<span class="swatches" aria-label="${sc} ${t('shadesW')}">${sh.map(h=>`<i style="background:${h}"></i>`).join('')}${sc>6?`<span class="muted xs">+${sc-6}</span>`:''}</span>`:''}${pinBtn(p)}</div></div></article>`}
function vExplorer(){const c=ctx();if(DS.real&&!bothOk()&&S.ex.sort==='gap')S.ex.sort='brand';const rows=exRows();const shown=rows.slice(0,S.ex.limit);
  const tools=`<div class="toolbar"><label class="search"><svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M11 11l3.5 3.5" stroke="currentColor" stroke-width="1.6"/></svg><input type="search" id="exq" data-exq value="${esc(S.ex.q)}" placeholder="${t('searchProducts')}" aria-label="${t('searchProducts')}"></label>
   <label class="sel"><span class="muted xs">${t('sortBy')}</span><select id="exsort" data-exsort>${SORTS.filter(s=>s!=='gap'||!DS.real||bothOk()).map(s=>`<option value="${s}" ${S.ex.sort===s?'selected':''}>${t('sorts')[s]}</option>`).join('')}</select></label>
   ${seg('exmode',[['grid',t('grid')],['table',t('tableV')]],S.ex.mode)}<span class="spacer"></span><span class="muted xs num" aria-live="polite">${t('rowsOf')(shown.length,rows.length)}</span></div>`;
  let body;if(!rows.length)body=emptyState(S.ex.q?t('noSearch')(S.ex.q):null);
  else if(S.ex.mode==='grid')body=`<div class="pgrid">${shown.map(p=>pcard(p,c.b)).join('')}</div>`;
  else{S.tbl.ex={sort:null,dir:1,q:'',limit:S.ex.limit};body=table('ex',[{k:'p',label:t('product'),f:p=>pcell(p,t('cat')[p.cat])},...RR.filter(k=>S.ret.has(k)).map(k=>({k,label:RN(k),align:'r',f:p=>DS.real&&!retOk(k)?`<span class="muted xs">${t('awaitingShort')}</span>`:listedAt(p,k,c.b)?`${aed(priceAt(p,k,c.b))}${promoAt(p,k,c.b)?` <span class="badge b-blush xs">−${promoAt(p,k,c.b)}%</span>`:''}`:`<span class="muted xs">${t('notListed')}</span>`})),
    {k:'g',label:t('gap'),align:'r',f:p=>gapSpan(gapOf(p,c.b,'exact'))},{k:'sz',label:t('size'),align:'r',f:p=>`${szT(p.size.u||p.size.s,p)}`},{k:'sh',label:t('shadesW'),align:'r',f:p=>Math.max(p.shadeCount.u,p.shadeCount.s)||'—'},{k:'pin',label:'',f:p=>pinBtn(p)}],shown,{filter:false,rowProd:p=>p.id})}
  return pagehead(t('nExplorer'),t('explorerSub'))+filterBar().replace('class="fbtn','class="exfb fbtn')+`<div class="exwrap"><aside class="frail" aria-label="${t('filters')}"><div class="frh"><h2>${t('filters')}</h2>${Object.values(S.f).some(x=>x.size)?`<button class="linkbtn" data-fclearall>${t('clear')}</button>`:''}</div>${filterPanel('r')}</aside><div class="exmain">`+(DS.real&&DS.early.length?`<section class="card mb">${earlyList(8)}</section>`:'')+tools+body+(rows.length>shown.length?`<div class="tmore"><button class="btn" data-exmore>${t('showMore')(Math.min(36,rows.length-shown.length))}</button></div>`:'')+'</div></div>'}

/* ---------- product page ---------- */
function vProduct(){const p=byId[S.param];if(!p)return pagehead(t('notFound'),'')+`<div class="wempty big"><b>${t('notFoundT')}</b><span>${t('notFoundP')}</span><a class="btn" href="#/explorer">${t('backExplorer')}</a></div>`;
  const b=DAYS-1;const views=[...(p.img?[['photo',pic(p)]]:[]),['detail',productSVG(p,'','detail')],['card',productSVG(p,'')]];if(p.shades.length)views.push(['shades',productSVG(p,'','shades')]);const gi=Math.min(S.gal,views.length-1);
  const gal=`<div class="gallery"><div class="gmain">${views[gi][1]}</div><div class="gthumbs" role="tablist" aria-label="${t('images')}">${views.map((v,i)=>`<button role="tab" aria-selected="${i===gi}" data-gal="${i}" aria-label="${t('galN')[v[0]]}">${v[1]}</button>`).join('')}</div><p class="muted xs">${views[gi][0]==='photo'?t('photoNote')(RN(p.img.includes(IMG_HOSTS.u)?'u':'s')):t('renderNote')}</p></div>`;
  const offer=k=>{if(DS.real&&!retOk(k))return `<div class="offer na"><h3><span class="rdot" style="--c:${RC(k)}">${RN(k)}</span></h3><span class="gl"><b>${retShort(k)}</b>${info(retDetail(k))}</span></div>`;
   if(heldAt(p,k,b))return `<div class="offer na"><h3><span class="rdot" style="--c:${RC(k)}">${RN(k)}</span></h3><b>${t('priceReview')}</b></div>`;
   if(!p.listed[k]||!listedAt(p,k,b))return `<div class="offer na"><h3><span class="rdot" style="--c:${RC(k)}">${RN(k)}</span></h3><b>${t('notListedAt')(RN(k))}</b><p class="muted">${p.listed[k]?t('delistedOn')(fmtD(dayDate(p.last[k]+1))):t('notCarried')}</p></div>`;
   const v=priceAt(p,k,b),reg=regAt(p,k,b),pr=promoAt(p,k,b),st=stockAt(p,k,b);
   return `<div class="offer"><h3><span class="rdot" style="--c:${RC(k)}">${RN(k)}</span>${p.sku[k]?`<span class="muted xs mono">${esc(p.sku[k])}</span>`:''}</h3><div class="big num">${aed(v)}${pr&&reg>v?` <s class="muted">${aed(reg)}</s>`:''}</div>
    <dl class="kv"><dt>${t('size')}</dt><dd class="num">${szT(sizeAt(p,k,b),p)}</dd><dt>${t('unitPrice')}</dt><dd class="num">${unitAt(p,k,b)==null?'—':`${aed(unitAt(p,k,b),2)} / ${p.unit}`}</dd>
    <dt>${t('promo')}</dt><dd>${DS.caps.promotions?(pr?`<span class="badge b-blush">−${pr}%</span>`:t('none')):`<span class="muted">${t('fs')[DS.fieldStatus.promo||'not_collected']}</span>`}</dd>
    <dt>${t('stockL')}</dt><dd>${st<0?`<span class="muted">${t('fs')[DS.fieldStatus.stock||'not_collected']}</span>`:stockTag(st)}</dd>
    <dt>${t('shadesW')}</dt><dd class="num">${p.shadeCount[k]||'—'}</dd><dt>${t('rating')}</dt><dd class="num">${p.rating[k]?`${p.rating[k][0]} · ${fmtN(p.rating[k][1])} ${t('reviews')}`:'—'}</dd></dl>${evBtn(p,k,t('seeEvidence'))}</div>`};
  let hist='';if(DAYS>1){const [a]=S.range;const series=RR.filter(k=>p.d[k]&&retOk(k)).map(k=>({name:RN(k),color:RC(k),dash:k==='s',vals:p.d[k].price}));const bands=NOT_OBS.filter(n=>!n.cats||n.cats.includes(p.cat)).map(n=>({a:n.a,b:n.b,label:RN(n.r)+': '+L(n.why)}));
    hist=`<section class="card"><header class="wh"><div class="wt"><h3>${t('priceHistory')}</h3><p>${t('priceHistSub')}</p></div><div class="wa">${[30,90,180].map(n=>`<button class="btn xs" data-range="${n}" aria-pressed="${S.range[1]-S.range[0]+1===n}">${t('lastN')(n)}</button>`).join('')}</div></header>
     <div class="chart">${lineChart({id:'ph',w:760,h:240,a:S.range[0],b:S.range[1],series,fmt:v=>aed(v),title:t('priceHistory'),bands,brush:true})}</div><div class="chart ctxwrap">${contextStrip({id:'phc',w:760,vals:(series[0]||{}).vals||[],a:S.range[0],b:S.range[1]})}</div>
     <div class="wfoot">${legendUS(true)}<span class="muted xs">${t('brushHint')}</span></div>
     ${lanes(p)}</section>`}
  else hist=`<section class="card">${gateState({t:t('needsHistory'),m:t('needsHistoryP')(cutoffShort())})}</section>`;
  const promos=p.promos.filter(x=>retOk(x.r)).sort((a,b)=>b.a-a.a);
  const match=`<section class="card"><header class="wh"><div class="wt"><h3>${t('matchT')}</h3></div></header>${p.match?`<dl class="kv"><dt>${t('method')}</dt><dd>${esc(p.match[0])}</dd><dt>${t('confidence')}</dt><dd class="num">${(p.match[1]*100).toFixed(0)}%</dd><dt>${t('stage')}</dt><dd>${esc(p.match[2]==='first-pass'?t('firstPass'):t('reviewedMatches'))}</dd><dt>${t('matchClassL')}</dt><dd>${t('mcName')[p.match[3]]||esc(p.match[3])}</dd><dt>${t('reviewL')}</dt><dd>${rsBadge(p.match[4])}</dd><dt>${t('sizeCheck')}</dt><dd>${p.sameSize?t('sameSize'):t('diffSize')(p.size.u,p.size.s,p.unit)}</dd></dl>`:`<p class="muted">${DS.real&&!bothOk()?t('awaitingR')(RN('u')):t('singleRetailer')}</p>`}</section>`;
  return `<div class="pagehead"><div><div class="bn">${esc(p.brand)}</div><h1>${esc(p.name)}</h1><p>${t('cat')[p.cat]} · ${szT(p.size.u||p.size.s,p)}</p></div><div class="phr">${pinBtn(p,true)}</div></div>
   <div class="prodgrid">${gal}<div class="offers">${RR.map(offer).join('')}</div></div>
   <div class="grid g-8-4 mt">${hist}<div class="stack">${match}<section class="card"><header class="wh"><div class="wt"><h3>${t('promoHist')}</h3></div></header>${!DS.caps.promotions?gateState(gate({caps:['promotions']})||{t:'',m:''}):promos.length?`<ul class="plist">${promos.map(x=>{const cp=CAMPAIGNS.find(c=>c.id===x.c);return `<li><span class="rdot" style="--c:${RC(x.r)}">${RN(x.r)}</span><span>${cp?esc(L(cp.name)):t('promo')}</span><span class="muted xs num">${fmtD(dayDate(x.a))} – ${fmtD(dayDate(x.b))}</span><b class="num">−${x.pct}%</b></li>`}).join('')}</ul>`:`<p class="muted">${t('noPromoHist')}</p>`}</section></div></div>`}
function lanes(p){const [a,b]=S.range;const W_=760,l=86,r=14,n=b-a+1,x=d=>l+(d-a)/n*(W_-l-r);const ks=RR.filter(k=>p.d[k]&&retOk(k)&&p.d[k].stock);if(!ks.length)return '';
  const col={0:'transparent',1:'#CDEBDC',2:'#F5E6B3',3:'#F2C6D1',4:'url(#hatch)'};let s=`<svg viewBox="0 0 ${W_} ${ks.length*22+6}" role="img" aria-label="${t('stockL')}">${HATCH}`;
  ks.forEach((k,j)=>{const y=j*22+3;s+=`<text x="0" y="${y+13}" font-size="11" fill="#3C434B">${RN(k)}</text>`;let i=a;while(i<=b){const st=p.d[k].stock[i];let e=i;while(e+1<=b&&p.d[k].stock[e+1]===st)e++;
    if(st)s+=`<rect x="${x(i)}" y="${y}" width="${Math.max(1.5,x(e+1)-x(i))}" height="16" rx="2" fill="${col[st]}" ${tipAttr([RN(k)+': '+t('stock')[['na','in','low','out','unk'][st]],`${fmtD(dayDate(i))} – ${fmtD(dayDate(e))}`])}/>`;i=e+1}});
  return `<div class="lanes"><h4>${t('stockL')}</h4><div class="chart">${s}</svg></div><div class="legend">${['in','low','out'].map((k,i)=>`<span><span class="sw" style="background:${col[i+1]}"></span>${t('stock')[k]}</span>`).join('')}<span><span class="hatchsw"></span>${t('stock').unk}</span></div></div>`}

/* ---------- compare ---------- */
const rsBadge=r=>`<span class="badge xs ${r==='accepted'?'b-mint':r==='proposed'?'b-lav':'b-butter'}">${t('rsName')[r]||esc(r||'')}</span>`;
function vCompare(){const P=S.pins.map(id=>byId[id]).filter(Boolean);const b=DAYS-1;
  if(!P.length)return pagehead(t('nCompare'),t('compareSub'))+`<div class="wempty big"><b>${t('compareEmpty')}</b><span>${t('compareEmptyP')}</span><a class="btn primary" href="#/explorer">${t('openExplorer')}</a></div>`;
  const cell=(p,k,f)=>DS.real&&!retOk(k)?`<span class="muted xs">${t('awaitingShort')}</span>`:listedAt(p,k,b)?f():`<span class="muted xs">${t('notListed')}</span>`;
  const bestOf=f=>{const v=P.map(f).filter(x=>x!=null);return v.length>1?Math.min(...v):null};
  const rows=[
   [t('image'),p=>`<a class="imgbox" href="#/product/${p.id}">${pic(p)}</a>`],
   [t('product'),p=>`<div class="bn">${esc(p.brand)}</div><a href="#/product/${p.id}" class="pn">${esc(p.name)}</a><div class="muted xs">${t('cat')[p.cat]}</div>`],
   ...RR.map(k=>{const best=bestOf(p=>retOk(k)&&listedAt(p,k,b)?unitAt(p,k,b):null);return [`${RN(k)} · ${t('price')}`,p=>cell(p,k,()=>`<b class="num">${aed(priceAt(p,k,b))}</b>${promoAt(p,k,b)?` <span class="badge b-blush xs">−${promoAt(p,k,b)}%</span>`:''}<div class="muted xs num ${unitAt(p,k,b)===best?'best':''}">${unitAt(p,k,b)==null?'—':`${aed(unitAt(p,k,b),2)}/${p.unit}`}${unitAt(p,k,b)===best?` · ${t('lowestUnit')}`:''}</div>`)]}),
   [t('gap'),p=>DS.real&&!bothOk()?`<span class="muted xs">${t('awaitingShort')}</span>`:gapSpan(gapOf(p,b,'exact'))+(gapOf(p,b,'exact')==null&&gapOf(p,b,'unit')!=null?` <span class="muted xs">${t('perUnitShort')} ${pct(gapOf(p,b,'unit'))}</span>`:'')],
   [t('size'),p=>RR.filter(k=>p.listed[k]&&retOk(k)).map(k=>`<span class="num">${szT(p.size[k],p)}</span> <span class="muted xs">${RN(k)}</span>`).join('<br>')],
   [t('shadesW'),p=>RR.filter(k=>p.listed[k]&&retOk(k)).map(k=>`<span class="num">${p.shadeCount[k]||'—'}</span> <span class="muted xs">${RN(k)}</span>`).join('<br>')+(p.shades.length?`<div class="swatches">${p.shades.filter(h=>/^#[0-9a-f]{3,8}$/i.test(h)).slice(0,8).map(h=>`<i style="background:${h}"></i>`).join('')}</div>`:'')],
   [t('stockL'),p=>RR.filter(k=>p.listed[k]&&retOk(k)).map(k=>{const s=stockAt(p,k,b);return s<0?`<span class="muted xs">${t('fs')[DS.fieldStatus.stock||'not_collected']}</span>`:stockTag(s)}).join('<br>')],
   [t('rating'),p=>RR.filter(k=>p.rating[k]&&retOk(k)).map(k=>`<span class="num">${p.rating[k][0]}</span> <span class="muted xs">${fmtN(p.rating[k][1])} · ${RN(k)}</span>`).join('<br>')||'—'],
   [t('matchT'),p=>p.match?`${esc(p.match[0])} <span class="muted xs num">${(p.match[1]*100).toFixed(0)}%</span><div>${rsBadge(p.match[4])} <span class="muted xs">${t('mcName')[p.match[3]]||''}</span></div>`:`<span class="muted xs">${DS.real&&!bothOk()?t('awaitingShort'):t('singleRetailer')}</span>`],
   [t('evidence'),p=>RR.filter(k=>p.listed[k]&&retOk(k)).map(k=>evBtn(p,k,RN(k))).join(' · ')],
   ['',p=>`<button class="linkbtn" data-pin="${p.id}">${t('remove')}</button>`]];
  if(DAYS>1)rows.splice(4,0,[t('trend90'),p=>{const k=RR.find(k=>p.d[k]&&retOk(k));if(!k)return '—';const a=Math.max(0,b-89),v=p.d[k].price.slice(a,b+1).filter(x=>x!=null);if(v.length<2)return '—';const lo=Math.min(...v),hi=Math.max(...v)||1,w=140,h=30;
    return `<svg viewBox="0 0 ${w} ${h}" class="spark" role="img" aria-label="${t('trend90')}"><polyline fill="none" stroke="${RC(k)}" stroke-width="1.5" points="${v.map((x,i)=>`${(i/(v.length-1)*w).toFixed(1)},${(h-3-(hi===lo?.5:(x-lo)/(hi-lo))*(h-6)).toFixed(1)}`).join(' ')}"/></svg><div class="muted xs num">${aed(lo)} – ${aed(hi)} · ${RN(k)}</div>`}]);
  return pagehead(t('nCompare'),t('compareSub'))+`<div class="cmpwrap"><table class="cmp2"><tbody>${rows.map(([h,f])=>`<tr><th scope="row">${h}</th>${P.map(p=>`<td>${f(p)}</td>`).join('')}${P.length<4?`<td class="addc">${h===t('image')?`<a class="addcol" href="#/explorer">${ICON.plus}<span>${t('addProduct')}</span></a>`:''}</td>`:''}</tr>`).join('')}</tbody></table></div>`}

/* ---------- assistant: answers computed from the loaded dataset ---------- */
const QS=['gaps','promo','exclusive','index','stock','unit','forecast'];
function answer(q){const c=ctx();const b=c.b;const cites=[];const cite=(p,k,txt)=>{cites.push({p,k,txt});return `<button class="cite" data-ev="${p.id}" data-r="${k}" aria-label="${t('source')} ${cites.length}">${cites.length}</button>`};
  const need=n=>gate(n);let g,text,tool,cohort;
  switch(q){
   case 'gaps':{tool='compare';if((g=need({both:1})))break;const P=c.P.filter(p=>gapOf(p,b,'exact')!=null).sort((x,y)=>Math.abs(gapOf(y,b,'exact'))-Math.abs(gapOf(x,b,'exact'))).slice(0,3);cohort=t('cohortExact')(c.P.filter(p=>gapOf(p,b,'exact')!=null).length);
    text=P.length?`<p>${t('aGaps')}</p><ol>${P.map(p=>{const g=gapOf(p,b,'exact');return `<li><b>${esc(p.brand+' '+p.name)}</b> (${szT(p.size.u,p)}): ${t('ulta')} ${aed(priceAt(p,'u',b))}${cite(p,'u')} ${t('vs')} ${t('sephora')} ${aed(priceAt(p,'s',b))}${cite(p,'s')}, ${pct(g)} ${g>0?t('sephoraCheaperP'):t('ultaCheaperP')}.</li>`}).join('')}</ol>`:`<p>${t('noMatched')}</p>`;break}
   case 'promo':{tool='promotions';if((g=need({caps:['promotions']})))break;cohort=t('cohortListed');
    const parts=RR.filter(k=>retOk(k)&&S.ret.has(k)).map(k=>{const L_=c.P.filter(p=>listedAt(p,k,b));const on=L_.filter(p=>promoAt(p,k,b)>0);const deep=on.sort((x,y)=>promoAt(y,k,b)-promoAt(x,k,b))[0];
      return `<li><b>${RN(k)}</b>: ${t('aPromo')(on.length,L_.length,L_.length?(on.length/L_.length*100).toFixed(0):0,median(on.map(p=>promoAt(p,k,b))))}${deep?` ${t('deepest')}: ${esc(deep.brand+' '+deep.name)} −${promoAt(deep,k,b)}%${cite(deep,k)}`:''}</li>`});
    text=`<ul>${parts.join('')}</ul>${DS.real&&!bothOk()?`<p class="muted">${RN('u')}: ${retShort('u')}</p>`:''}`;break}
   case 'exclusive':{tool='assortment_gaps';if((g=need({both:1})))break;cohort=t('cohortListed');
    const f=k=>{const o=k==='u'?'s':'u';const P=c.P.filter(p=>p.listed[k]&&!p.listed[o]);const B=[...new Set(P.map(p=>p.brand))].map(x=>[x,P.filter(p=>p.brand===x)]).sort((x,y)=>y[1].length-x[1].length);return `<li>${t('onlyAt')(RN(k))}: <b class="num">${P.length}</b> ${t('products')}, ${B.length} ${t('brandsW')}. ${B.slice(0,3).map(([x,Q])=>`${esc(x)} (${Q.length})${cite(Q[0],k)}`).join(', ')}</li>`};
    text=`<ul>${f('u')}${f('s')}</ul>`;break}
   case 'index':{tool='index_trend';if((g=need({both:1,history:1})))break;const ix=indexSeries(c.P,c.a,c.b);cohort=t('basketN')(ix.n);
    text=ix.n?`<p>${t('aIndex')(fmtN(ix.rel[c.a],1),fmtD(dayDate(c.a)),fmtN(ix.rel[c.b],1),fmtD(dayDate(c.b)))}</p><p class="muted">${t('aIndexNote')}</p>`:`<p>${t('noBasket')}</p>`;
    if(ix.n){const p=ix.basket[0];text+=`<p class="muted xs">${t('example')}: ${esc(p.brand+' '+p.name)}${cite(p,'u')}${cite(p,'s')}</p>`}break}
   case 'stock':{tool='get_product';if((g=need({caps:['stock']})))break;cohort=t('cohortListed');const rows=[];c.P.forEach(p=>RR.forEach(k=>{if(retOk(k)&&S.ret.has(k)&&stockAt(p,k,b)===3)rows.push([p,k])}));
    text=rows.length?`<p>${t('aStock')(rows.length)}</p><ul>${rows.slice(0,5).map(([p,k])=>`<li>${esc(p.brand+' '+p.name)}: ${RN(k)} ${t('since')} ${fmtD(dayDate(outSince(p,k,b)))}${cite(p,k)}</li>`).join('')}</ul>`:`<p>${t('noStockouts')}</p>`;break}
   case 'unit':{tool='search_products';cohort=t('cohortCat')(t('cat').foundation);const rows=[];c.P.filter(p=>p.cat==='foundation').forEach(p=>RR.forEach(k=>{if(retOk(k)&&S.ret.has(k)&&unitAt(p,k,b)!=null)rows.push([p,k,unitAt(p,k,b)])}));rows.sort((x,y)=>x[2]-y[2]);
    text=rows.length?`<p>${t('aUnit')}</p><ol>${rows.slice(0,3).map(([p,k,u])=>`<li>${esc(p.brand+' '+p.name)} ${t('at')} ${RN(k)}: ${aed(priceAt(p,k,b))} / ${szT(p.size[k],p)} = <b>${aed(u,2)}/${p.unit}</b>${cite(p,k)}</li>`).join('')}</ol>`:`<p>${t('noRows')}</p>`;break}
   case 'forecast':{tool='—';cohort='—';text=`<p>${t('aForecast')}</p>`;break}}
  if(g)text=`<p><b>${esc(g.t)}</b></p>${g.m?`<p class="muted">${esc(g.m)}</p>`:''}`;
  return {text,cites,tool,cohort:cohort||'—'}}
function vAssistant(){const q=QS[S.ask]||QS[0];const a=answer(q);const f=activeFilterText();
  return pagehead(t('nAssistant'),DS.real?t('assistSubReal'):t('assistSub'))+`<div class="chat2"><div class="sugg" role="list">${QS.map((x,i)=>`<button role="listitem" class="chip${i===S.ask?' on':''}" data-ask="${i}" aria-pressed="${i===S.ask}">${t('q')[x]}</button>`).join('')}</div>
   <div class="thread"><div class="msg q"><span class="who">${t('you')}</span><p>${t('q')[q]}</p></div>
   <div class="msg a" aria-live="polite"><span class="who">${DS.real?t('computedAnswer'):t('assistantName')}</span>${a.text}
    <div class="meta-row"><span><b>${t('tool')}</b> <span class="mono">${a.tool}</span></span><span><b>${t('cohort')}</b> ${a.cohort}</span><span><b>${t('filtersW')}</b> ${f}</span><span><b>${t('cutoff')}</b> ${cutoffLong()}</span></div>
    ${a.cites.length?`<div class="srclist"><b class="xs">${t('sources')}</b>${a.cites.map((c,i)=>`<button class="src" data-ev="${c.p.id}" data-r="${c.k}"><span class="n">${i+1}</span>${esc(c.p.brand+' '+c.p.name)} · ${RN(c.k)} · ${aed(priceAt(c.p,c.k,DAYS-1))}</button>`).join('')}</div>`:''}</div></div>
   <p class="muted xs">${DS.real?t('assistFootReal'):t('assistFoot')}</p></div>`}
function activeFilterText(){const a=[];Object.entries(S.f).forEach(([k,s])=>s.forEach(v=>a.push(k==='cat'?t('cat')[v]:k==='shade'?t('fam')[v]:v)));if(S.sel)a.push(S.sel.label);return a.length?esc(a.join(', ')):t('noneF')}

/* ---------- coverage & data health ---------- */
function vCoverage(){const b=DAYS-1;const m=DS.meta;
  const ds=`<section class="card"><header class="wh"><div class="wt"><h3>${t('dsTitle')}</h3></div></header><dl class="kv"><dt>${t('dataset')}</dt><dd>${DS.real?(m.test?t('testFixture'):t('snapshot')):t('sampleData')} · <span class="mono">${esc(m.kind)}</span></dd><dt>${t('generated')}</dt><dd class="num">${esc(m.generatedAt||'—')}</dd><dt>${t('days')}</dt><dd class="num">${DAYS} (${esc(m.dates[0])} → ${esc(m.dates[m.dates.length-1])})</dd><dt>${t('products')}</dt><dd class="num">${PRODUCTS.length}</dd><dt>${t('schema')}</dt><dd class="mono">pi.dataset/v1</dd></dl></section>`;
  const rets=(m.retailers||[]).length?m.retailers:RR.map(k=>({id:k,name:RN(k),status:'ok'}));
  const src=SOURCES.length?`<table class="data"><thead><tr><th>${t('source')}</th><th>${t('status')}</th><th>${t('rung')}</th><th class="r">${t('coverageL')}</th><th class="r">${t('blockRate')}</th><th class="r">${t('quarantined')}</th><th>${t('lastRun')}</th></tr></thead><tbody>${SOURCES.map(s=>`<tr><td><b>${esc(s.name)}</b>${s.reason?`<div class="muted xs">${esc(L(s.reason))}</div>`:''}${s.warn?`<div class="muted xs">${esc(L(s.warn))}</div>`:''}</td><td><span class="badge ${s.status==='ok'?'b-mint':s.status==='warn'?'b-butter':'b-grey'}">${t('statusName')[s.status]||esc(s.status)}</span></td><td class="num">${s.rung!=null?`${s.rung} · ${esc(L(s.rungName))}`:'—'}</td><td class="r num">${s.cov!=null?s.cov+'%':'—'}</td><td class="r num">${s.block!=null?s.block+'%':'—'}</td><td class="r num">${s.quar??'—'}</td><td class="num">${esc(s.last||'—')}</td></tr>`).join('')}</tbody></table>`
   :`<table class="data"><thead><tr><th>${t('source')}</th><th>${t('status')}</th><th class="r">${t('products')}</th><th>${t('coverageL')}</th><th>${t('note')}</th></tr></thead><tbody>${rets.map(r=>`<tr><td><b>${esc(r.name||RN(r.id))}</b></td><td><span class="badge ${!r.status||r.status==='ok'?'b-mint':r.status==='blocked'?'b-blush':'b-butter'}">${t('statusName')[r.status||'ok']||esc(r.status)}</span>${r.since&&!isNaN(new Date(r.since))?`<div class="muted xs num">${t('since')} ${fmtD(new Date(r.since))}</div>`:''}</td><td class="r num">${PRODUCTS.filter(p=>p.listed[r.id]).length}${DS.early.filter(e=>e.k===r.id).length?` <span class="muted xs">+${DS.early.filter(e=>e.k===r.id).length} ${t('earlyShort')}</span>`:''}</td><td>${r.catalogEstimate?`<span class="bar sm"><i style="width:${retCov(r.id).pc}%;background:${RC(r.id)}"></i></span><span class="num xs">${esc(covText(r.id))}</span>`:`<span class="muted xs">${t('covNoEst')}</span>`}</td><td><span class="gl">${retShort(r.id)}${info(retDetail(r.id))}</span></td></tr>`).join('')}</tbody></table><p class="muted xs">${t('covExplain')}</p>`;
  const comp=k=>{const L_=PRODUCTS.filter(p=>listedAt(p,k,b));if(!L_.length)return null;const f=fn=>L_.filter(fn).length/L_.length*100;return {price:100,regular:f(p=>regAt(p,k,b)!=null),promo:DS.caps.promotions?100:null,stock:DS.caps.stock?f(p=>stockAt(p,k,b)>0):null,size:f(p=>sizeAt(p,k,b)!=null),shades:f(p=>p.shadeCount[k]>0||!['foundation','concealer','lips','cheek'].includes(p.cat)),rating:f(p=>!!p.rating[k])}};
  const fields=FIELDS.length?FIELDS.map(([f,u,s])=>[f,u,s,null]):FIELD_KEYS.map(f=>{const cu=retOk('u')?comp('u'):null,cs=retOk('s')?comp('s'):null;return [f,cu?cu[f]:null,cs?cs[f]:null,DS.fieldStatus[f]]});
  const bar=v=>v==null?'':`<span class="bar sm"><i style="width:${v}%;background:${v>=95?'#7CC4A2':v>=80?'#E5C465':'#E08BA0'}"></i></span>`;
  const fcell=(v,st,k)=>DS.real&&!retOk(k)?`<span class="muted xs">${t('awaitingShort')}</span>`:v!=null?`${bar(v)}<span class="num">${v.toFixed(1)}%</span>`:`<span class="muted xs">${t('fs')[st||'not_collected']}</span>`;
  const fieldT=`<table class="data"><thead><tr><th>${t('field')}</th><th>${t('ulta')}</th><th>${t('sephora')}</th></tr></thead><tbody>${fields.map(([f,u,s,st])=>`<tr><td>${t('fieldName')[f]||f}</td><td>${fcell(u,st,'u')}</td><td>${fcell(s,st,'s')}</td></tr>`).join('')}</tbody></table>`;
  const prec=PRECISION.length?`<table class="data"><thead><tr><th>${t('category')}</th><th class="r">${t('precision')}</th><th class="r">${t('lowerBound')}</th><th class="r">n</th></tr></thead><tbody>${PRECISION.map(([c,pt,lo,hi,n])=>`<tr><td>${t('cat')[c]}</td><td class="r num">${pt}%</td><td class="r num ${lo<98?'gap-pos':''}">${lo}%${lo<98?` <span class="badge b-butter xs">${t('belowTarget')}</span>`:''}</td><td class="r num">${n}</td></tr>`).join('')}</tbody></table><p class="muted xs">${t('precNote')}</p>`
   :DS.matchCheck?`<p class="big num">${(DS.matchCheck.correct/DS.matchCheck.checked*100).toFixed(1)}%</p><p>${t('matchCheckTxt')(DS.matchCheck.correct,DS.matchCheck.checked)}</p>${DS.matchCheck.note?`<p class="muted xs">${esc(L(DS.matchCheck.note))}</p>`:''}`
   :`${gateState(bothOk()?{t:t('matchNoCheck'),m:t('matchNoCheckP'),kind:'wait'}:{t:`${RN(retOk('u')?'s':'u')}: ${retShort(retOk('u')?'s':'u')}`,m:retDetail(retOk('u')?'s':'u'),kind:'bad'})}`;
  const quar=QUAR.length?`<ul class="qlist">${QUAR.map(q=>`<li><span class="badge b-butter">${esc(q.src)}</span><b>${esc(q.what)}</b><span>${esc(L(q.why))}</span><span class="muted xs num">${esc(q.when)}</span></li>`).join('')}</ul>`:`<p class="muted">${t('noQuar')}</p>`;
  const nobs=NOT_OBS.length?`<ul class="qlist">${NOT_OBS.map(n=>`<li><span class="rdot" style="--c:${RC(n.r)}">${RN(n.r)}</span><b class="num">${fmtD(dayDate(n.a))}${n.b>n.a?' – '+fmtD(dayDate(n.b)):''}</b><span>${esc(L(n.why))}</span></li>`).join('')}</ul>`:`<p class="muted">${t('noNotObs')}</p>`;
  const card=(h,sub,body)=>`<section class="card"><header class="wh"><div class="wt"><h3>${h}</h3>${sub?`<p>${sub}</p>`:''}</div></header>${body}</section>`;
  return pagehead(t('nCoverage'),t('coverageSub'))+`<div class="grid g-8-4">${card(t('sourcesT'),t('sourcesSub'),src)}${ds}</div><div class="grid g2 mt">${card(t('fieldsT'),DS.real?t('fieldsSubReal'):t('fieldsSub'),fieldT)}${card(t('precT'),t('precSub'),prec)}</div><div class="grid g2 mt">${card(t('quarT'),t('quarSub'),quar)}${card(t('notObsT'),t('notObsSub'),nobs)}</div>`}

/* ---------- drawers: drill-down, evidence, add widget ---------- */
const DRILL={
 index:{t:'kIndex',need:{both:1},cat:P=>{const ix=indexSeries(P,0,DAYS-1);return ix.n?[`${fmtN(ix.rel[DAYS-1],1)}`,`${ix.n}`]:null},ch:[()=>t('indexShort'),()=>t('basket')],prod:p=>p.sameSize&&listedAt(p,'u',DAYS-1)&&listedAt(p,'s',DAYS-1),pc:[[()=>t('ulta'),p=>aed(priceAt(p,'u',DAYS-1))],[()=>t('sephora'),p=>aed(priceAt(p,'s',DAYS-1))],[()=>t('gap'),p=>gapSpan(gapOf(p,DAYS-1,'exact'))]]},
 gap:{t:'kGap',need:{both:1},cat:P=>{const g=P.map(p=>gapOf(p,DAYS-1,'exact')).filter(x=>x!=null);return g.length?[pct(median(g)),`${g.length}`]:null},ch:[()=>t('median'),()=>'n'],prod:p=>gapOf(p,DAYS-1,'exact')!=null,pc:[[()=>t('ulta'),p=>aed(priceAt(p,'u',DAYS-1))],[()=>t('sephora'),p=>aed(priceAt(p,'s',DAYS-1))],[()=>t('gap'),p=>gapSpan(gapOf(p,DAYS-1,'exact'))]]},
 matched:{t:'kMatched',need:{both:1},cat:P=>{const b=P.filter(p=>p.listed.u&&p.listed.s).length;return [`${b}`,`${P.filter(p=>p.listed.u&&!p.listed.s).length}`,`${P.filter(p=>p.listed.s&&!p.listed.u).length}`]},ch:[()=>t('both'),()=>t('uOnly'),()=>t('sOnly')],prod:p=>!!p.match,pc:[[()=>t('method'),p=>esc(p.match[0])],[()=>t('confidence'),p=>`${(p.match[1]*100).toFixed(0)}%`]]},
 promo:{t:'kPromo',need:{caps:['promotions']},cat:P=>RR.filter(k=>retOk(k)).map(k=>`${P.filter(p=>promoAt(p,k,DAYS-1)>0).length}`),ch:RR.filter(k=>true).map(k=>()=>RN(k)),prod:p=>RR.some(k=>retOk(k)&&promoAt(p,k,DAYS-1)>0),pc:RR.map(k=>[()=>RN(k),p=>retOk(k)&&promoAt(p,k,DAYS-1)?`−${promoAt(p,k,DAYS-1)}%`:'—'])},
 stock:{t:'kStock',need:{caps:['stock']},cat:P=>RR.map(k=>`${P.filter(p=>stockAt(p,k,DAYS-1)===3).length}`),ch:RR.map(k=>()=>RN(k)),prod:p=>RR.some(k=>stockAt(p,k,DAYS-1)===3),pc:RR.map(k=>[()=>RN(k),p=>stockAt(p,k,DAYS-1)>0?stockTag(stockAt(p,k,DAYS-1)):'—'])},
 launch:{t:'kLaunch',need:{history:1},cat:P=>{const e=launchesIn(P,S.range[0],S.range[1]);return [`${e.filter(x=>x.type==='new').length}`,`${e.filter(x=>x.type==='gone').length}`]},ch:[()=>t('newL'),()=>t('delistedL')],prod:p=>launchesIn([p],S.range[0],S.range[1]).length>0,pc:[[()=>t('event'),p=>launchesIn([p],S.range[0],S.range[1]).map(e=>`${e.type==='new'?t('newAt')(RN(e.k)):t('goneAt')(RN(e.k))} · ${fmtD(dayDate(e.d))}`).join('<br>')]]},
 catalog:{t:'kCatalog',need:{},cat:P=>RR.map(k=>retOk(k)?`${P.filter(p=>listedAt(p,k,DAYS-1)).length}`:t('awaitingShort')),ch:RR.map(k=>()=>RN(k)),prod:p=>true,pc:RR.map(k=>[()=>RN(k),p=>retOk(k)&&listedAt(p,k,DAYS-1)?aed(priceAt(p,k,DAYS-1)):'—'])}};
function drawer(){const d=S.drawer;if(!d)return '';let title='',body='',foot='';
  if(d.type==='drill'){const D=DRILL[d.kpi];const c=ctx();title=t(D.t);const g=gate(D.need);
    const crumbsH=`<nav class="dcrumbs" aria-label="${t('drillPath')}"><button class="linkbtn" data-drillto="0">${t(D.t)}</button>${d.cat?`<span aria-hidden="true">›</span><span>${t('cat')[d.cat]}</span>`:''}</nav>`;
    if(g)body=gateState(g);
    else if(!d.cat){const cats=CATS.filter(k=>c.P.some(p=>p.cat===k));body=`<p class="muted">${t('drillStep1')}</p><table class="data"><thead><tr><th>${t('category')}</th>${D.ch.map(f=>`<th class="r">${f()}</th>`).join('')}<th></th></tr></thead><tbody>${cats.map(k=>{const v=D.cat(c.P.filter(p=>p.cat===k));return `<tr class="click" data-drillcat="${k}" tabindex="0"><td><b>${t('cat')[k]}</b></td>${D.ch.map((_,i)=>`<td class="r num">${v?v[i]??'—':'—'}</td>`).join('')}<td class="r">${ICON.arrow}</td></tr>`}).join('')}</tbody></table>`}
    else{const P=c.P.filter(p=>p.cat===d.cat&&D.prod(p));body=`<p class="muted">${t('drillStep2')}</p>`+(P.length?`<table class="data"><thead><tr><th>${t('product')}</th>${D.pc.map(([h])=>`<th class="r">${h()}</th>`).join('')}</tr></thead><tbody>${P.slice(0,60).map(p=>`<tr class="click" data-prod="${p.id}" tabindex="0"><td>${pcell(p)}</td>${D.pc.map(([,f])=>`<td class="r num">${f(p)}</td>`).join('')}</tr>`).join('')}</tbody></table>`:`<p class="muted">${t('noRows')}</p>`)}
    body=crumbsH+body}
  else if(d.type==='ev'){const p=byId[d.id],k=d.r;title=t('evidence');if(!p){body=`<p>${t('notFoundP')}</p>`}else{const b=DAYS-1,v=priceAt(p,k,b),reg=regAt(p,k,b),ev=p.ev&&p.ev[k]||{};
    body=`${pcell(p,`${RN(k)} · ${szT(p.size[k],p)}`)}<dl class="kv mt"><dt>${t('capturedText')}</dt><dd class="mono">${esc(ev.rawPrice||(v!=null?'AED '+v.toFixed(2):'—'))}</dd><dt>${t('parsedPrice')}</dt><dd class="num">${aed(v,2)}</dd><dt>${t('priceType')}</dt><dd>${promoAt(p,k,b)?t('ptPromo'):t('ptSelling')}${reg!=null?` · ${t('regular')} ${aed(reg,2)}`:''}</dd>
     <dt>${t('capturedAt')}</dt><dd class="num">${esc(ev.capturedAt||'—')}</dd><dt>${t('source')}</dt><dd>${esc(ev.source||RN(k))}</dd><dt>${t('runId')}</dt><dd class="mono">${esc(ev.runId||'—')}</dd><dt>${t('sku')}</dt><dd class="mono">${esc(p.sku[k]||'—')}</dd>${p.url[k]?`<dt>URL</dt><dd class="mono xs">${esc(p.url[k])}</dd>`:''}<dt>${t('qualityGate')}</dt><dd><span class="badge b-mint">${t('passed')}</span> <span class="muted xs">${t('gateRules')}</span></dd></dl>
     <div class="snap"><span class="muted xs">${t('snapNote')}</span></div>${DS.real?'':`<p class="note">${t('evSampleNote')}</p>`}`}}
  else if(d.type==='filters'){title=t('filters');body=filterPanel();foot=`<button class="linkbtn" data-fclearall ${Object.values(S.f).some(x=>x.size)?'':'disabled'}>${t('clear')}</button><button class="btn primary" data-close>${t('showN')(fmtN(ctx().P.length))}</button>`}
  else if(d.type==='add'){title=t('addWidget');const have=new Set(S.layout.map(x=>x[0]));const G=[['gKpi',['kpiIndex','kpiGap','kpiMatched','kpiPromo','kpiStock','kpiLaunch','kpiCatalog','kpiMedPrice','kpiBrands','kpiRating']],['gPrice',['index','gapdist','gaps','ladder','bandgrid','cattbl','brandtbl','packsize']],['gPromo',['promocal','promoheat','promodepth']],['gRange',['matrix','shades','shadetop','stockouts','avail','feed','early']]];
    body=G.map(([g,ks])=>`<h4 class="dh">${t(g)}</h4><ul class="addlist">${ks.map(k=>{const Wd=W[k];const gt=gate(Wd.needs);return `<li><div><b>${Wd.title()}</b><span class="muted xs">${Wd.sub?Wd.sub():t('kpiTile')}${gt?` · ${esc(gt.t)}`:''}</span></div><button class="btn sm" data-addk="${k}">${have.has(k)?t('addAgain'):t('add')}</button></li>`}).join('')}</ul>`).join('')}
  return `<div class="scrim" data-close></div><aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="dtitle"><header><h2 id="dtitle">${title}</h2><button class="iconbtn" data-close aria-label="${t('close')}">${ICON.x}</button></header><div class="dbody">${body}</div>${foot?`<footer class="dfoot">${foot}</footer>`:''}</aside>`}

/* ---------- render ---------- */
const VIEWS={dashboard:vDashboard,explorer:vExplorer,pricing:vPricing,promotions:vPromotions,assortment:vAssortment,availability:vAvailability,compare:vCompare,assistant:vAssistant,coverage:vCoverage,product:vProduct};
let lastRoute=null;
function render(){CTX=null;document.documentElement.lang=S.lang;document.documentElement.dir=S.lang==='ar'?'rtl':'ltr';
  const root=document.getElementById('root');
  if(APP.hosted&&APP.state!=='ready'){root.innerHTML=gateScreen();document.title=t('appName');return}
  const ae=document.activeElement,fid=ae&&ae.id,sel=fid&&ae.selectionStart!=null?[ae.selectionStart,ae.selectionEnd]:null;
  const sy=window.scrollY;const v=VIEWS[S.route]||vDashboard;const keepS=[...document.querySelectorAll('.dbody,.popl.tall')].map(x=>x.scrollTop);
  root.innerHTML=shell(v());
  const n=NAV.find(x=>x[0]===S.route);document.title=`${S.route==='product'&&byId[S.param]?byId[S.param].name:n?t(n[1]):t('appName')} · ${t('appName')}`;
  if(lastRoute!==location.hash){lastRoute=location.hash;window.scrollTo(0,0);const h=document.querySelector('.pagehead h1');if(h&&!fid){h.setAttribute('tabindex','-1');h.focus({preventScroll:true})}}
  else window.scrollTo(0,sy);
  if(fid){const el=document.getElementById(fid);if(el){el.focus({preventScroll:true});if(sel&&el.setSelectionRange)try{el.setSelectionRange(sel[0],sel[1])}catch(e){}}}
  [...document.querySelectorAll('.dbody,.popl.tall')].forEach((x,i)=>{if(keepS[i])x.scrollTop=keepS[i]});
  if(S.drawer){const d=document.querySelector('.drawer');if(d&&!d.contains(document.activeElement)){const f=d.querySelector('button,[tabindex="0"]');f&&f.focus()}}
  if(S.toast){clearTimeout(render.tt);render.tt=setTimeout(()=>{S.toast=null;const x=document.querySelector('.toast');x&&x.remove()},2600)}}
function route(){const h=location.hash.replace(/^#\/?/,'');const [r,...rest]=h.split('/');const known=r==='product'||r==='signin'||VIEWS[r];
  if(!known){location.replace('#/dashboard');return}
  if(r==='signin'&&APP.hosted&&APP.state==='ready'){location.replace('#/dashboard');return}
  S.route=r==='signin'?'dashboard':r;S.param=rest.join('/')?decodeURIComponent(rest.join('/')):null;if(r==='product')S.gal=0;S.pop=null;S.wmenu=null;S.drawer=null;render()}
function toast(m){S.toast=m}
function closeDrawer(){const f=S.drawer&&S.drawer.type==='filters';S.drawer=null;render();if(f){const b=document.getElementById('fb-open');b&&b.focus()}}
function markDirty(){S.dirty=true}
function persist(){try{localStorage.setItem(LS,JSON.stringify(S.views))}catch(e){}}
function setView(id){const v=viewById(id);S.viewId=v.id;S.layout=v.w.map(x=>x.slice());S.dirty=false;S.saveAs=false;
  if(v.f){S.f={brand:new Set(v.f.brand||[]),cat:new Set(v.f.cat||[]),band:new Set(v.f.band||[]),shade:new Set(v.f.shade||[])};S.sel=null}
  S.loading=true;render();setTimeout(()=>{S.loading=false;render()},320)}
function snapFilters(){return {brand:[...S.f.brand],cat:[...S.f.cat],band:[...S.f.band],shade:[...S.f.shade]}}

/* ---------- events ---------- */
window.onBrush=(a,b)=>{S.range=[a,b];render()};
function setSel(src,key,label,ids){if(S.sel&&S.sel.src===src&&S.sel.key===key)S.sel=null;else S.sel={src,key,label,ids:new Set(ids)};render()}
function act(v){const c=ctx();const [kind,...rest]=v.split(':');const P=c.src(kind==='gap'?'gapdist':kind==='lad'?'ladder':kind==='pc'?'promocal':kind==='heat'?'promoheat':kind==='mx'?'matrix':kind==='pd'?'promodepth':'');
  if(kind==='gap'){const i=+rest[0];setSel('gapdist',v,`${t('gap')} ${binLabel(i)}`,P.filter(p=>{const g=gapOf(p,c.b,S.gapMode);return g!=null&&binOf(g)===i}).map(p=>p.id))}
  else if(kind==='lad'){const k=rest[0];setSel('ladder',k,t('cat')[k],P.filter(p=>p.cat===k).map(p=>p.id))}
  else if(kind==='pc'){const cp=CAMPAIGNS.find(x=>x.id===rest[0]);setSel('promocal',rest[0],L(cp.name),P.filter(p=>p.promos.some(x=>x.c===cp.id)).map(p=>p.id))}
  else if(kind==='heat'){const [k,i,j]=[rest[0],+rest[1],+rest[2]];setSel('promoheat',v,`${RN(k)} · ${t('timesN')(FREQ[i])} · ${DEPTHB[j]}`,P.filter(p=>{const ws=promoWindows(p,k,c.a,c.b);return ws.length&&Math.min(3,ws.length-1)===i&&depthIdx(Math.max(...ws.map(x=>x.pct)))===j}).map(p=>p.id))}
  else if(kind==='mx'){const [b,k]=rest.join(':').split('|');setSel('matrix',b+'|'+k,`${b} · ${t('cat')[k]}`,P.filter(p=>p.brand===b&&p.cat===k).map(p=>p.id))}
  else if(kind==='pd'){const i=+rest[0];setSel('promodepth',v,`${t('discount')} ${DEPTHB[i]}`,P.filter(p=>RR.some(k=>retOk(k)&&promoAt(p,k,c.b)>0&&depthIdx(promoAt(p,k,c.b))===i)).map(p=>p.id))}}
function resetAll(){S.f={brand:new Set(),cat:new Set(),band:new Set(),shade:new Set()};S.sel=null;S.ret=new Set(RR.filter(retOk));S.range=[Math.max(0,DAYS-90),DAYS-1];S.preview='live';S.ex.q=''}
document.addEventListener('click',e=>{const el=e.target.closest('button,a,[data-act],[data-prod],[data-close],tr[data-drillcat],label');if(!el)return;const d=el.dataset;
  if(S.pop&&!e.target.closest('.fb')){S.pop=null;S.popq='';render();if(!d.pop&&!d.act)return}
  if(S.wmenu!=null&&!e.target.closest('.wctl')){S.wmenu=null;render()}
  if(el.id==='langbtn'){S.lang=S.lang==='en'?'ar':'en';try{localStorage.setItem('pi.lang',S.lang)}catch(x){}render();return}
  if(d.close!==undefined){closeDrawer();return}
  if(d.act){act(d.act);return}
  if(d.pop!==undefined){S.pop=S.pop===d.pop||!d.pop?null:d.pop;S.popq='';render();if(S.pop){const q=document.getElementById('pq-'+S.pop)||document.querySelector('.pop input');q&&q.focus()}else{const b=document.getElementById('fb-'+d.pop);b&&b.focus()}return}
  if(d.fdrawer!==undefined){S.drawer={type:'filters'};S.popq='';render();return}
  if(d.fclearall!==undefined){Object.values(S.f).forEach(x=>x.clear());if(S.edit||S.viewId)markDirty();render();return}
  if(d.fclear){S.f[d.fclear].clear();render();return}
  if(d.unf){S.f[d.unf].delete(d.v);render();return}
  if(d.setf){d.setf.split('|').forEach(x=>{const i=x.indexOf(':'),k=x.slice(0,i);if(i>0&&SETF_KEYS.includes(k))S.f[k]=new Set([x.slice(i+1)])});render();return}
  if(d.unsel!==undefined){S.sel=null;render();return}
  if(d.reset!==undefined){resetAll();render();return}
  if(d.ret){const k=d.ret;if(DS.real&&!retOk(k)){toast(`${RN(k)}: ${retShort(k)}`);render();return}if(S.ret.has(k)&&S.ret.size===1){toast(t('oneRetailer'));render();return}S.ret.has(k)?S.ret.delete(k):S.ret.add(k);render();return}
  if(d.range){const n=Math.min(+d.range,DAYS);S.range=[DAYS-n,DAYS-1];render();return}
  if(d.seg){const v=d.v;if(d.seg==='exmode'){S.ex.mode=v}else S[d.seg]=v;if(d.seg==='gapMode'&&S.sel&&S.sel.src==='gapdist')S.sel=null;render();return}
  if(d.pin){const i=S.pins.indexOf(d.pin);if(i>=0)S.pins.splice(i,1);else if(S.pins.length>=4){toast(t('trayFull'))}else{S.pins.push(d.pin);toast(t('pinnedT'))}render();return}
  if(d.clearpins!==undefined){S.pins=[];render();return}
  if(d.ev){S.drawer={type:'ev',id:d.ev,r:d.r};render();return}
  if(d.drill){S.drawer={type:'drill',kpi:d.drill,cat:null};render();return}
  if(d.drillcat){S.drawer.cat=d.drillcat;render();return}
  if(d.drillto!==undefined){S.drawer.cat=null;render();return}
  if(d.prod&&!e.target.closest('button:not([data-prod]),a')){location.hash='#/product/'+d.prod;return}
  if(d.tmore){S.tbl[d.tmore].limit+=20;render();return}
  if(d.sort){const st=S.tbl[d.sort];if(st.sort===d.k)st.dir*=-1;else{st.sort=d.k;st.dir=-1}render();return}
  if(d.exmore!==undefined){S.ex.limit+=36;render();return}
  if(d.gal){S.gal=+d.gal;render();return}
  if(d.ask){S.ask=+d.ask;render();return}
  if(d.fbrand){S.f.brand=new Set([d.fbrand]);location.hash='#/explorer';return}
  if(d.view){if(S.dirty&&!confirm(t('discardQ')))return;setView(d.view);return}
  if(d.edit!==undefined){S.edit=!S.edit;S.wmenu=null;if(!S.edit)S.preview='live';render();return}
  if(d.addw!==undefined){S.drawer={type:'add'};render();return}
  if(d.addk){const Wd=W[d.addk];S.layout.push([d.addk,Wd.dw,Wd.dh]);markDirty();S.drawer=null;toast(t('addedT')(Wd.title()));render();setTimeout(()=>{const x=document.querySelector(`[data-wi="${S.layout.length-1}"]`);x&&x.scrollIntoView({block:'center',behavior:'smooth'})},30);return}
  if(d.wmenu!==undefined){S.wmenu=S.wmenu===+d.wmenu?null:+d.wmenu;render();const m=document.querySelector('.menu button:not([disabled])');m&&m.focus();return}
  if(d.wact){const i=+d.i,L_=S.layout,it=L_[i],min=W[it[0]].minW||3;let ni=i;
    if(d.wact==='prev'&&i>0){L_.splice(i-1,0,L_.splice(i,1)[0]);ni=i-1}if(d.wact==='next'&&i<L_.length-1){L_.splice(i+1,0,L_.splice(i,1)[0]);ni=i+1}
    if(d.wact==='wider')it[1]=Math.min(12,it[1]+1);if(d.wact==='narrower')it[1]=Math.max(min,it[1]-1);if(d.wact==='taller')it[2]=Math.min(5,it[2]+1);if(d.wact==='shorter')it[2]=Math.max(1,it[2]-1);
    if(d.wact==='remove'){L_.splice(i,1);S.wmenu=null;toast(t('removedT'));markDirty();render();return}
    markDirty();S.wmenu=ni;render();const b=document.querySelector(`.menu [data-wact="${d.wact}"]`)||document.querySelector('.menu button:not([disabled])');b&&b.focus();return}
  if(d.resetview!==undefined){setView(S.viewId);return}
  if(d.saveas!==undefined){S.saveAs=true;render();const i=document.getElementById('vname');i&&(i.focus(),i.select());return}
  if(d.cancelsave!==undefined){S.saveAs=false;render();return}
  if(d.save!==undefined){const v=S.views.find(x=>x.id===S.viewId);if(v){v.w=S.layout.map(x=>x.slice());v.f=snapFilters();persist();S.dirty=false;toast(t('savedT'));render()}return}
  if(d.delview!==undefined){if(!confirm(t('deleteQ')))return;S.views=S.views.filter(x=>x.id!==S.viewId);persist();setView(PRESETS[0].id);toast(t('deletedT'));return}
  if(d.signout!==undefined){signOut();return}
  if(d.forgot!==undefined){APP.mode=APP.mode==='forgot'?'signin':'forgot';APP.err=null;APP.info=null;render();const x=document.getElementById('email');x&&x.focus();return}
  if(d.showpw){const x=document.getElementById(d.showpw);if(x){const on=x.type==='password';x.type=on?'text':'password';el.setAttribute('aria-pressed',String(on));el.setAttribute('aria-label',on?t('hidePw'):t('showPw'))}return}
  if(d.actretry!==undefined){verifyAction();return}
  if(d.retry!==undefined){boot();return}
  if(d.fixture!==undefined){useFixture(d.fixture==='0'?false:d.fixture);return}
});
document.addEventListener('submit',e=>{const f=e.target;e.preventDefault();
  if(f.dataset.saveform!==undefined){const name=document.getElementById('vname').value.trim();if(!name)return;const id='u'+Date.now().toString(36);S.views.push({id,name:{en:name,ar:name},w:S.layout.map(x=>x.slice()),f:snapFilters()});persist();S.viewId=id;S.dirty=false;S.saveAs=false;toast(t('savedT'));render();return}
  if(f.dataset.signin!==undefined){signIn(f.email.value.trim(),f.password.value);return}
  if(f.dataset.reset!==undefined){resetPw(f.email.value.trim());return}
  if(f.dataset.newpw!==undefined){confirmPw(f.np.value,f.np2.value);return}});
document.addEventListener('input',e=>{const el=e.target,d=el.dataset;
  if(d.exq!==undefined){S.ex.q=el.value;S.ex.limit=36;clearTimeout(render.qt);render.qt=setTimeout(render,120);return}
  if(d.tq){S.tbl[d.tq].q=el.value;clearTimeout(render.qt);render.qt=setTimeout(render,120);return}
  if(d.popq){S.popq=el.value;render();return}});
document.addEventListener('change',e=>{const el=e.target,d=el.dataset;
  if(d.f){el.checked?S.f[d.f].add(el.value):S.f[d.f].delete(el.value);if(S.edit||S.viewId)markDirty();render();return}
  if(d.exsort!==undefined){S.ex.sort=el.value;render();return}
  if(d.preview!==undefined){S.preview=el.value;render();return}});
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){if(S.pop){const k=S.pop;S.pop=null;render();const b=document.getElementById('fb-'+k);b&&b.focus();return}if(S.wmenu!=null){const i=S.wmenu;S.wmenu=null;render();const b=document.querySelector(`[data-wmenu="${i}"]`);b&&b.focus();return}if(S.drawer){closeDrawer();return}if(S.saveAs){S.saveAs=false;render();return}}
  if((e.key==='Enter'||e.key===' ')&&e.target.matches('tr[data-prod],tr[data-drillcat],[data-act]:not(button)')){e.preventDefault();e.target.click();return}
  if(e.key==='Tab'&&S.drawer){const d=document.querySelector('.drawer');if(!d)return;const f=[...d.querySelectorAll('button,a[href],input,select,[tabindex="0"]')];if(!f.length)return;if(e.shiftKey&&document.activeElement===f[0]){e.preventDefault();f[f.length-1].focus()}else if(!e.shiftKey&&document.activeElement===f[f.length-1]){e.preventDefault();f[0].focus()}}});
/* drag to reorder */
let DRG=null;
document.addEventListener('dragstart',e=>{const w=e.target.closest&&e.target.closest('.widget.editing');if(!w)return;DRG=+w.dataset.wi;w.classList.add('dragging');e.dataTransfer.effectAllowed='move';try{e.dataTransfer.setData('text/plain',String(DRG))}catch(x){}});
document.addEventListener('dragover',e=>{if(DRG==null)return;const w=e.target.closest('.widget.editing');if(!w)return;e.preventDefault();document.querySelectorAll('.dropb,.dropa').forEach(x=>x.classList.remove('dropb','dropa'));const r=w.getBoundingClientRect();const rtl=S.lang==='ar';const after=(rtl?e.clientX<r.left+r.width/2:e.clientX>r.left+r.width/2);w.classList.add(after?'dropa':'dropb')});
document.addEventListener('drop',e=>{if(DRG==null)return;const w=e.target.closest('.widget.editing');e.preventDefault();if(w){let to=+w.dataset.wi;const after=w.classList.contains('dropa');const it=S.layout.splice(DRG,1)[0];if(DRG<to)to--;S.layout.splice(after?to+1:to,0,it);markDirty()}DRG=null;render()});
document.addEventListener('dragend',()=>{DRG=null;document.querySelectorAll('.dragging,.dropb,.dropa').forEach(x=>x.classList.remove('dragging','dropb','dropa'))});
/* resize handle */
let RSZ=null;
document.addEventListener('pointerdown',e=>{const h=e.target.closest&&e.target.closest('[data-rs]');if(!h)return;e.preventDefault();const i=+h.dataset.rs;const g=document.getElementById('dgrid');const col=(g.clientWidth-11*GAP)/12;RSZ={i,x:e.clientX,y:e.clientY,w:S.layout[i][1],h:S.layout[i][2],col,el:h.closest('.widget')};h.setPointerCapture(e.pointerId)});
document.addEventListener('pointermove',e=>{if(!RSZ)return;const dx=(e.clientX-RSZ.x)*(S.lang==='ar'?-1:1),dy=e.clientY-RSZ.y;const min=W[S.layout[RSZ.i][0]].minW||3;
  const w=Math.max(min,Math.min(12,Math.round(RSZ.w+dx/(RSZ.col+GAP)))),h=Math.max(1,Math.min(5,Math.round(RSZ.h+dy/(ROWH+GAP))));RSZ.el.style.gridColumn=`span ${w}`;RSZ.el.style.gridRow=`span ${h}`;RSZ.nw=w;RSZ.nh=h;RSZ.el.dataset.size=`${w} × ${h}`});
document.addEventListener('pointerup',()=>{if(!RSZ)return;const it=S.layout[RSZ.i];if(RSZ.nw&&(RSZ.nw!==it[1]||RSZ.nh!==it[2])){it[1]=RSZ.nw;it[2]=RSZ.nh;markDirty()}RSZ=null;render()});
let RT;window.addEventListener('resize',()=>{clearTimeout(RT);RT=setTimeout(render,150)});
window.addEventListener('hashchange',route);

/* ---------- hosted mode: Firebase Auth + Storage over REST (no SDK, no CDN) ---------- */
const APP={hosted:(document.querySelector('meta[name="pi-mode"]')||{}).content==='hosted',state:'ready',mode:'signin',cfg:null,idToken:null,exp:0,email:null,err:null,info:null};
const DATA_PATH='datasets/uae/latest.json';
async function cfg(){if(APP.cfg)return APP.cfg;const r=await fetch('/__/firebase/init.json',{cache:'no-store'});if(!r.ok)throw new Error('config');APP.cfg=await r.json();return APP.cfg}
async function idp(path,body){const c=await cfg();const r=await fetch(`https://identitytoolkit.googleapis.com/v1/${path}?key=${encodeURIComponent(c.apiKey)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const j=await r.json().catch(()=>({}));if(!r.ok)throw Object.assign(new Error('auth'),{code:(j.error&&j.error.message)||'ERROR'});return j}
async function refresh(rt){const c=await cfg();const r=await fetch(`https://securetoken.googleapis.com/v1/token?key=${encodeURIComponent(c.apiKey)}`,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'grant_type=refresh_token&refresh_token='+encodeURIComponent(rt)});const j=await r.json().catch(()=>({}));if(!r.ok)throw Object.assign(new Error('refresh'),{code:(j.error&&j.error.message)||'ERROR'});
  APP.idToken=j.id_token;APP.exp=Date.now()+(+j.expires_in-60)*1000;try{localStorage.setItem('pi.auth',JSON.stringify({rt:j.refresh_token,email:APP.email}))}catch(e){}}
function authErr(code){const m={EMAIL_NOT_FOUND:'errCreds',INVALID_PASSWORD:'errCreds',INVALID_LOGIN_CREDENTIALS:'errCreds',USER_DISABLED:'errDisabled',TOO_MANY_ATTEMPTS_TRY_LATER:'errTooMany',INVALID_EMAIL:'errEmail'};const k=Object.keys(m).find(x=>String(code).startsWith(x));return t(k?m[k]:'errGeneric')}
async function signIn(email,pw){APP.formEmail=email;APP.err=null;APP.busy=true;render();try{const j=await idp('accounts:signInWithPassword',{email,password:pw,returnSecureToken:true});APP.email=j.email;APP.idToken=j.idToken;APP.exp=Date.now()+(+j.expiresIn-60)*1000;try{localStorage.setItem('pi.auth',JSON.stringify({rt:j.refreshToken,email:j.email}))}catch(e){}APP.busy=false;await loadData()}catch(e){APP.busy=false;APP.err=e.code?authErr(e.code):t('errNetwork');render()}}
async function resetPw(email){APP.formEmail=email;if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)){APP.err=t('errEmail');render();return}APP.err=null;APP.info=null;APP.busy=true;render();try{await idp('accounts:sendOobCode',{requestType:'PASSWORD_RESET',email});APP.info=t('resetSent')}catch(e){const r=resetOutcome(e.code);if(r==='sent')APP.info=t('resetSent');else if(r==='email')APP.err=t('errEmail');else{console.warn('password reset failed:',String(e.code||'network').split(/[\s:]/)[0]);APP.err=t('errResetLater')}}APP.busy=false;render()}
/* An unknown address answers like a sent link, so the form never says who has an account; any other failure is said, never swallowed. */
function resetOutcome(code){const c=String(code||'');return /^EMAIL_NOT_FOUND/.test(c)?'sent':/^(INVALID_EMAIL|MISSING_EMAIL)/.test(c)?'email':'later'}
function signOut(){try{localStorage.removeItem('pi.auth')}catch(e){}APP.idToken=null;APP.email=null;APP.state='signin';APP.mode='signin';REAL=null;useDS(SAMPLE);location.hash='#/signin';render()}
async function loadData(){APP.state='loading';render();try{const c=await cfg();if(Date.now()>APP.exp){const s=JSON.parse(localStorage.getItem('pi.auth')||'null');if(!s)throw Object.assign(new Error(),{st:'signin'});await refresh(s.rt)}
    const url=`https://firebasestorage.googleapis.com/v0/b/${encodeURIComponent(c.storageBucket)}/o/${encodeURIComponent(DATA_PATH)}?alt=media`;
    const r=await fetch(url,{headers:{Authorization:'Firebase '+APP.idToken},cache:'no-store'});
    if(r.status===401||r.status===403){APP.state='noaccess';render();return}if(r.status===404){APP.state='nodata';render();return}if(!r.ok)throw new Error('HTTP '+r.status);
    const j=await r.json();const errs=validateDataset(j);if(errs.length){APP.state='invalid';APP.err=errs.join(' · ');render();return}
    REAL=hydrate(j);useDS(REAL);afterData();APP.state='ready';if(/signin/.test(location.hash)||!location.hash)location.replace('#/dashboard');route()}
  catch(e){if(e.st==='signin'){APP.state='signin';render();return}if(e.code&&/TOKEN|USER/.test(e.code)){signOut();return}APP.state='error';APP.err=String(e.message||e);render()}}
function afterData(){S.ret=new Set(RR.filter(retOk));S.range=[Math.max(0,DAYS-90),DAYS-1];S.pins=S.pins.filter(id=>byId[id]);if(!S.pins.length)S.pins=PRODUCTS.filter(p=>p.listed.u&&p.listed.s).slice(0,0).map(p=>p.id);
  if(DS.real){S.viewId='snap';S.layout=viewById('snap').w.map(x=>x.slice())}}
/* /auth/action: Firebase email action handler (password reset only). The oobCode is kept in memory and removed from the address bar. */
function actErr(c){return /EXPIRED_OOB_CODE/.test(c||'')?'expired':c?'invalid':'error'}
async function bootAction(){const q=new URLSearchParams(location.search);let stored=null;try{stored=localStorage.getItem('pi.lang')}catch(e){}if(!stored&&/^ar/i.test(q.get('lang')||''))S.lang='ar';
  const mode=q.get('mode'),code=q.get('oobCode');APP.state='action';APP.act={mode,code,st:'verifying'};try{history.replaceState(null,'',location.pathname)}catch(e){}
  if(mode!=='resetPassword'){APP.act.st=mode?'unsupported':'invalid';render();return}if(!code){APP.act.st='invalid';render();return}verifyAction()}
async function verifyAction(){const A=APP.act;A.st='verifying';render();try{const j=await idp('accounts:resetPassword',{oobCode:A.code});A.email=j.email||'';A.st='form'}catch(e){A.st=actErr(e.code)}render();const f=document.getElementById('np');f&&f.focus()}
async function confirmPw(p1,p2){const A=APP.act;A.err=null;if(p1.length<8){A.err=t('pwMin');render();return}if(p1!==p2){A.err=t('pwMismatch');render();return}
  A.busy=true;render();try{await idp('accounts:resetPassword',{oobCode:A.code,newPassword:p1});A.st='done';A.code=null}catch(e){const c=e.code||'';if(/WEAK_PASSWORD|PASSWORD_DOES_NOT_MEET/.test(c))A.err=t('errWeak');else if(/OOB_CODE/.test(c))A.st=actErr(c);else A.err=c?t('errSave'):t('errNetwork')}A.busy=false;render();const h=document.querySelector('.gatecard h1');h&&(h.setAttribute('tabindex','-1'),A.st!=='form'&&h.focus())}
async function boot(){if(!APP.hosted){APP.state='ready';route();return}
  if(/^\/auth\/action\/?$/.test(location.pathname)){bootAction();return}
  if(/^#\/forgot/.test(location.hash)){APP.mode='forgot';location.replace('#/signin')}
  const fx=new URLSearchParams(location.search).get('fixture');
  if(fx&&/^(localhost|127\.0\.0\.1)$/.test(location.hostname)){APP.state='loading';render();try{const j=await (await fetch(fx)).json();const errs=validateDataset(j);if(errs.length)throw new Error(errs.join(' · '));REAL=hydrate(j);useDS(REAL);afterData();APP.email='local fixture';APP.state='ready';route()}catch(e){APP.state='invalid';APP.err=String(e.message);render()}return}
  let s=null;try{s=JSON.parse(localStorage.getItem('pi.auth')||'null')}catch(e){}
  if(!s){APP.state='signin';if(!/signin/.test(location.hash))location.replace('#/signin');render();return}
  APP.email=s.email;APP.state='loading';render();try{await refresh(s.rt);await loadData()}catch(e){if(e.code){signOut();return}APP.state='error';APP.err=String(e.message||e);render()}}
function pwField(id,label,ac,hint){return `<label for="${id}">${label}</label><div class="pwrap"><input id="${id}" name="${id}" type="password" autocomplete="${ac}" required ${hint?`aria-describedby="${id}-h"`:''}><button type="button" class="iconbtn" data-showpw="${id}" aria-pressed="false" aria-label="${t('showPw')}">${ICON.eye}</button></div>${hint?`<p class="hint" id="${id}-h">${hint}</p>`:''}`}
function gateScreen(){const st=APP.state;const card=inner=>`<div class="gatepage"><main class="gatecard" id="main"><div class="brandmark"><span class="logo" aria-hidden="true"><i></i><i></i></span><div><b>${t('appName')}</b><span>${t('appSub')}</span></div></div>${inner}</main><button class="btn ghost sm langfloat" id="langbtn" lang="${S.lang==='en'?'ar':'en'}">${S.lang==='en'?'العربية':'English'}</button></div>`;
  const stateB=(kind,ic,title,text,actions)=>card(`<div class="state"><span class="gi ${kind}">${ICON[ic]}</span><div><h1>${title}</h1><p class="muted">${text}</p></div></div><div class="actions">${actions}</div>`);
  const tech=()=>APP.err?`<details><summary class="muted xs">${t('techDetails')}</summary><p class="mono xs">${esc(APP.err)}</p></details>`:'';
  const err=e=>e?`<p class="formerr" role="alert">${esc(e)}</p>`:'';
  if(st==='action'){const A=APP.act,sin=`<a class="btn primary" href="/#/signin">${t('goSignIn')}</a>`,req=`<a class="btn primary" href="/#/forgot">${t('reqNew')}</a>`;
    if(A.st==='verifying')return card(`<h1>${t('actVerifyT')}</h1><div class="skel"><i style="width:70%"></i><i style="width:50%"></i></div>`);
    if(A.st==='form')return card(`<h1>${t('newPwT')}</h1>${A.email?`<p class="muted">${t('newPwP')(`<bdi>${esc(A.email)}</bdi>`)}</p>`:''}<form data-newpw class="authform" novalidate><input type="text" name="username" autocomplete="username" value="${esc(A.email||'')}" class="vh" tabindex="-1" aria-hidden="true" readonly>
      ${pwField('np',t('newPw'),'new-password',t('pwMin'))}${pwField('np2',t('confirmPw'),'new-password')}${err(A.err)}<button class="btn primary" type="submit" ${A.busy?'disabled':''}>${A.busy?t('working'):t('savePw')}</button></form>`);
    if(A.st==='done')return stateB('ok','check',t('pwDoneT'),t('pwDoneP'),sin);
    if(A.st==='expired')return stateB('warn','clock',t('linkExpT'),t('linkExpP'),req);
    if(A.st==='unsupported')return stateB('warn','dash',t('linkModeT'),t('linkModeP'),sin);
    if(A.st==='error')return stateB('bad','dash',t('errT'),t('errNetwork'),`<button class="btn primary" data-actretry>${t('retry')}</button>`);
    return stateB('bad','shield',t('linkBadT'),t('linkBadP'),req)}
  if(st==='signin'){const f=APP.mode==='forgot';
    if(f&&APP.info)return stateB('ok','mail',t('checkEmailT'),esc(APP.info),`<button class="btn" data-forgot>${t('backSignIn')}</button>`);
    return card(`<h1>${f?t('resetT'):t('signInT')}</h1><p class="muted">${f?t('resetP'):t('signInP')}</p>
   <form ${f?'data-reset':'data-signin'} class="authform" novalidate><label for="email">${t('email')}</label><input id="email" name="email" type="email" autocomplete="username" required value="${esc(APP.formEmail||APP.email||'')}">
   ${f?'':pwField('password',t('password'),'current-password')}
   ${err(APP.err)}
   <button class="btn primary" type="submit" ${APP.busy?'disabled':''}>${APP.busy?t('working'):f?t('sendReset'):t('signIn')}</button></form>
   <button class="linkbtn" data-forgot>${f?t('backSignIn'):t('forgot')}</button><p class="muted xs">${t('inviteOnly')}</p>`)}
  if(st==='loading')return card(`<h1>${t('loadingT')}</h1><div class="skel"><i style="width:70%"></i><i style="width:50%"></i></div><p class="muted xs">${t('loadingP')}</p>`);
  if(st==='noaccess')return stateB('warn','shield',t('noAccessT'),t('noAccessP')(esc(APP.email||'')),`<button class="btn" data-signout>${t('signOut')}</button>`);
  if(st==='nodata')return stateB('wait','clock',t('noDataT'),t('noDataP'),`<button class="btn primary" data-retry>${t('retry')}</button><button class="btn" data-signout>${t('signOut')}</button>`);
  if(st==='invalid')return card(`<div class="state"><span class="gi bad">${ICON.dash}</span><div><h1>${t('invalidT')}</h1><p class="muted">${t('invalidP')}</p></div></div>${tech()}<div class="actions"><button class="btn" data-retry>${t('retry')}</button></div>`);
  return card(`<div class="state"><span class="gi bad">${ICON.dash}</span><div><h1>${t('errT')}</h1><p class="muted">${t('errP')}</p></div></div>${tech()}<div class="actions"><button class="btn primary" data-retry>${t('retry')}</button><button class="btn" data-signout>${t('signOut')}</button></div>`)}

/* artifact-only switch: preview the demo-night snapshot shape (test fixture) without any network */
const FIX={};function useFixture(on){if(on){const m=on==='2'?'partial':'blocked';REAL=FIX[m]||(FIX[m]=hydrate(fixtureContract(m)));useDS(REAL)}else useDS(SAMPLE);resetAll();afterData();if(!on){S.viewId='lead';S.layout=viewById('lead').w.map(x=>x.slice());S.pins=['h0','h2','h4']}render()}
PRESETS.unshift({id:'snap',name:{en:'Snapshot overview',ar:'نظرة على اللقطة'},preset:true,w:[['kpiCatalog',3,1],['kpiMedPrice',3,1],['kpiBrands',3,1],['kpiRating',3,1],['early',4,4],['ladder',8,4],['bandgrid',12,5],['brandtbl',12,5],['matrix',12,3]]});
try{const l=localStorage.getItem('pi.lang');if(l==='ar'||l==='en')S.lang=l}catch(e){}
boot();
