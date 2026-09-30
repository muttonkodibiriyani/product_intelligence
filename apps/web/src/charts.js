/* Minimal inline-SVG chart kit: line + crosshair + brush, context strip, bars, heatmap, tooltips. */
const CH={};
const C_U='#E07C9D', C_S='#5E9AD4', GRID='#EEF0F4', AX='#8A90A0';
function niceScale(lo,hi,n=4){if(lo===hi){lo-=1;hi+=1}const raw=(hi-lo)/n,mag=Math.pow(10,Math.floor(Math.log10(raw))),f=raw/mag;const step=(f<=1?1:f<=2?2:f<=2.5?2.5:f<=5?5:10)*mag;return {lo:Math.floor(lo/step)*step,hi:Math.ceil(hi/step)*step,step}}
function tipAttr(lines){return `data-tip="${esc(lines.join('\n'))}"`}

function lineChart(o){
  const w=o.w||680,h=o.h||230,compact=o.compact,l=compact?34:44,r=compact?10:52,tp=12,bt=24,a=o.a,b=o.b,n=b-a+1;
  const vals=o.series.flatMap(s=>s.vals?s.vals.slice(a,b+1).filter(v=>v!=null):[]);
  if(!vals.length)return emptyChart(w,h);
  let mn=Math.min(...vals),mx=Math.max(...vals);if(o.ref!=null){mn=Math.min(mn,o.ref);mx=Math.max(mx,o.ref)}
  const pad=(mx-mn)*.08||1;const sc=niceScale(mn-pad,mx+pad,compact?3:4);
  const x=i=>l+(n===1?0:(i-a)*(w-l-r)/(n-1)), y=v=>tp+(sc.hi-v)/(sc.hi-sc.lo)*(h-tp-bt);
  CH[o.id]={type:'line',w,h,l,r,tp,bt,a,b,series:o.series,fmt:o.fmt||(v=>v),brush:o.brush!==false,y,x};
  let s=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(o.title||'')}" class="lc"><title>${esc(o.title||'')}</title>`;
  (o.bands||[]).forEach(bd=>{if(bd.b<a||bd.a>b)return;const x0=x(Math.max(bd.a,a))-2,x1=x(Math.min(bd.b,b))+2;s+=`<rect x="${x0}" y="${tp}" width="${Math.max(4,x1-x0)}" height="${h-tp-bt}" fill="url(#hatch)" opacity=".9"><title>${esc(bd.label)}</title></rect>`});
  for(let v=sc.lo;v<=sc.hi+1e-9;v+=sc.step){s+=`<line x1="${l}" x2="${w-r}" y1="${y(v)}" y2="${y(v)}" stroke="${GRID}"/><text x="${l-6}" y="${y(v)+4}" font-size="${compact?9.5:10.5}" text-anchor="end" fill="${AX}">${o.fmt?o.fmt(+v.toFixed(2),true):+v.toFixed(2)}</text>`}
  if(o.ref!=null)s+=`<line x1="${l}" x2="${w-r}" y1="${y(o.ref)}" y2="${y(o.ref)}" stroke="#B3ADA3" stroke-dasharray="3 3"/>`;
  const nt=compact?3:5;for(let k=0;k<nt;k++){const i=Math.round(a+k*(n-1)/(nt-1));s+=`<text x="${x(i)}" y="${h-6}" font-size="${compact?9.5:10.5}" text-anchor="${k===0?'start':k===nt-1?'end':'middle'}" fill="${AX}">${fmtD(dayDate(i))}</text>`}
  o.series.forEach(se=>{if(!se.vals)return;let d='',pen=false;for(let i=a;i<=b;i++){const v=se.vals[i];if(v==null){pen=false;continue}d+=`${pen?'L':'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`;pen=true}
    s+=`<path class="ln" d="${d}" fill="none" stroke="${se.color}" stroke-width="${compact?1.7:2.2}" ${se.dash?'stroke-dasharray="6 3"':''} stroke-linejoin="round" stroke-linecap="round"/>`;
    let li=b;while(li>a&&se.vals[li]==null)li--;const lv=se.vals[li];if(lv!=null){s+=`<circle cx="${x(li)}" cy="${y(lv)}" r="3.2" fill="${se.color}"/>`;if(!compact)s+=`<text x="${x(li)+7}" y="${y(lv)+4}" font-size="11" font-weight="650" fill="${se.color}">${(o.fmt||(v=>v))(lv)}</text>`}});
  s+=`<g id="${o.id}-xh" style="display:none" pointer-events="none"><line y1="${tp}" y2="${h-bt}" stroke="#1E2226" stroke-opacity=".35"/>${o.series.map((se,k)=>`<circle r="4" fill="#fff" stroke="${se.color}" stroke-width="2" data-k="${k}"/>`).join('')}</g>`;
  s+=`<rect id="${o.id}-br" class="brushrect" y="${tp}" height="${h-tp-bt}" x="0" width="0" style="display:none"/>`;
  s+=`<rect class="ov" data-chart="${o.id}" x="${l}" y="${tp}" width="${w-l-r}" height="${h-tp-bt}" fill="transparent" style="cursor:${o.brush!==false?'crosshair':'default'}" tabindex="-1"/>`;
  return s+HATCH+'</svg>';
}
const HATCH=`<defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="#F4F1EC"/><line x1="0" y1="0" x2="0" y2="6" stroke="#D9D3C9" stroke-width="2"/></pattern></defs>`;
function emptyChart(w,h,msg){return `<svg viewBox="0 0 ${w} ${h}"><rect x="1" y="1" width="${w-2}" height="${h-2}" rx="8" fill="#FBFAF8" stroke="#E9E5DE" stroke-dasharray="4 4"/><text x="${w/2}" y="${h/2+4}" text-anchor="middle" font-size="12" fill="${AX}">${esc(msg||t('noData'))}</text></svg>`}

