// Linux Electron visual evidence in a disposable, unmanaged profile. No engines or services start.
import {spawn} from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {setTimeout as delay} from 'node:timers/promises';
const root=process.cwd(), out=path.join(root,'docs/evidence/ui-workstation');
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
 const inventory=[];
 for(const theme of ['dark','light'])for(const [width,height] of [[1024,768],[1440,900],[1920,1080]]){

  await cmd('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
  for(const route of ['overview','models','engines','workers','optimize','live','compare','recipes','updates','settings','help']){
   await evaluate(`localStorage.setItem('lab.theme','${theme}'); location.hash='#/${route}'; location.reload()`);await delay(650);
   await evaluate('window.scrollTo(0,0)');
   const name=`${route}-${theme}-${width}x${height}.png`;const shot=await cmd('Page.captureScreenshot',{format:'png'});await fs.writeFile(path.join(out,name),Buffer.from(shot.data,'base64'));
   const geometry=await evaluate("({overflow:document.documentElement.scrollWidth>innerWidth, title:document.title, demo:document.body.innerText.includes('OFFLINE DEMO MODE'), node:typeof require})");
   if(geometry.overflow||!geometry.demo||geometry.node!=='undefined')throw Error(JSON.stringify({name,...geometry}));inventory.push({name,...geometry});
  }
 }
 for (const theme of ['dark', 'light']) {
  await cmd('Emulation.setDeviceMetricsOverride', {width:1440,height:900,deviceScaleFactor:1,mobile:false});
  await evaluate(`localStorage.setItem('lab.theme','${theme}');location.hash='#/optimize';location.reload()`);await delay(600);
  for(let step=0;step<4;step++) { await evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='Continue').click()");await delay(150); }
  await delay(300);
  for(const [name, expression] of [['preflight', 'window.scrollTo(0,0)'], ['preflight-details', 'window.scrollTo(0,document.body.scrollHeight)']]) {
   await evaluate(expression);const shot=await cmd('Page.captureScreenshot',{format:'png'});await fs.writeFile(path.join(out,`${name}-${theme}.png`),Buffer.from(shot.data,'base64'));
  }
  await evaluate("location.hash='#/live'");await delay(600);
  await evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='Trial 1').click();document.querySelector('.run-workspace').scrollIntoView()");
  const shot=await cmd('Page.captureScreenshot',{format:'png'});await fs.writeFile(path.join(out,`trial-inspector-${theme}.png`),Buffer.from(shot.data,'base64'));
 }
 await cmd('Emulation.clearDeviceMetricsOverride');
 await evaluate("localStorage.removeItem('lab.demo'); location.href='lab://app/index.html#/live'");await delay(900);
 const error=await cmd('Page.captureScreenshot',{format:'png'});await fs.writeFile(path.join(out,'controller-disconnected.png'),Buffer.from(error.data,'base64'));
 await fs.writeFile(path.join(out,'inventory.json'),JSON.stringify({platform:process.platform,version:'0.6.0',source:'Explicit offline demo fixtures; disconnected uses unconfigured IPC controller',inventory},null,2));
 console.log(`Captured ${inventory.length} screenshots; no document overflow; sandbox renderer has no require. Profile: ${profile}`);
 await delay(1000);
}finally{socket?.close();child.kill('SIGTERM');await delay(1000);if(child.exitCode===null)child.kill('SIGKILL');}
