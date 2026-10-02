/* Data layer. Everything the app renders comes from one pi.dataset/v1 JSON (see data-contract.md).
   The sample generator (data.js) exports that JSON; the real snapshot export produces the same shape. */
/* dataset strings reach SVG attributes: only plain hex colours pass */
const HEX=h=>typeof h==='string'&&/^#[0-9a-f]{6}$/i.test(h)?h:null;
const DEFAULT_TYPE={foundation:'foundation',concealer:'wand',lips:'lipstick',cheek:'blush',eyes:'mascara',skincare:'dropper',fragrance:'perfume',body:'jar',other:'jar'};
const FIELD_KEYS=['price','regular','promo','stock','size','shades','rating','gtin'];

/* ---- sample → contract ---- */
function sampleContract(){
  const iso=i=>dayDate(i).toISOString().slice(0,10);const dates=Array.from({length:DAYS},(_,i)=>iso(i));
  const regSeries=(p,k)=>p.d[k].price.map((v,d)=>{if(v==null)return null;let reg=p.reg[k];p.pchg.forEach(e=>{if(e.r===k&&d<e.d)reg=e.from});const sc=p.sizeChg.find(e=>e.r===k);if(sc&&d<sc.d)reg=Math.round(reg*.97);return reg});
  const products=G_PRODUCTS.map(p=>({id:p.id,brand:p.brand,name:p.name,category:p.cat,unit:p.unit,shadeFamilies:p.fam,shades:p.shades,
    render:{type:p.type,cap:p.cap,liquid:p.liquid},
    match:p.match?{method:p.match[0],confidence:p.match[1],stage:'reviewed'}:null,
    offers:Object.fromEntries(RR.map(k=>[k,p.d[k]?{sku:(k==='u'?'ULT-':'SPH-')+(hash(p.id+k)%900000+100000),url:null,size:p.size[k],shadeCount:p.shadeCount[k],rating:p.rating[k],
      series:{price:p.d[k].price,regular:regSeries(p,k),size:p.d[k].size,stock:p.d[k].stock,promo:p.d[k].promo},
      promos:p.promos.filter(x=>x.r===k).map(x=>({campaign:x.c,start:iso(x.a),end:iso(x.b),pct:x.pct})),
      evidence:{capturedAt:dates[DAYS-1]+(k==='u'?'T05:42:00Z':'T06:10:00Z'),source:k==='u'?'ulta_ae · rung 2':'sephora_me · rung 1',runId:(k==='u'?'run-ulta-':'run-sph-')+'0930-'+(hash(p.id)%9000+1000)}}:null]))}));
  return {schema:'pi.dataset/v1',
    meta:{kind:'sample',cutoff:dates[DAYS-1]+'T06:10:00Z',generatedAt:dates[DAYS-1]+'T06:30:00Z',market:'AE',currency:'AED',matchStage:'reviewed',dates,
      retailers:[{id:'u',key:'ulta_ae',name:'Ulta UAE'},{id:'s',key:'sephora_me',name:'Sephora UAE'}],
      capabilities:{history:true,promotions:true,campaigns:true,stock:true,sizes:true,shades:true,coverage:true},
      fields:{},matchCheck:null},
    products,
    campaigns:G_CAMPAIGNS.map(c=>({id:c.id,retailer:c.r,name:c.name,mechanic:c.mech,start:c.start,end:c.end,depth:c.depth||null,categories:c.cats||null})),
    notObserved:G_NOT_OBS.map(n=>({retailer:n.r,start:iso(n.a),end:iso(n.b),categories:n.cats,why:n.why})),
    coverage:{sources:G_SOURCES,fields:G_FIELDS,precision:G_PRECISION,quarantine:G_QUAR}}}

/* ---- contract → model ---- */
function validateDataset(j){const e=[];if(!j||j.schema!=='pi.dataset/v1')e.push('schema must be pi.dataset/v1');
  if(!j.meta||!Array.isArray(j.meta.dates)||!j.meta.dates.length)e.push('meta.dates must be a non-empty array');
  if(!Array.isArray(j.products))e.push('products must be an array');
  if(!e.length){const n=j.meta.dates.length;j.products.slice(0,400).forEach(p=>{if(!p.id||!p.brand||!p.name)e.push('product missing id/brand/name');
    Object.entries(p.offers||{}).forEach(([k,o])=>{if(o&&o.series&&o.series.price&&o.series.price.length!==n)e.push(`${p.id}.${k}: series length ≠ dates`)})})}
  return e.slice(0,5)}
