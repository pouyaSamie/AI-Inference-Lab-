// Actual Electron in an isolated unmanaged profile. Update/runtime states below are explicit UI fixtures.
import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { setTimeout as delay } from 'node:timers/promises';
const root=process.cwd(), out=path.join(root,'docs/evidence/journey-0.6.2');
await fs.mkdir(out,{recursive:true});
const html=path.join(root,'apps/desktop/journey-qa.html');
await fs.writeFile(html,`<div id="root"></div><script type="module" src="${path.join(root, "scripts/fixtures/journey-qa.tsx")}"></script>`);
try {
 const {build}=await import('../apps/desktop/node_modules/vite/dist/node/index.js');
 await build({configFile:false,root:path.join(root,'apps/desktop'),base:'./',resolve:{alias:{react:path.join(root,'apps/desktop/node_modules/react')}},esbuild:{jsx:'automatic'},build:{outDir:'dist',emptyOutDir:false,rollupOptions:{input:html}}});
}finally{await fs.rm(html,{force:true});}
const profile=await fs.mkdtemp(path.join(os.tmpdir(),'lab-journey-qa-'));
const child=spawn(path.join(root,'apps/desktop/node_modules/electron/dist/electron'),['--ozone-platform=x11','--inspect=0',path.join(root,'apps/desktop')],{env:{...process.env,LAB_DESKTOP_MANAGED:'0',XDG_CONFIG_HOME:profile},stdio:['ignore','ignore','pipe']});
let output='',socket,id=0;child.stderr.on('data',d=>output+=d);const pending=new Map();
try {
 let url;for(let i=0;i<100;i++){url=output.match(/Debugger listening on (ws:\/\/127\.0\.0\.1:\d+\/[^\s]+)/)?.[1];if(url)break;await delay(100);}if(!url)throw Error(output);
 socket=new WebSocket(url);await new Promise(r=>socket.addEventListener('open',r,{once:true}));
 socket.addEventListener('message',e=>{const m=JSON.parse(e.data);if(pending.has(m.id)){pending.get(m.id)(m.result);pending.delete(m.id);}});
 const evaluate=expression=>new Promise(resolve=>{const n=++id;pending.set(n,resolve);socket.send(JSON.stringify({id:n,method:'Runtime.evaluate',params:{expression,returnByValue:true,awaitPromise:true}}));});
 await delay(1200);
 const setup=await evaluate(`(()=>{const e=process.mainModule.require('electron');global.qaWindow=e.BrowserWindow.getAllWindows()[0];global.qaUpdate={enabled:false,checking:false,checked_at:'2026-10-24',error:null,operation:'Downloading engine archive',installation:{engine_id:'llamacpp',asset_id:123,version:'0.7.0',phase:'downloading',bytes_done:52428800,bytes_total:104857600},releases:['llamacpp','strata'].map(engine_id=>({engine_id,version:engine_id==='llamacpp'?'0.7.0':'0.1.48',update:'available',installed_version:'previous',assets:[{id:123,name:'linux-cuda.tar.gz',size:104857600,digest:'sha256:'+'a'.repeat(64)}],recommendation:{asset_id:123,label:'NVIDIA GPU acceleration',hardware:'UI fixture GPU',reason:'UI fixture compatibility match'},support:{size:0}}))};e.ipcMain.removeHandler('lab:engines:updates-status');e.ipcMain.handle('lab:engines:updates-status',()=>global.qaUpdate);return {iconSize:e.nativeImage.createFromPath(${JSON.stringify(path.join(root,"apps/desktop/dist/app-icon.png"))}).getSize(),classSwitch:e.app.commandLine.getSwitchValue("class")};})()`);
 if(setup.result?.value?.iconSize?.width !== 256)throw Error("Window icon asset failed nativeImage validation");
 const records=[];
 for(const theme of ['dark','light'])for(const [width,height] of [[1024,768],[1440,900],[1920,1080]])for(const route of ['overview','updates','models','live']) {
  const res=await evaluate(`(async()=>{qaWindow.setContentSize(${width},${height});await qaWindow.webContents.executeJavaScript("localStorage.setItem('lab.demo','1');localStorage.setItem('lab.setup.complete','1');localStorage.setItem('lab.theme','${theme}');location.hash='#/${route}';location.reload()");await new Promise(r=>setTimeout(r,650));await qaWindow.webContents.executeJavaScript("window.scrollTo(0,0)");const geometry=await qaWindow.webContents.executeJavaScript("({overflow:document.documentElement.scrollWidth>innerWidth,node:typeof require,title:document.title})");return {image:(await qaWindow.webContents.capturePage()).toDataURL(),...geometry};})()`);
  if(res.exceptionDetails)throw Error(JSON.stringify(res.exceptionDetails));const {image,...geometry}=res.result.value;
  if(geometry.overflow||geometry.node!=='undefined')throw Error(JSON.stringify(geometry));
  const name=`${route}-${theme}-${width}x${height}.png`;await fs.writeFile(path.join(out,name),Buffer.from(image.split(',')[1],'base64'));records.push({name,...geometry});
 }
 for(const theme of ['dark','light'])for(const phase of ['downloading','unpacking','complete','failed']) {
  const res=await evaluate(`(async()=>{qaUpdate.installation.phase='${phase}';qaUpdate.operation=${phase === 'downloading' ? "'Downloading engine archive'" : phase === 'unpacking' ? "'Checking and unpacking archive'" : 'null'};qaUpdate.error=${phase === 'failed' ? "'Download failed: fixture checksum mismatch'" : 'null'};qaWindow.setContentSize(1024,768);await qaWindow.loadURL('lab://app/journey-qa.html?theme=${theme}');await new Promise(r=>setTimeout(r,700));return (await qaWindow.webContents.capturePage()).toDataURL();})()`);
  if(res.exceptionDetails)throw Error(JSON.stringify(res.exceptionDetails));const name=`maintenance-${phase}-${theme}.png`;await fs.writeFile(path.join(out,name),Buffer.from(res.result.value.split(',')[1],'base64'));records.push({name,fixture:true});
 }
 await fs.writeFile(path.join(out,'report.json'),JSON.stringify({version:'0.6.2',lane:'Actual Electron; offline demo and update UI fixtures, no engine installation or benchmark',records,setup:setup.result.value},null,2));console.log(`${records.length} actual Electron captures saved to ${out}`);
}finally{socket?.close();child.kill('SIGTERM');await Promise.race([new Promise(r=>child.once('exit',r)),delay(1500)]);if(child.exitCode===null){child.kill('SIGKILL');await new Promise(r=>child.once('exit',r));}await fs.rm(profile,{recursive:true,force:true});}