function contextStrip(o){
  const w=o.w||680,h=o.h||46,l=o.l??44,r=o.r??52,tp=4,bt=4;const vals=o.vals.filter(v=>v!=null);if(!vals.length)return '';
  const mn=Math.min(...vals),mx=Math.max(...vals);const x=i=>l+i*(w-l-r)/(DAYS-1),y=v=>tp+(mx-v)/((mx-mn)||1)*(h-tp-bt);
  CH[o.id]={type:'ctx',w,h,l,r,tp,bt,a:0,b:DAYS-1,x};
  let d='',pen=false;o.vals.forEach((v,i)=>{if(v==null){pen=false;return}d+=`${pen?'L':'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`;pen=true});
  const x0=x(o.a),x1=x(o.b);
  return `<svg viewBox="0 0 ${w} ${h}" class="ctx" role="img" aria-label="${esc(t('rangeCtx'))}"><rect x="${l}" y="0" width="${w-l-r}" height="${h}" rx="6" fill="#F6F4F0"/><path d="${d}" fill="none" stroke="#B3ADA3" stroke-width="1.3"/>
   <rect x="${l}" y="0" width="${Math.max(0,x0-l)}" height="${h}" fill="#FBFAF7" opacity=".7"/><rect x="${x1}" y="0" width="${Math.max(0,w-r-x1)}" height="${h}" fill="#FBFAF7" opacity=".7"/>
   <rect x="${x0}" y="0.5" width="${Math.max(2,x1-x0)}" height="${h-1}" rx="5" fill="none" stroke="#1E2226" stroke-opacity=".55"/>
   <rect x="${x0-3}" y="${h/2-9}" width="6" height="18" rx="3" fill="#1E2226" opacity=".6"/><rect x="${x1-3}" y="${h/2-9}" width="6" height="18" rx="3" fill="#1E2226" opacity=".6"/>
   <rect id="${o.id}-br" class="brushrect" y="0" height="${h}" x="0" width="0" style="display:none"/>
   <rect class="ov" data-chart="${o.id}" x="${l}" y="0" width="${w-l-r}" height="${h}" fill="transparent" style="cursor:ew-resize"/></svg>`;
}

