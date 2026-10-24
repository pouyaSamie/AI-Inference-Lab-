import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { DataRows } from "./DataRows";
import { Modal, StatusBadge, Tabs } from "./ui";
import { RangeChart, ScatterChart } from "./Charts";

const cleanups: (() => void)[] = [];
afterEach(() => { cleanups.splice(0).forEach(fn => fn()); });
async function render(children: React.ReactNode) {
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(children));
  cleanups.push(() => { act(() => root.unmount()); container.remove(); });
  return container;
}
it("does not label incomplete, unvalidated or simulated outcomes as successful", async () => {
  const el = await render(<><StatusBadge value="incomplete" /><StatusBadge value="not_validated" /><StatusBadge value="simulated_completed" /><StatusBadge value="completed" /></>);
  expect([...el.querySelectorAll('.badge')].map(b => b.className)).toEqual(["badge badge-warn", "badge badge-danger", "badge badge-simulated", "badge badge-ok"]);
});
it("provides roving arrow, Home and End tab navigation with a labelled panel", async () => {
  function Views() { const [value, setValue] = useState("json"); return <Tabs tabs={[{ value:"json", label:"JSON" }, { value:"yaml", label:"YAML" }]} value={value} onChange={setValue}><p>{value} content</p></Tabs>; }
  const el = await render(<Views />);
  const first = el.querySelector<HTMLButtonElement>('[role="tab"]')!; first.focus();
  await act(async () => { first.dispatchEvent(new KeyboardEvent("keydown", {key:"ArrowLeft", bubbles:true})); });
  const selected = el.querySelector<HTMLButtonElement>('[aria-selected="true"]')!;
  expect(selected.textContent).toBe("YAML"); expect(document.activeElement).toBe(selected);
  expect(first.tabIndex).toBe(-1); expect(el.querySelector('[role="tabpanel"]')?.getAttribute('aria-labelledby')).toBe(selected.id);
  await act(async () => { selected.dispatchEvent(new KeyboardEvent("keydown", {key:"Home", bubbles:true})); });
  expect(el.querySelector('[role="tabpanel"]')?.textContent).toContain("json content");
});
it("isolates a dialog, traps links, refuses busy Escape and restores trigger focus", async () => {
  const closed = vi.fn();
  function Dialog() { const [open,setOpen] = useState(false); return <><button onClick={() => setOpen(true)}>Open</button>{open ? <Modal title="Evidence" onClose={() => {closed();setOpen(false);}}><a href="#reference">Reference</a><button onClick={() => setOpen(false)}>Close</button></Modal> : null}</>; }
  const el = await render(<Dialog />); const trigger = el.querySelector<HTMLButtonElement>('button')!; trigger.focus();
  await act(async () => trigger.click());
  expect(trigger.inert).toBe(true);
  const dialog = el.querySelector<HTMLElement>('[role="dialog"]')!, link = el.querySelector<HTMLAnchorElement>('a')!;
  for(const node of [link,el.querySelectorAll('button')[1]!]) vi.spyOn(node,'getClientRects').mockReturnValue([{}] as unknown as DOMRectList);
  await act(async () => { dialog.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true})); });
  expect(document.activeElement).toBe(link);
  await act(async () => { document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true})); });
  expect(closed).toHaveBeenCalledOnce(); expect(trigger.inert).toBe(false); expect(document.activeElement).toBe(trigger);
});
it("keeps 5000 evidence records reachable while mounting at most 50 table rows", async () => {
  const items = Array.from({length:5000},(_,i)=>i);
  const el = await render(<table><DataRows items={items} columns={1} label="trials">{n=><tr key={n}><td>Trial {n}</td></tr>}</DataRows></table>);
  expect(el.querySelectorAll('tbody tr')).toHaveLength(50); expect(el.textContent).toContain('1–50 of 5000');
  await act(async () => { [...el.querySelectorAll('button')].find(b=>b.textContent==='Next')!.click(); });
  expect(el.querySelector('tbody')?.textContent).toContain('Trial 50'); expect(el.textContent).toContain('51–100 of 5000');
});
it("bounds plots and supplies tabular alternatives without hiding the coverage limit", async () => {
  const points = Array.from({length:5000},(_,i)=>({label:`Trial ${i}`,value:1.1,x:10+i,y:20+i,simulated:true}));
  const el = await render(<><RangeChart points={points}/><ScatterChart points={points} xLabel="Prefill tok/s" yLabel="Decode tok/s"/></>);
  expect(el.textContent).toContain('40 of 5000 paired scores'); expect(el.textContent).toContain('200 of 5000 matching observations');
  expect(el.querySelectorAll('svg circle, svg rect').length).toBe(240);
  expect(el.querySelectorAll('details table')).toHaveLength(2);
});
it("keeps a busy dialog open when Escape is pressed", async () => {
  const close = vi.fn(); await render(<Modal title="Saving evidence" busy onClose={close}><button disabled>Saving</button></Modal>);
  await act(async () => { document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true})); });
  expect(close).not.toHaveBeenCalled();
});
