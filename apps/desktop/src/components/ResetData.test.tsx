import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { ResetDataPanel } from "./ResetData";
import type { DesktopBridge, LocalRuntimeStatus } from "../lib/bridge";
import type { SystemStatusResponse } from "../lib/contracts";

it('requires an idle managed lab, does not reset on render, and presents native cancellation honestly',async()=>{
  const reset=vi.fn(async()=>({canceled:true}));window.labDesktop={runtime:{resetData:reset}} as unknown as DesktopBridge;
  const runtime={managed:true,state:'ready'} as LocalRuntimeStatus;
  const container=document.createElement('div');document.body.append(container);const root=createRoot(container);
  const render=async(demo:boolean,active:number)=>{await act(async()=>root.render(<ResetDataPanel demo={demo} runtime={runtime} status={{experiments_active:active,serving_active:0} as SystemStatusResponse}/>));};
  try{
    await render(false,1);expect(container.querySelector('button')?.disabled).toBe(true);expect(reset).not.toHaveBeenCalled();
    await render(true,0);expect(container.querySelector('button')?.disabled).toBe(true);
    await render(false,0);expect(container.querySelector('button')?.disabled).toBe(false);expect(reset).not.toHaveBeenCalled();
    await act(async()=>container.querySelector('button')!.click());expect(reset).toHaveBeenCalledOnce();expect(container.textContent).toContain('No data was changed');
  }finally{await act(async()=>root.unmount());container.remove();delete window.labDesktop;}
});
