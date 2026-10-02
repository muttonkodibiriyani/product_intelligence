/* Illustrative sample data only. Generated deterministically; not collected from any retailer. */
var DAYS=180, END=Date.UTC(2026,8,30);
function dayDate(i){return new Date(END-(DAYS-1-i)*864e5)}
function dayOf(iso){return Math.round((Date.parse(iso+'T00:00:00Z')-END)/864e5)+DAYS-1}
function hash(s){let h=2166136261;for(const c of s){h^=c.charCodeAt(0);h=Math.imul(h,16777619)}return h>>>0}
function mulberry(a){return function(){a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296}}
const RR=['u','s'];
const SKIN=['#F5DCC8','#EFCBAF','#E6BB98','#DBA882','#CD956D','#BC8058','#A76B47','#90583A','#77462E','#5C3424','#44261A'];
const LIPC=['#C4897A','#C06A78','#B0263B','#7C2B4B','#DE8AA0','#A66F7E','#DE7B62','#E3A393','#9E4B5A'];
const CHEEK=['#DE8AA0','#E7A089','#C9536A','#D9687A','#B8745B','#E9B59A'];
const BROW=['#C9A27E','#9B7458','#6A4B3A','#4A3226','#2E211B'];
const BG={foundation:'#F7EEE8',concealer:'#F6EDE6',lips:'#F8E7EA',cheek:'#F8E9EC',eyes:'#EEEAF6',skincare:'#E6F3EC',fragrance:'#F8F2DD',body:'#FBF3DA'};
const CATS=['foundation','concealer','lips','cheek','eyes','skincare','fragrance','body'];
const FAMS=['Fair','Light','Medium','Tan','Deep','Nude','Pink','Red','Berry','Coral'];
const BANDS=[['<100',0,99.99],['100–199',100,199.99],['200–399',200,399.99],['400+',400,1e9]];

