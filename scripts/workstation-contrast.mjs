// Runs inside the renderer on labelled fixtures. Backgrounds are composited through ancestors.
export function auditContrast() {
  const parse = value => {
    if (value.startsWith('color(srgb')) { const v=value.match(/[\d.]+/g).map(Number); return [v[0]*255,v[1]*255,v[2]*255,v[3]??1]; }
    const v=value.match(/[\d.]+/g)?.map(Number); return v?.length>=3 ? [v[0],v[1],v[2],v[3]??1] : [0,0,0,0];
  };
  const blend=(a,b)=>[0,1,2].map(i=>a[i]*a[3]+b[i]*(1-a[3])).concat(1);
  const luminance=c=>c.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
  const failures=[], pairs=new Map(); let checked=0;
  const inspect=el=>{
    const style=getComputedStyle(el); if(!el.getClientRects().length || el.closest('[disabled], [aria-hidden="true"]') || style.visibility==='hidden')return;
    const chain=[];for(let node=el;node instanceof Element;node=node.parentElement)chain.unshift(node);
    let bg=[255,255,255,1];for(const node of chain)bg=blend(parse(getComputedStyle(node).backgroundColor),bg);
    const fg=blend(parse(el instanceof SVGElement ? style.fill : style.color),bg);
    const l1=luminance(fg),l2=luminance(bg),ratio=(Math.max(l1,l2)+.05)/(Math.min(l1,l2)+.05);
    const size=parseFloat(style.fontSize),weight=parseInt(style.fontWeight)||400;
    const required=size>=24||(size>=18.66&&weight>=700)?3:4.5;
    checked++;const key=[style.color,style.backgroundColor,bg.join(','),required].join('|');
    if(!pairs.has(key))pairs.set(key,{foreground:style.color,background:bg.slice(0,3).map(Math.round),ratio:+ratio.toFixed(2),required});
    if(ratio+.01<required)failures.push({tag:el.tagName,class:el.getAttribute('class'),text:el.textContent?.trim().slice(0,90),ratio:+ratio.toFixed(2),required});
  };
  const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let node;
  while((node=walker.nextNode()))if(node.textContent.trim())inspect(node.parentElement);
  document.querySelectorAll('input:not([type="range"]):not([type="checkbox"]):not([type="radio"]),select,textarea').forEach(inspect);
  return {checked,pairs:[...pairs.values()],failures};
}
