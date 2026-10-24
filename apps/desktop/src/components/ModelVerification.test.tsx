import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { ModelVerificationProgress } from "./ModelVerification";
import type { DesktopBridge } from "../lib/bridge";

it("explains stalled verification without claiming failure and shows safe recovery errors", async () => {
  const retry = vi.fn(async () => { throw Error("Finish active jobs before rescanning"); });
  window.labDesktop = { runtime: { retry } } as unknown as DesktopBridge;
  const container = document.createElement("div"), root = createRoot(container);
  try {
    await act(async () => root.render(<ModelVerificationProgress value={{ state: "verifying", updated_at: Date.now() / 1000 - 130, bytes_done: 10, bytes_total: 100, files_done: 0, files_total: 1 }} />));
    expect(container.textContent).toContain("does not prove failure");
    expect(container.textContent).toContain("Check that every split file is present");
    await act(async () => { [...container.querySelectorAll("button")].find(b => b.textContent === "Rescan & retry verification")!.click(); });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("Finish active jobs");
  } finally { await act(async () => root.unmount()); delete window.labDesktop; }
});

it("does not show a completed progress bar when verification failed", async () => {
  const container = document.createElement("div"), root = createRoot(container);
  try {
    await act(async () => root.render(<ModelVerificationProgress value={{ state: "failed", bytes_done: 100, bytes_total: 100, files_done: 1, files_total: 1 }} />));
    expect(container.textContent).toContain("Some model files could not be verified");
    expect(container.querySelector("progress")).toBeNull();
  } finally { await act(async () => root.unmount()); }
});