const BRANDS=[
 ['Fenty Beauty',1.0,'both',['foundation','concealer','lips','cheek'],'#1C1C1E'],
 ['Huda Beauty',1.0,'both',['foundation','concealer','lips','eyes'],'#D7B98E'],
 ['Estée Lauder',1.35,'both',['foundation','skincare','fragrance'],'#C4A57A'],
 ['NARS',1.05,'both',['foundation','concealer','cheek','lips'],'#1C1C1E'],
 ['Charlotte Tilbury',1.25,'both',['lips','cheek','foundation','eyes'],'#C9A36A'],
 ['Rare Beauty',0.95,'both',['cheek','lips','foundation'],'#F1ECE6'],
 ['Benefit Cosmetics',0.95,'both',['eyes','cheek'],'#E79AB0'],
 ['Clinique',0.95,'both',['skincare','foundation'],'#9CC9B4'],
 ['Dior',1.5,'both',['fragrance','lips','foundation'],'#23262B'],
 ['Yves Saint Laurent',1.45,'both',['fragrance','lips'],'#1C1C1E'],
 ['Laneige',0.8,'both',['lips','skincare'],'#8FB4E3'],
 ['Drunk Elephant',1.2,'both',['skincare'],'#2F7F9E'],
 ['Sol de Janeiro',0.95,'both',['body','fragrance'],'#E5B53B'],
 ['Tarte',0.9,'both',['concealer','eyes','cheek'],'#6B4A8F'],
 ['Anastasia Beverly Hills',0.95,'both',['eyes'],'#8C8F94'],
 ['The Ordinary',0.3,'both',['skincare'],'#F4F4F2'],
 ['Sephora Collection',0.45,'s',['lips','eyes','skincare'],'#1C1C1E'],
 ['Kayali',1.2,'s',['fragrance'],'#E6D3B3'],
 ['Glow Recipe',0.95,'s',['skincare'],'#F09AAE'],
 ['Summer Fridays',0.8,'s',['lips','skincare'],'#DCC3A9'],
 ['Fresh',1.05,'s',['skincare','lips'],'#E9DCC6'],
 ['Tatcha',1.4,'s',['skincare'],'#B84A4A'],
 ['Ulta Beauty Collection',0.4,'u',['lips','eyes','body'],'#E8757E'],
 ['Morphe',0.6,'u',['eyes','cheek'],'#2A2A2C'],
 ['e.l.f. Cosmetics',0.35,'u',['foundation','eyes','lips'],'#E9EEF2'],
 ['MAC',0.9,'u',['lips','foundation','eyes'],'#1C1C1E'],
 ['Kylie Cosmetics',0.75,'u',['lips','cheek'],'#F2D6DC'],
 ['Tree Hut',0.35,'u',['body'],'#9C7BB5']
];
// [name, render type, size, unit, base AED, shade kind]
const LINES={
 foundation:[['Soft Matte Longwear Foundation','foundation',32,'ml',160,'skin'],['Skin Tint SPF 30','foundation',30,'ml',135,'skin'],['Serum Foundation','foundation',30,'ml',175,'skin'],['Hydrating Primer','pot',30,'ml',120,null],['Setting Powder','compact',9,'g',130,'skin']],
 concealer:[['Radiant Concealer','wand',6,'ml',115,'skin'],['Full Coverage Concealer','wand',10,'ml',120,'skin'],['Colour Corrector','wand',6,'ml',100,'skin']],
 lips:[['Matte Lipstick','lipstick',3.5,'g',110,'lip'],['Satin Lipstick','lipstick',3.5,'g',115,'lip'],['Lip Gloss','tube',8,'ml',90,'lip'],['Lip Liner','pencil',1.2,'g',75,'lip'],['Lip Balm','pot',15,'g',80,'lip']],
 cheek:[['Liquid Blush','blush',7.5,'ml',110,'cheek'],['Powder Blush','compact',5,'g',120,'cheek'],['Bronzer','compact',8,'g',140,'cheek'],['Highlighter','compact',8,'g',145,'cheek']],
 eyes:[['Eyeshadow Palette','palette',10,'g',210,null],['Lengthening Mascara','mascara',8.5,'g',115,null],['Brow Pencil','pencil',0.09,'g',95,'brow'],['Liquid Eyeliner','mascara',0.6,'ml',95,null],['Mini Palette','palette',4.5,'g',120,null]],
 skincare:[['Moisturising Cream','jar',50,'ml',190,null],['Niacinamide Serum','dropper',30,'ml',160,null],['Gel Cleanser','tube',150,'ml',110,null],['Eye Cream','pot',15,'ml',175,null],['Sunscreen SPF 50','tube',50,'ml',140,null],['Retinol Serum','dropper',30,'ml',210,null]],
 fragrance:[['Eau de Parfum','perfume',50,'ml',420,null],['Eau de Parfum','perfume',100,'ml',560,null],['Eau de Toilette','perfume',100,'ml',430,null],['Travel Spray','perfume',10,'ml',120,null],['Hair & Body Mist','perfume',90,'ml',150,null]],
 body:[['Body Cream','jar',240,'ml',180,null],['Body Scrub','jar',510,'g',95,null],['Body Oil','dropper',100,'ml',170,null],['Hand Cream','tube',50,'ml',75,null]]
};
// Hand-drawn hero products: [brand, name, cat, type, size, unit, cap, liquid, u, s, shadeKind, launch]
const HERO=[
 ['Fenty Beauty',"Pro Filt'r Soft Matte Longwear Foundation",'foundation','foundation',32,'ml','#1C1C1E','#C9926C',165,159,'skin'],
 ['Huda Beauty','#FauxFilter Luminous Matte Foundation','foundation','foundation',35,'ml','#D7B98E','#D6A47F',175,175,'skin'],
 ['Estée Lauder','Double Wear Stay-in-Place Foundation SPF 10','foundation','foundation',30,'ml','#C4A57A','#DDB08D',230,225,'skin'],
 ['NARS','Radiant Creamy Concealer','concealer','wand',6,'ml','#1C1C1E','#E1B592',130,130,'skin'],
 ['Tarte','Shape Tape Full Coverage Concealer','concealer','wand',10,'ml','#6B4A8F','#E3BB98',129,125,'skin'],
 ['Rare Beauty','Soft Pinch Liquid Blush','cheek','blush',7.5,'ml','#F1ECE6','#D9687A',115,109,'cheek'],
 ['Charlotte Tilbury','Matte Revolution Lipstick — Pillow Talk','lips','lipstick',3.5,'g','#C9A36A','#B97A74',150,145,'lip'],
 ['MAC','Retro Matte Lipstick — Ruby Woo','lips','lipstick',3,'g','#1C1C1E','#B0263B',105,null,'lip'],
 ['Anastasia Beverly Hills','Brow Wiz','eyes','pencil',0.085,'g','#8C8F94','#6A4B3A',110,105,'brow'],
 ['Laneige','Lip Sleeping Mask — Berry','lips','pot',20,'g','#E9A9B8','#F4C9D2',89,85,'lip'],
 ['Benefit Cosmetics',"They're Real! Lengthening Mascara",'eyes','mascara',8.5,'g','#1C1C1E','#1C1C1E',125,119,null],
 ['Huda Beauty','Nude Obsessions Eyeshadow Palette','eyes','palette',10.8,'g','#E9D3C3','#C19A7F',145,145,null],
 ['Dior','Sauvage Eau de Parfum','fragrance','perfume',100,'ml','#23262B','#2C3E5C',520,505,null],
 ['Yves Saint Laurent','Libre Eau de Parfum','fragrance','perfume',50,'ml','#1C1C1E','#E9B872',495,495,null],
 ['Kayali','Vanilla | 28 Eau de Parfum','fragrance','perfume',50,'ml','#E6D3B3','#C98FA5',null,460,null,'2026-09-22'],
 ['Clinique','Moisture Surge 100H Hydrator','skincare','jar',50,'ml','#E78FA3','#F3F0EB',220,215,null],
 ['The Ordinary','Niacinamide 10% + Zinc 1%','skincare','dropper',30,'ml','#F4F4F2','#EDEBE6',39,42,null],
 ['Drunk Elephant','Protini Polypeptide Cream','skincare','jar',50,'ml','#2F7F9E','#F4F1EA',265,259,null],
 ['Glow Recipe','Watermelon Glow Niacinamide Dew Drops','skincare','dropper',40,'ml','#F09AAE','#F6B8C4',null,149,null,'2026-09-25'],
 ['Summer Fridays','Lip Butter Balm — Vanilla Beige','lips','tube',15,'g','#DCC3A9','#DCC3A9',null,95,'lip','2026-09-27'],
 ['Sol de Janeiro','Brazilian Bum Bum Cream','body','jar',240,'ml','#E5B53B','#F6E3B4',199,189,null],
 ['Morphe','35O Supernatural Glow Palette','eyes','palette',52.5,'g','#2A2A2C','#C98A5E',99,null,null,'2026-09-23'],
 ['Kylie Cosmetics','Matte Lip Kit — Candy K','lips','lipstick',3,'ml','#F2D6DC','#B7747A',115,null,'lip'],
 ['e.l.f. Cosmetics','Power Grip Primer','foundation','pot',24,'ml','#E9EEF2','#DDE7EE',49,null,null,'2026-09-26']
];
const G_CAMPAIGNS=[
 {id:'u1',r:'u',name:{en:'Spring beauty event',ar:'حدث الجمال الربيعي'},mech:'pct',start:'2026-04-20',end:'2026-05-10',depth:[20,40],share:.3},
 {id:'u6',r:'u',name:{en:'Members: 2× points week',ar:'الأعضاء: أسبوع النقاط المضاعفة'},mech:'member',start:'2026-06-01',end:'2026-06-07',share:0},
 {id:'u2',r:'u',name:{en:'Summer fragrance 15% off',ar:'عطور الصيف: خصم 15%'},mech:'pct',start:'2026-07-01',end:'2026-07-15',depth:[15,15],cats:['fragrance','body'],share:.6},
 {id:'u3',r:'u',name:{en:'Daily deals (21 days)',ar:'عروض يومية (21 يوماً)'},mech:'pct',start:'2026-08-24',end:'2026-09-13',depth:[30,50],share:.07},
 {id:'u4',r:'u',name:{en:'Buy 2, get 1 on e.l.f.',ar:'اشترِ 2 واحصل على 1 من e.l.f.'},mech:'bundle',start:'2026-09-05',end:'2026-09-19',depth:[33,33],brands:['e.l.f. Cosmetics'],share:1},
 {id:'u7',r:'u',name:{en:'"Autumn edit" banner — terms not parsed',ar:'لافتة «تشكيلة الخريف» — لم تُحلَّل الشروط'},mech:'unclassified',start:'2026-09-15',end:'2026-10-02',share:0},
 {id:'u5',r:'u',name:{en:'Skincare 25% off',ar:'العناية بالبشرة: خصم 25%'},mech:'pct',start:'2026-09-24',end:'2026-10-06',depth:[25,25],cats:['skincare'],share:.7},
 {id:'u8',r:'u',name:{en:'Selected palettes 30% off',ar:'لوحات ظلال مختارة: خصم 30%'},mech:'pct',start:'2026-09-24',end:'2026-10-05',depth:[30,30],cats:['eyes'],share:.45},
 {id:'s1',r:'s',name:{en:'Spring savings (members)',ar:'توفير الربيع (للأعضاء)'},mech:'member',start:'2026-04-08',end:'2026-04-20',depth:[10,20],share:.85},
 {id:'s2',r:'s',name:{en:'Eid gifting 20% off',ar:'هدايا العيد: خصم 20%'},mech:'pct',start:'2026-05-20',end:'2026-05-31',depth:[20,20],cats:['fragrance','body'],share:.6},
 {id:'s3',r:'s',name:{en:'Summer sale, up to 50%',ar:'تخفيضات الصيف حتى 50%'},mech:'pct',start:'2026-07-01',end:'2026-07-20',depth:[20,50],share:.25},
 {id:'s4',r:'s',name:{en:'Fragrance minis: 3 for 2',ar:'عطور صغيرة: 3 بسعر 2'},mech:'bundle',start:'2026-08-18',end:'2026-09-05',depth:[33,33],cats:['fragrance'],share:.3},
 {id:'s5',r:'s',name:{en:'Free mini with AED 300 spend',ar:'هدية صغيرة عند إنفاق 300 د.إ'},mech:'gwp',start:'2026-09-01',end:'2026-09-30',share:0},
 {id:'s6',r:'s',name:{en:'Beauty Pass members: 20% off',ar:'أعضاء بيوتي باس: خصم 20%'},mech:'member',start:'2026-09-10',end:'2026-09-16',depth:[20,20],share:.85},
 {id:'s7',r:'s',name:{en:'Selected complexion 15% off',ar:'منتجات بشرة مختارة: خصم 15%'},mech:'pct',start:'2026-09-24',end:'2026-10-03',depth:[15,15],cats:['foundation','concealer'],share:.5},
 {id:'s8',r:'s',name:{en:'Mascara edit 20% off',ar:'تشكيلة الماسكارا: خصم 20%'},mech:'pct',start:'2026-09-24',end:'2026-10-07',depth:[20,20],cats:['eyes'],share:.3}
];
G_CAMPAIGNS.forEach(c=>{c.a=dayOf(c.start);c.b=dayOf(c.end)});
const G_NOT_OBS=[{r:'s',a:118,b:119,cats:null,why:{en:'Sephora run blocked (challenge page); days shown as not observed, never as out of stock.',ar:'حُجب تشغيل سيفورا (صفحة تحدٍّ)؛ تظهر الأيام كغير مرصودة وليست نفاداً.'}},
 {r:'u',a:178,b:178,cats:['skincare'],why:{en:'Ulta skincare count dropped 23% on 29 Sep; run marked partial.',ar:'انخفض عدد منتجات العناية في ألتا 23% في 29 سبتمبر؛ عُلِّم التشغيل جزئياً.'}}];