function bars(o){
  const w=o.w||440,h=o.h||200,l=o.l||34,r=8,tp=10,bt=o.bt||26,cats=o.cats,ser=o.series,gw=(w-l-r)/cats.length;
  const bw=Math.max(3,Math.min(o.maxBar||20,(gw-4)/ser.length-2));
  const all=ser.flatMap(s=>s.vals);const mx=Math.max(1,...all);const sc=niceScale(0,mx,3);const y=v=>tp+(1-v/sc.hi)*(h-tp-bt);
  let s=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(o.title||'')}" class="bars"><title>${esc(o.title||'')}</title>`;
  for(let v=0;v<=sc.hi+1e-9;v+=sc.step)s+=`<line x1="${l}" x2="${w-r}" y1="${y(v)}" y2="${y(v)}" stroke="${GRID}"/><text x="${l-5}" y="${y(v)+4}" font-size="10" text-anchor="end" fill="${AX}">${o.yfmt?o.yfmt(v):+v.toFixed(1)}</text>`;
  if(o.zeroAt!=null){const zx=l+gw*o.zeroAt;s+=`<line x1="${zx}" x2="${zx}" y1="${tp}" y2="${h-bt}" stroke="#1E2226" stroke-opacity=".4" stroke-dasharray="3 3"/>`}
  cats.forEach((c,i)=>{const cx=l+gw*i+gw/2,tw=bw*ser.length+2*(ser.length-1);const dim=o.sel!=null&&o.sel!==i;
    ser.forEach((se,j)=>{const v=se.vals[i],bx=cx-tw/2+j*(bw+2);s+=`<rect class="bar" x="${bx}" y="${y(v)}" width="${bw}" height="${Math.max(0,y(0)-y(v))}" rx="2" fill="${se.color}" opacity="${dim?.28:1}"/>`});
    const tipLines=[o.tipTitle?o.tipTitle(i):c,...ser.map(se=>`${se.name}: ${o.fmt?o.fmt(se.vals[i]):se.vals[i]}`)];if(o.tipExtra)tipLines.push(o.tipExtra);
    s+=`<rect class="hit${o.act?' act':''}" x="${l+gw*i}" y="${tp}" width="${gw}" height="${h-tp-bt}" fill="transparent" ${tipAttr(tipLines)} ${o.act?`data-act="${o.act(i)}" tabindex="0" role="button" aria-label="${esc(tipLines.join(', '))}"`:''}/>`;
    if(o.every?i%o.every===0:true)s+=`<text x="${cx}" y="${h-8}" font-size="10" text-anchor="middle" fill="${o.sel===i?'#1E2226':'#6A717A'}" font-weight="${o.sel===i?700:400}">${esc(c)}</text>`});
  return s+'</svg>';
}

function heatmap(o){
  const rows=o.rows,cols=o.cols,cw=o.cw||64,rh=o.rh||34,l=o.l||110,tp=26,w=l+cols.length*cw+4,h=tp+rows.length*rh+4;
  const mx=Math.max(1,...o.vals.flat());
  let s=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(o.title||'')}" class="heat"><title>${esc(o.title||'')}</title>`;
  cols.forEach((c,j)=>s+=`<text x="${l+j*cw+cw/2}" y="16" font-size="10.5" text-anchor="middle" fill="${AX}">${esc(c)}</text>`);
  rows.forEach((rw,i)=>{s+=`<text x="${l-8}" y="${tp+i*rh+rh/2+4}" font-size="11" text-anchor="end" fill="#3C434B">${esc(rw)}</text>`;
    cols.forEach((c,j)=>{const v=o.vals[i][j];const k=v/mx;const sel=o.sel&&o.sel[0]===i&&o.sel[1]===j;const dim=o.sel&&!sel;
      s+=`<rect x="${l+j*cw+2}" y="${tp+i*rh+2}" width="${cw-4}" height="${rh-4}" rx="5" fill="${v?o.color:'#F6F4F0'}" fill-opacity="${v?(0.14+0.86*k).toFixed(2):1}" ${sel?'stroke="#1E2226" stroke-width="2"':''} opacity="${dim?.45:1}"/>`;
      s+=`<text x="${l+j*cw+cw/2}" y="${tp+i*rh+rh/2+4}" font-size="11" text-anchor="middle" font-weight="600" fill="${k>.55?'#fff':'#3C434B'}" pointer-events="none">${v||'·'}</text>`;
      s+=`<rect class="hit${v&&o.act?' act':''}" x="${l+j*cw+2}" y="${tp+i*rh+2}" width="${cw-4}" height="${rh-4}" fill="transparent" ${tipAttr([rw+' · '+c,o.tip(v,i,j)])} ${v&&o.act?`data-act="${o.act(i,j)}" tabindex="0" role="button" aria-label="${esc(rw+', '+c+': '+o.tip(v,i,j))}"`:''}/>`})});
  return s+'</svg>';
}

/* ---------- tooltip + pointer interactions ---------- */
let TIP=null,DRAG=null;
function tipShow(text,cx,cy){if(!TIP){TIP=document.createElement('div');TIP.id='tip';TIP.setAttribute('role','tooltip');document.body.appendChild(TIP)}
  const [h,...rest]=text.split('\n');TIP.innerHTML=`<b>${esc(h)}</b>${rest.map(x=>`<div>${esc(x)}</div>`).join('')}`;TIP.style.display='block';
  const r=TIP.getBoundingClientRect();let x=cx+14,y=cy+14;if(x+r.width>innerWidth-8)x=cx-r.width-14;if(y+r.height>innerHeight-8)y=cy-r.height-14;TIP.style.left=x+'px';TIP.style.top=y+'px'}