/* Product images are hotlinked from the retailer's own CDN, never copied: an https URL on that retailer's host only, else none. */
const IMG_HOSTS={s:'img-product.sephora.me',u:'media.alshaya.com'};
function imgUrl(v,k){if(typeof v!=='string')return null;try{const u=new URL(v);return u.protocol==='https:'&&!u.username&&!u.password&&(k?u.hostname===IMG_HOSTS[k]:Object.values(IMG_HOSTS).includes(u.hostname))?u.href:null}catch(e){return null}}
/* A price of 0.01 or less is a feed error, not a price (owner rule): it is read as no price, so it
   is never shown and never enters an aggregate. */
const cash=v=>v==null||!(+v>0.01)?null:+v;
function hydrate(j){
  const dates=j.meta.dates,N=dates.length,end=Date.parse(dates[N-1]+'T00:00:00Z'),dOf=iso=>Math.round((Date.parse(String(iso).slice(0,10)+'T00:00:00Z')-end)/864e5)+N-1;
  const caps=Object.assign({history:N>1,promotions:false,campaigns:false,stock:false,sizes:false,shades:false,coverage:false},j.meta.capabilities||{});
  const rets=Object.fromEntries((j.meta.retailers||[]).map(r=>[r.id,r]));
  const rOk=k=>!rets[k]||!rets[k].status||rets[k].status==='ok'||rets[k].status==='partial';
  const early=[];
  const products=j.products.map(q=>{const cat=CATS.includes(q.category)?q.category:'other';const R=q.render||{};
    const shades=(q.shades||[]).filter(h=>/^#[0-9a-f]{6}$/i.test(h));
    const p={id:String(q.id).replace(/[^\w.:-]/g,'_'),brand:String(q.brand??''),name:String(q.name??''),cat,type:R.type||DEFAULT_TYPE[cat],unit:String(q.unit||'').replace(/[^\p{L}\p{N} .\/%-]/gu,'').slice(0,12),cap:HEX(R.cap)||'#2A2A2C',liquid:HEX(R.liquid)||shades[0]||'#E9E1D7',shades,fam:q.shadeFamilies||[],hero:false,
      listed:{},size:{},reg:{},shadeCount:{},rating:{},first:{},last:{},d:{},ev:{},sku:{},url:{},promos:[],outs:[],sizeChg:[],
      match:q.match&&q.match.reviewState!=='rejected'?[q.match.method,q.match.confidence,q.match.stage||j.meta.matchStage,q.match.matchClass||'exact',q.match.reviewState||(j.meta.kind==='sample'?'accepted':'unreviewed')]:null};
    RR.forEach(k=>{let o=q.offers&&q.offers[k];if(o&&(o.early||!rOk(k))){if(o.early)early.push({p,k,o});o=null}p.listed[k]=!!o;if(!o){p.d[k]=null;p.first[k]=p.last[k]=null;p.shadeCount[k]=0;p.rating[k]=null;return}
      const sr=o.series||{};const price=(sr.price||new Array(N).fill(null)).map(cash);
      const size=sr.size?sr.size.map(v=>v==null?null:+v):new Array(N).fill(o.size==null?null:+o.size);
      const stock=sr.stock?sr.stock.map((v,i)=>price[i]==null&&v!==4?0:v):null;
      const regular=sr.regular?sr.regular.map(cash):null;/* a discount worked out from a guarded price or regular price is not a discount either */const bad=i=>price[i]==null||(regular&&regular[i]==null&&sr.regular[i]!=null);const promo=sr.promo?sr.promo.map((v,i)=>bad(i)?0:v):null;
      const held=(sr.price||[]).map((v,i)=>v!=null&&price[i]==null);p.d[k]={price,size,stock,promo,regular,held};p.size[k]=o.size!=null?+o.size:size[N-1];p.shadeCount[k]=+o.shadeCount||0;p.rating[k]=Array.isArray(o.rating)?o.rating.map(Number):null;
      p.ev[k]=o.evidence||null;if(!p.img)p.img=imgUrl(o.image,k);p.sku[k]=o.sku||null;p.url[k]=o.url||null;
      let f=price.findIndex(v=>v!=null),l=-1;for(let i=N-1;i>=0;i--)if(price[i]!=null){l=i;break}
      p.first[k]=f<0?null:f;p.last[k]=l<0?null:l;
      p.reg[k]=regular&&l>=0?regular[l]:(l>=0?price[l]:null);
      (o.promos||[]).forEach(x=>{const a=Math.max(0,dOf(x.start)),b=Math.min(N-1,dOf(x.end));let ok=false;for(let i=a;i<=b;i++)if(!bad(i))ok=true;if(ok)p.promos.push({c:x.campaign||null,r:k,a,b,pct:+x.pct||0})});
      if(!o.promos&&promo){let a=null;for(let i=0;i<=N;i++){const on=i<N&&promo[i]>0;if(on&&a==null)a=i;if(!on&&a!=null){p.promos.push({c:null,r:k,a,b:i-1,pct:Math.max(...promo.slice(a,i))});a=null}}}
      if(stock){let a=null;for(let i=0;i<=N;i++){const on=i<N&&stock[i]===3;if(on&&a==null)a=i;if(!on&&a!=null){p.outs.push({r:k,a,b:i-1});a=null}}}
      for(let i=1;i<N;i++)if(size[i]!=null&&size[i-1]!=null&&size[i]!==size[i-1])p.sizeChg.push({r:k,d:i,from:size[i-1],to:size[i]})});
    if(!p.img)p.img=imgUrl(q.image);
    p.sameSize=p.listed.u&&p.listed.s&&p.size.u!=null&&p.size.u===p.size.s&&!p.sizeChg.length&&(!p.match||p.match[3]==='exact');return p});
  early.forEach(e=>{const sr=e.o.series||{};e.price=sr.price?cash(sr.price[N-1]):null;e.size=e.o.size==null?null:+e.o.size;e.at=e.o.evidence&&e.o.evidence.capturedAt});
  products.splice(0,products.length,...products.filter(p=>p.listed.u||p.listed.s));
  /* categories outside the beauty list stay visible as 'other' (filters, ladder, overlap) */
  if(products.some(p=>p.cat==='other')&&!CATS.includes('other'))CATS.push('other');
  const campaigns=(j.campaigns||[]).map(c=>({id:c.id,r:c.retailer,name:typeof c.name==='string'?{en:c.name}:c.name,mech:c.mechanic||'unclassified',start:c.start,end:c.end,depth:c.depth,cats:c.categories,a:dOf(c.start),b:dOf(c.end)}));
  const notObs=(j.notObserved||[]).map(n=>({r:n.retailer,a:dOf(n.start),b:dOf(n.end),cats:n.categories||null,why:typeof n.why==='string'?{en:n.why}:n.why}));
  const cov=j.coverage||{};
  const ds={meta:j.meta,real:j.meta.kind!=='sample',caps,N,END:end,products,byId:Object.fromEntries(products.map(p=>[p.id,p])),
    brands:[...new Set(products.map(p=>p.brand))].sort((a,b)=>a.localeCompare(b)),campaigns,notObs,
    rets,rOk:Object.fromEntries(RR.map(k=>[k,rOk(k)])),early,sources:cov.sources||[],fields:cov.fields||[],precision:cov.precision||[],quar:cov.quarantine||[],fieldStatus:j.meta.fields||{},matchCheck:j.meta.matchCheck||null};
  return ds}

/* ---- active dataset (globals used by charts and views) ---- */
var DS=null,PRODUCTS=[],CAMPAIGNS=[],NOT_OBS=[],byId={},BRAND_LIST=[],SOURCES=[],FIELDS=[],PRECISION=[],QUAR=[];
function useDS(ds){DS=ds;DAYS=ds.N;END=ds.END;PRODUCTS=ds.products;CAMPAIGNS=ds.campaigns;NOT_OBS=ds.notObs;byId=ds.byId;BRAND_LIST=ds.brands;SOURCES=ds.sources;FIELDS=ds.fields;PRECISION=ds.precision;QUAR=ds.quar}
const priceAt=(p,k,d)=>p.d[k]?p.d[k].price[d]:null;
const regAt=(p,k,d)=>{const x=p.d[k];if(!x||x.price[d]==null)return null;return x.regular?x.regular[d]:null};
const sizeAt=(p,k,d)=>p.d[k]?p.d[k].size[d]:null;
const stockAt=(p,k,d)=>{const x=p.d[k];if(!x)return 0;if(!x.stock)return x.price[d]!=null?-1:0;return x.stock[d]};
const promoAt=(p,k,d)=>{const x=p.d[k];return x&&x.promo?x.promo[d]:0};
const listedAt=(p,k,d)=>!!(p.d[k]&&p.d[k].price[d]!=null);
/* listed that day, but its price was a feed error (0.01 or less) and is withheld */
const heldAt=(p,k,d)=>!!(p.d[k]&&p.d[k].held&&p.d[k].held[d]);
const unitAt=(p,k,d)=>{const v=priceAt(p,k,d),s=sizeAt(p,k,d);return v==null||!s?null:v/s};

const SAMPLE=hydrate(sampleContract());
let REAL=null;
useDS(SAMPLE);

/* ---- test fixture shaped like the demo-night reality: one Sephora snapshot, Ulta blocked, a few early examples ---- */
function fixtureContract(mode){const part=mode==='partial';const j=sampleContract();const last=j.meta.dates.length-1;const cut=a=>a?[a[last]]:undefined;let early=0;
  const products=[];j.products.forEach(q=>{const o={u:null,s:null};
    ['u','s'].forEach(k=>{const x=q.offers[k];if(!x||x.series.price[last]==null)return;const isEarly=k==='u'&&q.id[0]==='h'&&early<5&&!!q.offers.s;if(part&&k==='u'){if(hash(q.id+'px')%10>=6)return}else{if(k==='u'&&!isEarly)return;if(isEarly)early++}
      o[k]={sku:x.sku,url:null,size:x.series.size[last],shadeCount:x.shadeCount,rating:x.rating,early:(!part&&isEarly)||undefined,series:{price:cut(x.series.price),regular:cut(x.series.regular),promo:cut(x.series.promo)},
        evidence:{capturedAt:k==='u'?'2026-09-30T20:41:00Z':'2026-09-30T20:10:00Z',source:k==='u'?(part?'ulta_ae · proxy snapshot':'ulta_ae · early capture'):'sephora_me · catalogue snapshot',runId:k==='u'?(part?'run-ulta-0930-proxy':'run-ulta-0930-early'):'run-sph-0930-snap',rawPrice:'AED '+x.series.price[last].toFixed(2)}}});
    if(o.u||o.s)products.push(Object.assign({},q,{match:part&&o.u&&o.s&&q.match?{method:q.match.method,confidence:q.match.confidence,stage:'first-pass',matchClass:o.u.size===o.s.size?'exact':'variant',reviewState:q.match.confidence>.97?'proposed':'unreviewed'}:null,offers:o}))});
  return {schema:'pi.dataset/v1',meta:{kind:'snapshot',test:true,cutoff:'2026-09-30T20:10:00Z',generatedAt:'2026-09-30T20:30:00Z',market:'AE',currency:'AED',matchStage:'first-pass',dates:[j.meta.dates[last]],
    retailers:[part?{id:'u',key:'ulta_ae',name:'Ulta UAE',status:'partial',catalogEstimate:260,note:{en:'Partial capture via proxy; categories and pages still being collected.',ar:'رصد جزئي عبر وكيل؛ لا تزال بعض الفئات والصفحات قيد الجمع.'}}:{id:'u',key:'ulta_ae',name:'Ulta UAE',status:'blocked',since:'2026-09-30T20:55:00Z',earlyExamples:true,note:{en:'Ulta UAE: access currently blocked by the site (Cloudflare challenge since 30 Sep 20:55 UTC); re-test scheduled.',ar:'ألتا الإمارات: الوصول محجوب حالياً من الموقع (تحدّي Cloudflare منذ 30 سبتمبر 20:55 UTC)؛ إعادة الاختبار مجدولة.'}},
      {id:'s',key:'sephora_me',name:'Sephora UAE',status:'ok',catalogEstimate:170}],
    capabilities:{history:false,promotions:true,campaigns:false,stock:false,sizes:true,shades:true,coverage:false},
    fields:{price:'ok',regular:'ok',promo:'ok',stock:'not_collected',size:'ok',shades:'ok',rating:'ok',gtin:'not_published'},matchCheck:part?{checked:50,correct:47,note:{en:'Random sample of first-pass pairs, checked by hand.',ar:'عينة عشوائية من أزواج المطابقة الأولية، فُحصت يدوياً.'}}:null},
    products,campaigns:[],notObserved:[],coverage:null}}