/* ---------- build catalogue ---------- */
const G_PRODUCTS=[];
(function build(){
  const shadeList=(kind,r)=>kind==='skin'?SKIN:kind==='lip'?LIPC:kind==='cheek'?CHEEK:kind==='brow'?BROW:[];
  const famFor=(kind,r)=>kind==='skin'?['Fair','Light','Medium','Tan','Deep']:kind==='lip'?['Nude','Pink','Red','Berry'].filter(()=>r()>.2):kind==='cheek'?['Pink','Coral','Berry'].filter(()=>r()>.25):[];
  const baseShades={skin:[30,56],lip:[8,30],cheek:[6,14],brow:[8,12]};
  function make(o,r){
    const p={id:o.id,brand:o.brand,name:o.name,cat:o.cat,type:o.type,unit:o.unit,cap:o.cap,liquid:o.liquid,hero:!!o.hero};
    p.listed={u:o.u!=null,s:o.s!=null};
    // sizes: some matched pairs are sold in different sizes
    p.size={u:o.size,s:o.size};
    if(!o.hero&&p.listed.u&&p.listed.s&&r()<.11){const f=[0.5,2,1.67][Math.floor(r()*3)];p.size.s=+(o.size*f).toFixed(o.size*f<10?1:0)}
    // regular price at end
    p.reg={u:o.u,s:o.s};
    if(!o.hero){const base=o.base*(0.85+r()*0.3);
      if(p.listed.u)p.reg.u=Math.round(base);
      if(p.listed.s){let g=r()<.34?0:(r()-.62)*.16;p.reg.s=Math.round((p.listed.u?p.reg.u:base)*Math.pow(p.size.s/p.size.u,0.85)*(1+g))}}
    // shades
    p.shades=[];p.shadeCount={u:0,s:0};p.fam=[];
    if(o.kind){const L=shadeList(o.kind);const [lo,hi]=baseShades[o.kind];const n=Math.round(lo+r()*(hi-lo));
      p.shadeCount={u:p.listed.u?n:0,s:p.listed.s?n:0};
      if(p.listed.u&&p.listed.s&&r()<.45){const k=r()<.5?'u':'s';p.shadeCount[k]=Math.max(3,n-Math.round(2+r()*12))}
      p.shades=o.kind==='skin'?L:L.slice().sort(()=>r()-.5).slice(0,6);p.fam=famFor(o.kind,r);if(!p.fam.length&&o.kind!=='brow')p.fam=[o.kind==='lip'?'Nude':'Pink']}
    p.rating={u:p.listed.u?[+(3.9+r()*.9).toFixed(1),Math.round(80+r()*r()*9000)]:null,s:p.listed.s?[+(3.9+r()*.9).toFixed(1),Math.round(80+r()*r()*9000)]:null};
    p.match=p.listed.u&&p.listed.s?(r()<.86?['GTIN exact',0.99]:['Name + size + brand',+(0.95+r()*.04).toFixed(2)]):null;
    // first / last seen
    p.first={u:0,s:0};p.last={u:DAYS-1,s:DAYS-1};
    RR.forEach(k=>{if(!p.listed[k]){p.first[k]=null;p.last[k]=null;return}
      if(o.launch&&(o.u==null||o.s==null)){p.first[k]=dayOf(o.launch);return}
      if(!o.hero&&r()<.07)p.first[k]=r()<.45?DAYS-1-Math.floor(r()*20):20+Math.floor(r()*140);
      if(!o.hero&&r()<.035)p.last[k]=60+Math.floor(r()*116)});
    // regular price history (changes)
    p.pchg=[];
    RR.forEach(k=>{if(p.listed[k]&&r()<.33)p.pchg.push({r:k,d:10+Math.floor(r()*160),from:Math.round(p.reg[k]*(1-(0.04+r()*.08)))})});
    // promotions from campaigns
    p.promos=[];
    G_CAMPAIGNS.forEach(c=>{if(!c.share||!p.listed[c.r])return;if(c.cats&&!c.cats.includes(p.cat))return;if(c.brands&&!c.brands.includes(p.brand))return;
      if(r()<c.share){const d=c.depth[0]+Math.round(r()*(c.depth[1]-c.depth[0])/5)*5;p.promos.push({c:c.id,r:c.r,a:Math.max(c.a,0),b:Math.min(c.b,DAYS-1),pct:d})}});
    // regular raised ahead of a current promotion (stated > true markdown)
    p.promos.filter(x=>x.b===DAYS-1).forEach(x=>{if(r()<.3){p.pchg=p.pchg.filter(e=>e.r!==x.r);p.pchg.push({r:x.r,d:x.a-(20+Math.floor(r()*25)),from:Math.round(p.reg[x.r]*(1-(0.1+r()*.1)))})}});
    // stock
    p.outs=[];p.lowNow={u:false,s:false};
    RR.forEach(k=>{if(!p.listed[k])return;if(r()<.22){const a=Math.floor(r()*170);p.outs.push({r:k,a,b:Math.min(DAYS-1,a+3+Math.floor(r()*22))})}
      if(r()<.05){const a=160+Math.floor(r()*17);p.outs.push({r:k,a,b:DAYS-1})}
      p.lowNow[k]=r()<.07});
    // pack-size change (shrinkflation ledger)
    p.sizeChg=[];
    if(!o.hero&&r()<.08&&p.listed.u){const k=p.listed.s&&r()<.5?'s':'u';const from=p.size[k];const to=+(from*(0.8+r()*.12)).toFixed(from<10?1:0);if(to<from){p.sizeChg.push({r:k,d:40+Math.floor(r()*130),from,to});p.size[k]=to;}}
    return p}
  let n=0;
  HERO.forEach(h=>{const [brand,name,cat,type,size,unit,cap,liquid,u,s,kind,launch]=h;const r=mulberry(hash(name));
    G_PRODUCTS.push(make({id:'h'+(n++),hero:true,brand,name,cat,type,size,unit,cap,liquid,u,s,kind,launch},r))});
  BRANDS.forEach(([brand,tier,at,cats,cap])=>{const r=mulberry(hash(brand));
    cats.forEach(cat=>{const lines=LINES[cat].filter(()=>r()<.62);(lines.length?lines:[LINES[cat][0]]).forEach(([ln,type,size,unit,base,kind])=>{
      if(G_PRODUCTS.some(p=>p.brand===brand&&p.name.startsWith(ln)))return;
      let u=1,s=1;if(at==='u')s=null;else if(at==='s')u=null;else{const x=r();if(x<.09)s=null;else if(x<.18)u=null}
      const liquid=kind==='skin'?SKIN[1+Math.floor(r()*8)]:kind==='lip'?LIPC[Math.floor(r()*LIPC.length)]:kind==='cheek'?CHEEK[Math.floor(r()*CHEEK.length)]:kind==='brow'?BROW[2]:
        ({skincare:['#F3F0EB','#F4E6D8','#E8F0EC','#F6E7EA'],fragrance:['#E9B872','#D9A3B5','#C8B27A','#B8C7D9','#EACB8F'],body:['#F6E3B4','#F4E6D8','#F0D2C7'],eyes:['#C19A7F','#1C1C1E'],foundation:['#DDE7EE']}[cat]||['#EEE'])[Math.floor(r()*4)%(({skincare:4,fragrance:5,body:3,eyes:2,foundation:1})[cat]||1)];
      G_PRODUCTS.push(make({id:'g'+(n++),brand,name:ln,cat,type,size,unit,cap,liquid:liquid||'#EEE',u,s,kind,base:base*tier},r))})})});
  // precompute daily series: price, size, stock code (0 not listed,1 in,2 low,3 out,4 not observed), promo pct
  G_PRODUCTS.forEach(p=>{p.d={};RR.forEach(k=>{if(!p.listed[k]){p.d[k]=null;return}
    const price=new Array(DAYS).fill(null),size=new Array(DAYS).fill(p.size[k]),stock=new Array(DAYS).fill(0),promo=new Array(DAYS).fill(0);
    const sc=p.sizeChg.find(e=>e.r===k);if(sc)for(let i=0;i<sc.d;i++)size[i]=sc.from;
    for(let i=p.first[k];i<=p.last[k];i++){let reg=p.reg[k];p.pchg.forEach(e=>{if(e.r===k&&i<e.d)reg=e.from});
      if(sc&&i<sc.d)reg=Math.round(reg*(0.97));
      let pct=0;p.promos.forEach(x=>{if(x.r===k&&i>=x.a&&i<=x.b)pct=Math.max(pct,x.pct)});
      const mech=pct?G_CAMPAIGNS.find(c=>p.promos.some(x=>x.r===k&&x.c===c.id&&i>=x.a&&i<=x.b)).mech:null;
      price[i]=pct&&mech!=='bundle'?Math.round(reg*(1-pct/100)):reg;promo[i]=pct;
      let st=1;p.outs.forEach(o=>{if(o.r===k&&i>=o.a&&i<=o.b)st=3});if(i===DAYS-1&&st===1&&p.lowNow[k])st=2;
      G_NOT_OBS.forEach(nb=>{if(nb.r===k&&i>=nb.a&&i<=nb.b&&(!nb.cats||nb.cats.includes(p.cat)))st=4});
      stock[i]=st;}
    p.d[k]={price,size,stock,promo}})});
  // keep a fixed ~10% of sizes consistent: if both listed and size differs, exact match impossible
  G_PRODUCTS.forEach(p=>{p.sameSize=p.listed.u&&p.listed.s&&p.size.u===p.size.s&&!p.sizeChg.length});
})();