function tipHide(){if(TIP)TIP.style.display='none'}
function svgX(svg,clientX){const r=svg.getBoundingClientRect();const vb=svg.viewBox.baseVal;return vb.x+(clientX-r.left)/r.width*vb.width}
function idxAt(c,sx){const n=c.b-c.a+1;return Math.max(c.a,Math.min(c.b,Math.round(c.a+(sx-c.l)/(c.w-c.l-c.r)*(n-1))))}
document.addEventListener('pointerover',e=>{const el=e.target.closest&&e.target.closest('[data-tip]');if(el&&!DRAG)tipShow(el.getAttribute('data-tip'),e.clientX,e.clientY)});
document.addEventListener('pointerout',e=>{const el=e.target.closest&&e.target.closest('[data-tip]');if(el)tipHide()});
document.addEventListener('focusin',e=>{const el=e.target.closest&&e.target.closest('[data-tip]');if(el){const r=el.getBoundingClientRect();tipShow(el.getAttribute('data-tip'),r.left+r.width/2,r.top+r.height/2)}});
document.addEventListener('focusout',tipHide);
document.addEventListener('pointerdown',e=>{const ov=e.target.closest&&e.target.closest('[data-chart]');if(!ov)return;const c=CH[ov.dataset.chart];if(!c||(c.type==='line'&&!c.brush))return;
  const svg=ov.ownerSVGElement;const i=idxAt(c,svgX(svg,e.clientX));DRAG={id:ov.dataset.chart,svg,i0:i,i1:i,c};ov.setPointerCapture(e.pointerId);tipHide();e.preventDefault()});
document.addEventListener('pointermove',e=>{
  if(DRAG){const {c,svg}=DRAG;DRAG.i1=idxAt(c,svgX(svg,e.clientX));const br=document.getElementById(DRAG.id+'-br');const a=Math.min(DRAG.i0,DRAG.i1),b=Math.max(DRAG.i0,DRAG.i1);
    const X=i=>c.l+(i-c.a)*(c.w-c.l-c.r)/(c.b-c.a);br.style.display='';br.setAttribute('x',X(a));br.setAttribute('width',Math.max(1,X(b)-X(a)));
    tipShow(`${fmtD(dayDate(a))} – ${fmtD(dayDate(b))}\n${b-a+1} ${t('days')}`,e.clientX,e.clientY);return}
  const ov=e.target.closest&&e.target.closest('[data-chart]');if(!ov)return;const c=CH[ov.dataset.chart];if(!c||c.type!=='line')return;
  const i=idxAt(c,svgX(ov.ownerSVGElement,e.clientX));const g=document.getElementById(ov.dataset.chart+'-xh');if(!g)return;g.style.display='';const X=c.x(i);
  g.querySelector('line').setAttribute('x1',X);g.querySelector('line').setAttribute('x2',X);
  const lines=[fmtD(dayDate(i))+' 2026'];g.querySelectorAll('circle').forEach(ci=>{const se=c.series[+ci.dataset.k];const v=se.vals?se.vals[i]:null;if(v==null){ci.style.display='none';lines.push(`${se.name}: ${t('noObs')}`);return}ci.style.display='';ci.setAttribute('cx',X);ci.setAttribute('cy',c.y(v));lines.push(`${se.name}: ${c.fmt(v)}`)});
  if(c.extra)lines.push(...c.extra(i));tipShow(lines.join('\n'),e.clientX,e.clientY)});
document.addEventListener('pointerup',e=>{if(!DRAG)return;const d=DRAG;DRAG=null;tipHide();const a=Math.min(d.i0,d.i1),b=Math.max(d.i0,d.i1);
  if(d.c.type==='ctx'&&b-a<6){const span=S.range[1]-S.range[0];let na=Math.round(a-span/2);na=Math.max(0,Math.min(DAYS-1-span,na));window.onBrush&&window.onBrush(na,na+span);return}
  if(b-a>=6)window.onBrush&&window.onBrush(a,b);else{const br=document.getElementById(d.id+'-br');if(br)br.style.display='none'}});
document.addEventListener('pointerleave',()=>tipHide());
document.addEventListener('mouseout',e=>{const ov=e.target.closest&&e.target.closest('[data-chart]');if(ov&&!DRAG){const g=document.getElementById(ov.dataset.chart+'-xh');if(g)g.style.display='none';tipHide()}});
