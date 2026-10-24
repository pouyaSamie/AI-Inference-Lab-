// Linux Electron visual evidence in a disposable, unmanaged profile. No engines or services start.
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
 await cmd('Page.bringToFront');await cmd('Emulation.setFocusEmulationEnabled',{enabled:true});
 const checks=[];
 const key=async(key,code,modifiers=0)=>{const windowsVirtualKeyCode={Enter:13,Tab:9,Escape:27,End:35,Home:36}[key];await cmd('Input.dispatchKeyEvent',{type:'keyDown',key,code,modifiers,windowsVirtualKeyCode,nativeVirtualKeyCode:windowsVirtualKeyCode,...(key==='Enter'?{text:'\r',unmodifiedText:'\r'}:{})});await cmd('Input.dispatchKeyEvent',{type:'keyUp',key,code,modifiers,windowsVirtualKeyCode,nativeVirtualKeyCode:windowsVirtualKeyCode});await delay(60);};
 const assert=async(name,expression)=>{if(!await evaluate(expression))throw Error(name);checks.push(name);};
 await evaluate("localStorage.setItem('lab.theme','light');location.href='lab://app/index.html?demo=1#/live'");await delay(200);await cmd('Page.reload');await delay(700);
 await evaluate("document.querySelector('[aria-label=\"Dark appearance\"]').focus()");await key('Enter','Enter');
 
 await assert('Appearance icon supports keyboard activation and persistence',"document.documentElement.dataset.theme==='dark'&&localStorage.getItem('lab.theme')==='dark'");
 await evaluate("const select=document.querySelector('.page-header select');select.value='exp-demo-running';select.dispatchEvent(new Event('change',{bubbles:true}))");await delay(500);
 await evaluate("const cancel=[...document.querySelectorAll('.run-actions button')].find(b=>b.textContent==='Cancel');cancel.focus();cancel.click()");
 await assert('Dialog isolates sidebar',"document.querySelector('[role=dialog]')&&document.querySelector('.sidebar').inert");
 await key('Tab','Tab');await assert('Tab enters dialog form',"document.activeElement.tagName==='TEXTAREA'");
 await key('Tab','Tab',8);await assert('Shift Tab wraps within dialog',"document.activeElement.textContent==='Cancel test'");
 await key('Escape','Escape');await assert('Escape dismisses and restores focus',"!document.querySelector('[role=dialog]')&&document.activeElement.textContent==='Cancel'&&!document.querySelector('.sidebar').inert");
 await evaluate("document.querySelector('[aria-label=\"Primary\"] button[aria-current]').focus()");
 await evaluate("location.hash='#/recipes'");await delay(600);
 await evaluate("document.querySelector('[role=tab]').focus()");await key('End','End');
 await assert('Recipe tabs expose active panel with End key',"document.activeElement.textContent==='systemd'&&document.querySelector('[role=tabpanel]').getAttribute('aria-labelledby')===document.activeElement.id");
 await key('Home','Home');await assert('Recipe tabs restore JSON with Home key',"document.activeElement.textContent==='JSON'");
 await fs.writeFile(path.join(out,'keyboard-report.json'),JSON.stringify({platform:process.platform,source:'Actual Electron CDP keyboard input; explicit demo fixtures, no mutation sent to a controller',checks},null,2));
 console.log(JSON.stringify(checks));
}finally{socket?.close();child.kill('SIGTERM');await delay(1000);if(child.exitCode===null)child.kill('SIGKILL');}