/* ---------- static coverage (sample) ---------- */
const G_SOURCES=[
 {name:'Sephora UAE',k:'s',status:'ok',rung:1,rungName:{en:'curl_cffi, session reuse',ar:'curl_cffi مع إعادة استخدام الجلسة'},last:'30 Sep 06:10',cov:98.4,block:0.3,quar:7,cost:0},
 {name:'Ulta UAE',k:'u',status:'warn',rung:2,rungName:{en:'Playwright browser',ar:'متصفح Playwright'},last:'30 Sep 05:42',cov:97.1,block:0.8,quar:12,cost:0,warn:G_NOT_OBS[1].why},
 {name:'Sephora KSA',status:'pending',reason:{en:'Rungs 0–4 blocked (challenge page). Rung 5 proxy needs owner approval. Retried weekly; next try 5 Oct.',ar:'الدرجات 0–4 محجوبة (صفحة تحدٍّ). الدرجة 5 تتطلب موافقة المالك على الوكيل. تُعاد المحاولة أسبوعياً؛ التالية 5 أكتوبر.'}},
 {name:'Ulta KSA',status:'pending',reason:{en:'No KSA storefront found at last check. Retried weekly; next try 5 Oct.',ar:'لم يُعثر على متجر سعودي في آخر فحص. تُعاد المحاولة أسبوعياً؛ التالية 5 أكتوبر.'}}
];
const G_FIELDS=[['price',100,100],['regular',96.2,99.1],['promo',88.4,91.7],['stock',97.5,99.0],['shadeName',98.8,99.3],['shadeHex',71.2,84.6],['size',99.4,99.6],['gtin',62.3,78.9],['images',99.9,99.8],['ingredients',81.0,86.2],['reviews',94.1,88.0]];
const G_PRECISION=[['foundation',99.1,98.4,99.6,412],['lips',98.7,98.1,99.2,388],['eyes',98.9,98.2,99.4,301],['fragrance',99.4,98.9,99.8,265],['skincare',98.3,97.6,98.9,344]];
const G_QUAR=[
 {src:'Sephora UAE',what:'Dior Sauvage EDP 200 ml',why:{en:'Price AED 60.50 is ÷10 vs history (AED 605). Quarantined, ticket opened.',ar:'السعر 60.50 د.إ أقل بعشرة أضعاف من السجل (605 د.إ). حُجر وفُتحت تذكرة.'},when:'30 Sep 06:10'},
 {src:'Ulta UAE',what:'Morphe 9P palette',why:{en:'Discount 92% exceeds the 90% rule.',ar:'الخصم 92% يتجاوز قاعدة 90%.'},when:'30 Sep 05:42'},
 {src:'Ulta UAE',what:'Skincare category',why:G_NOT_OBS[1].why,when:'29 Sep 05:40'}
];

