import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";
import { usePolling } from "./hooks";

it("never carries fixture data into a disconnected real source", async () => {
  const element=document.createElement('div');document.body.append(element);const root=createRoot(element);
  function Probe({source}:{source:string}) { const poll=usePolling(async()=>{if(source==='real')throw Error('Offline');return 'Fixture throughput';},60_000,true,source);return <div>{poll.data??'No data'} {poll.error?'Disconnected':''}</div>; }
  try {
    await act(async()=>root.render(<Probe source="demo"/>));expect(element.textContent).toContain('Fixture throughput');
    await act(async()=>root.render(<Probe source="real"/>));expect(element.textContent).toContain('Disconnected');expect(element.textContent).not.toContain('Fixture throughput');
  } finally {await act(async()=>root.unmount());element.remove();}
});
it("refreshes all mounted page queries from the shared header event", async () => {
  const element=document.createElement('div');document.body.append(element);const root=createRoot(element);
  let workers=0,recipes=0;
  function Probe() {const a=usePolling(async()=>++workers,60_000), b=usePolling(async()=>++recipes,60_000);return <div>{a.data}/{b.data}</div>;}
  try {
    await act(async()=>root.render(<Probe/>));expect(element.textContent).toBe('1/1');
    await act(async()=>{window.dispatchEvent(new Event('lab:refresh-page'));});expect(element.textContent).toBe('2/2');
  } finally {await act(async()=>root.unmount());element.remove();}
});
