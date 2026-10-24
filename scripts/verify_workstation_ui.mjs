// Linux Electron visual evidence in a disposable, unmanaged profile. No engines or services start.
import {auditContrast} from './workstation-contrast.mjs';
import {spawn} from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {setTimeout as delay} from 'node:timers/promises';
const root=process.cwd(), out=path.join(root,'docs/evidence/ui-workstation-completion');
await fs.mkdir(out,{recursive:true});
const profile=await fs.mkdtemp(path.join(os.tmpdir(),'lab-ui-design-'));
const child=spawn(path.join(root,'apps/desktop/node_modules/electron/dist/electron'),['--ozone-platform=x11','--remote-debugging-port=0',path.join(root,'apps/desktop')],{env:{...process.env,LAB_DESKTOP_MANAGED:'0',XDG_CONFIG_HOME:profile,XDG_CACHE_HOME:path.join(profile,'cache')},stdio:['ignore','ignore','pipe']});
let stderr='',socket,seq=0;const pending=new Map();child.stderr.on('data',d=>stderr+=d);
function cmd(method,params={}){const id=++seq;return new Promise((resolve,reject)=>{pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});}
const evaluate=async expression=>{const r=await cmd('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
try {
 let target;for(let i=0;i<150;i++){const ep=stderr.match(/DevTools listening on (ws:\/\/127\.0\.0\.1:\d+)\//)?.[1];if(ep){const ts=await(await fetch(ep.replace('ws:','http:')+'/json/list')).json();target=ts.find(t=>t.url.startsWith('lab://'));if(target)break;}await delay(200);}
 if(!target)throw Error(stderr);
 socket=new WebSocket(target.webSocketDebuggerUrl);await new Promise(r=>socket.addEventListener('open',r,{once:true}));socket.addEventListener('message',e=>{const m=JSON.parse(e.data),p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result);}});
 await delay(500);
 await evaluate("localStorage.setItem('lab.demo','1'); location.search='?demo=1'");await delay(1200);
 const report=[];
 const capture=async(name)=>{const shot=await cmd('Page.captureScreenshot',{format:'png'});await fs.writeFile(path.join(out,name+'.png'),Buffer.from(shot.data,'base64'));};
 const go=async(scenario,route,theme)=>{
  await evaluate(`localStorage.setItem('lab.theme', '${theme}');location.href='lab://app/index.html?demo=1&demoScenario=${scenario}#/${route}'`);await delay(100);await cmd('Page.reload');await delay(700);
  if(await evaluate('document.documentElement.dataset.theme')!==theme)throw Error('Theme failed to apply');
 };
 for(const theme of ['dark','light'])for(const [width,height] of [[1024,768],[1440,900],[1920,1080]]) {
  await cmd('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
  for(const route of ['overview','models','engines','workers','optimize','live','compare','recipes','updates','settings','help']) {
   await go('default',route,theme);await evaluate('window.scrollTo(0,0)');
   const contrast=await evaluate('('+auditContrast.toString()+')()');
   const overflow=await evaluate('document.documentElement.scrollWidth>innerWidth');
   await capture(`${route}-${theme}-${width}x${height}`);
   report.push({route,theme,width,height,scenario:'default',overflow,contrast});
   if(overflow)throw Error(`Overflow on ${route} ${width}`);
  }
 }
 for(const theme of ['dark','light']) {
  await cmd('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
  for(const scenario of ['stale','partial','empty','error','stream-gap','large','failed']) {
   const route=scenario==='stale'?'optimize':scenario==='large'?'compare':'live';
   await go(scenario,route,theme);
   if(scenario==='stale') {
    for(let step=0;step<4;step++){await evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='Continue').click()");await delay(120);}
    const blocked=await evaluate("document.body.innerText.includes('cmd-demo-stale-snapshot')&&!document.body.innerText.includes('Create experiment')");if(!blocked)throw Error('Stale preflight not blocked');
   }
   if(scenario==='large') {
    await cmd('Performance.enable');await cmd('HeapProfiler.collectGarbage');const before=await cmd('Performance.getMetrics');await delay(2000);const after=await cmd('Performance.getMetrics');
    const metric=(m,n)=>m.metrics.find(v=>v.name===n)?.value;
    report.push({scenario,theme,performance:{taskSecondsOver2s:metric(after,'TaskDuration')-metric(before,'TaskDuration'),scriptSecondsOver2s:metric(after,'ScriptDuration')-metric(before,'ScriptDuration'),heapBytes:metric(after,'JSHeapUsedSize'),domNodes:metric(after,'Nodes')},coverage:await evaluate("({attachedNodes:document.querySelectorAll('*').length,rows:document.querySelectorAll('tbody tr').length,marks:document.querySelectorAll('svg.chart circle,svg.chart rect').length,text:document.body.innerText.includes('200 of 5000')})")});
   }
   await capture(`${scenario}-${theme}`);
   report.push({scenario,route,theme,contrast:await evaluate('('+auditContrast.toString()+')()'),overflow:await evaluate('document.documentElement.scrollWidth>innerWidth')});
   if(scenario==='large') {
    await evaluate("location.hash='#/live'");await delay(700);
    const bound=await evaluate("document.querySelectorAll('.run-workspace tbody tr').length");if(bound!==100)throw Error('Trial rows not bounded: '+bound);
    await evaluate("document.querySelector('.run-workspace').scrollIntoView()");await capture(`large-trials-${theme}`);
   }
  }
 }
 await fs.writeFile(path.join(out,'qa-report.json'),JSON.stringify({platform:process.platform,app:'0.6.0 source build',source:'Explicit offline fixture scenarios only',report},null,2));
 const failures=report.flatMap(r=>r.contrast?.failures??[]);
 console.log(JSON.stringify({captures:report.length,contrastFailures:failures.length,report:path.join(out,'qa-report.json')}));
}finally{socket?.close();child.kill('SIGTERM');await delay(1000);if(child.exitCode===null)child.kill('SIGKILL');}