/* ---------- product renderings (inline SVG) ---------- */
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
const SHORT={'Fenty Beauty':'FENTY','Huda Beauty':'HUDA','Estée Lauder':'ESTĒE','Tarte':'tarte','Rare Beauty':'RARE','Charlotte Tilbury':'CT','MAC':'M·A·C','Anastasia Beverly Hills':'ABH','Laneige':'LANEIGE','Benefit Cosmetics':'benefit','Dior':'DIOR','Yves Saint Laurent':'YSL','Kayali':'KAYALI','Clinique':'CLINIQUE','The Ordinary':'The Ordinary.','Drunk Elephant':'DRUNK','Glow Recipe':'GLOW','Summer Fridays':'SUMMER','Sol de Janeiro':'SOL','Morphe':'MORPHE','Kylie Cosmetics':'KYLIE','e.l.f. Cosmetics':'e.l.f.','Sephora Collection':'SEPHORA','Ulta Beauty Collection':'ULTA','Fresh':'fresh','Tatcha':'TATCHA','Tree Hut':'TREE HUT','NARS':'NARS'};
function lum(hex){const n=parseInt(hex.slice(1),16);return ((n>>16)*299+((n>>8)&255)*587+(n&255)*114)/1000}
const onColor=hex=>lum(hex)>150?'#2A2A2C':'#FFFFFF';
const FF='font-family="Helvetica,Arial,sans-serif"';
const shadow=(rx=46)=>`<ellipse cx="100" cy="176" rx="${rx}" ry="5" fill="#000" opacity=".07"/>`;
const hl=(x,y,h)=>`<rect x="${x}" y="${y}" width="4" height="${h}" rx="2" fill="#fff" opacity=".45"/>`;
function productSVG(p,label,variant){
  const b=esc(SHORT[p.brand]||p.brand), c=p.cap, l=p.liquid, bg=BG[p.cat]||'#F4F1EC', sz=p.size.u||p.size.s;
  if(variant==='shades'){const sh=p.shades.length?p.shades:[l];let g='';const cols=4;sh.slice(0,12).forEach((h,i)=>{const x=34+(i%cols)*34,y=40+Math.floor(i/cols)*42;g+=`<rect x="${x}" y="${y}" width="28" height="34" rx="4" fill="${h}"/>`});
    return `<svg viewBox="0 0 200 200" role="img" aria-label="${esc((label||p.name)+' shade card')}"><rect width="200" height="200" fill="#FBF9F6"/><rect x="24" y="28" width="152" height="144" rx="8" fill="#fff" stroke="#E7E2DA"/>${g}</svg>`}
  let g='';
  switch(p.type){
   case 'foundation':g=shadow()+`<rect x="84" y="30" width="32" height="30" rx="4" fill="${c}"/><rect x="90" y="58" width="20" height="12" fill="#D8D4CE"/><rect x="66" y="68" width="68" height="106" rx="12" fill="#F3F1ED" stroke="#DAD5CD"/><rect x="71" y="80" width="58" height="89" rx="8" fill="${l}"/><rect x="78" y="112" width="44" height="28" rx="2" fill="#FFFFFF" opacity=".9"/><text x="100" y="124" font-size="8" text-anchor="middle" font-weight="700" fill="#2A2A2C" ${FF} letter-spacing=".6">${b}</text><text x="100" y="134" font-size="4.5" text-anchor="middle" fill="#6A6A6A" ${FF}>${sz} ${p.unit}</text>`+hl(74,84,70);break;
   case 'wand':g=shadow(30)+`<rect x="86" y="22" width="28" height="56" rx="5" fill="${c}"/><rect x="82" y="76" width="36" height="98" rx="8" fill="#F1EEEA" stroke="#DAD5CD"/><rect x="86" y="82" width="28" height="86" rx="5" fill="${l}"/><text x="100" y="128" font-size="7" text-anchor="middle" font-weight="700" fill="${onColor(l)}" ${FF} transform="rotate(-90 100 128)">${b}</text>`+hl(88,86,70);break;
   case 'blush':g=shadow(30)+`<circle cx="100" cy="46" r="20" fill="${c}" stroke="#DAD5CD"/><rect x="88" y="62" width="24" height="12" fill="#E4DFD8"/><rect x="80" y="72" width="40" height="102" rx="9" fill="#F3F1ED" stroke="#DAD5CD"/><rect x="85" y="80" width="30" height="88" rx="6" fill="${l}"/><text x="100" y="152" font-size="7" text-anchor="middle" font-weight="700" fill="#fff" ${FF}>${b}</text>`+hl(87,84,60);break;
   case 'compact':g=shadow(56)+`<circle cx="100" cy="104" r="62" fill="${c}" stroke="#D2CCC3"/><circle cx="100" cy="104" r="48" fill="${l}"/><circle cx="100" cy="104" r="48" fill="none" stroke="#fff" stroke-opacity=".25" stroke-width="6"/><path d="M70 88 Q100 70 130 88" stroke="#fff" stroke-opacity=".35" stroke-width="3" fill="none"/><text x="100" y="178" font-size="7" text-anchor="middle" font-weight="700" fill="#6A6259" ${FF} letter-spacing="1">${b}</text>`;break;
   case 'lipstick':g=shadow(48)+`<path d="M84 76 L84 44 Q84 34 100 28 L116 22 L116 76 Z" fill="${l}"/><path d="M110 26 L116 22 L116 76 L110 76 Z" fill="#000" opacity=".08"/><rect x="80" y="74" width="40" height="30" rx="2" fill="${c}" opacity=".85"/><rect x="76" y="102" width="48" height="72" rx="3" fill="${c}"/><rect x="76" y="102" width="48" height="5" fill="#fff" opacity=".25"/><text x="100" y="146" font-size="7" text-anchor="middle" font-weight="700" fill="${onColor(c)}" ${FF}>${b}</text>`+hl(80,108,60);break;
   case 'pencil':g=shadow(50)+`<g transform="rotate(-28 100 100)"><rect x="94" y="40" width="12" height="118" rx="3" fill="${c}"/><rect x="94" y="30" width="12" height="12" fill="#C9C6C0"/><path d="M96 30 L100 18 L104 30Z" fill="${l}"/><rect x="94" y="158" width="12" height="16" rx="3" fill="#2A2A2C"/><text x="100" y="110" font-size="6" text-anchor="middle" fill="${onColor(c)}" ${FF} transform="rotate(-90 100 110)">${b}</text></g>`;break;
   case 'mascara':g=shadow(26)+`<rect x="88" y="20" width="24" height="62" rx="4" fill="${c}"/><rect x="88" y="80" width="24" height="4" fill="#C9A36A"/><rect x="86" y="84" width="28" height="90" rx="6" fill="${lum(c)>150?'#2A2A2C':'#F1C6CF'}"/><text x="100" y="132" font-size="7.5" text-anchor="middle" font-weight="700" fill="${lum(c)>150?'#fff':'#2A2A2C'}" ${FF} transform="rotate(-90 100 132)">${b}</text>`+hl(89,88,70);break;
   case 'palette':{const pans=(p.shades.length?p.shades:['#F0D6C3','#D9B09A','#C18A73','#A56B55','#8E5645','#6B3F33','#E3C19E','#B97D5E','#4F2C24']).slice(0,9);
    g=shadow(72)+`<rect x="26" y="50" width="148" height="112" rx="10" fill="${c}" stroke="#D2CCC3"/>`;pans.forEach((s,i)=>{const x=46+(i%3)*38,y=66+Math.floor(i/3)*28;g+=`<rect x="${x}" y="${y}" width="32" height="22" rx="4" fill="${s}"/><rect x="${x+3}" y="${y+3}" width="10" height="3" rx="1.5" fill="#fff" opacity=".35"/>`});
    g+=`<text x="100" y="44" font-size="7" text-anchor="middle" font-weight="700" fill="#6A6259" ${FF} letter-spacing="1">${b}</text>`;break;}
   case 'perfume':g=shadow(52)+`<rect x="80" y="26" width="40" height="30" rx="3" fill="${c}"/><rect x="92" y="54" width="16" height="12" fill="#C8C3BA"/><rect x="54" y="64" width="92" height="110" rx="8" fill="#EDEAE4" stroke="#D2CCC3"/><rect x="60" y="76" width="80" height="92" rx="5" fill="${l}" opacity=".92"/><rect x="72" y="108" width="56" height="22" fill="#fff" opacity=".85"/><text x="100" y="123" font-size="8" text-anchor="middle" font-weight="700" fill="#2A2A2C" ${FF} letter-spacing="1">${b}</text>`+hl(64,80,76);break;
   case 'jar':g=shadow(52)+`<rect x="50" y="74" width="100" height="28" rx="6" fill="${c}"/><rect x="50" y="74" width="100" height="5" rx="2" fill="#fff" opacity=".25"/><rect x="54" y="100" width="92" height="74" rx="12" fill="${l}" stroke="#DAD5CD"/><text x="100" y="142" font-size="8" text-anchor="middle" font-weight="700" fill="#2A2A2C" ${FF} letter-spacing=".6">${b}</text><text x="100" y="152" font-size="4.5" text-anchor="middle" fill="#6A6A6A" ${FF}>${sz} ${p.unit}</text>`+hl(60,106,54);break;
   case 'pot':g=shadow(44)+`<rect x="60" y="96" width="80" height="22" rx="6" fill="${c}"/><rect x="62" y="116" width="76" height="58" rx="10" fill="${l}" stroke="#DAD5CD"/><text x="100" y="150" font-size="7.5" text-anchor="middle" font-weight="700" fill="#2A2A2C" ${FF}>${b}</text>`+hl(66,120,44);break;
   case 'dropper':g=shadow(36)+`<rect x="90" y="24" width="20" height="36" rx="10" fill="#2A2A2C"/><rect x="84" y="58" width="32" height="18" rx="2" fill="${c}" stroke="#D2CCC3"/><rect x="72" y="74" width="56" height="100" rx="8" fill="${l}" stroke="#D2CCC3"/><rect x="78" y="104" width="44" height="30" fill="#fff" opacity=".85"/><text x="100" y="118" font-size="6" text-anchor="middle" font-weight="700" fill="#2A2A2C" ${FF}>${b}</text><text x="100" y="127" font-size="4.5" text-anchor="middle" fill="#6A6A6A" ${FF}>${sz} ${p.unit}</text>`+hl(76,80,80);break;
   case 'tube':g=shadow(34)+`<path d="M78 40 L122 40 L118 150 L82 150 Z" fill="${l}" stroke="#D2CCC3"/><rect x="76" y="34" width="48" height="8" rx="2" fill="#E9E1D7"/><rect x="86" y="148" width="28" height="26" rx="4" fill="${c}" stroke="#C9BBAA"/><text x="100" y="96" font-size="7" text-anchor="middle" font-weight="700" fill="${onColor(l)}" ${FF} letter-spacing=".8">${b}</text>`+hl(84,46,90);break;
  }
  if(variant==='detail')return `<svg viewBox="30 20 140 160" role="img" aria-label="${esc((label||p.name)+' detail')}"><rect x="30" y="20" width="140" height="160" fill="${bg}"/>${g}</svg>`;
  return `<svg viewBox="0 0 200 200" role="img" aria-label="${esc(label||p.brand+' '+p.name)}"><rect width="200" height="200" fill="${bg}"/>${g}</svg>`;
}
