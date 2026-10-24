import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createLabApi } from "../lib/api";
import { OptimizePage } from "./OptimizePage";
import type { PageProps } from "./types";
import type { CommandStatusView } from "../lib/contracts";

afterEach(() => { vi.useRealTimers(); window.history.replaceState({}, "", "/"); });
async function scenario(failed = false) {
  vi.useFakeTimers(); window.history.replaceState({}, "", "/?demo=1");
  const api = createLabApi(); const original = api.plan.bind(api);
  const plan = vi.spyOn(api, "plan").mockImplementationOnce(async () => ({ status: "preflight_required", reason: "Checking the selected model files", command_id: "cmd-test", retry_after_ms: 1000 })).mockImplementation(original);
  vi.spyOn(api, "workerCommands").mockResolvedValue([{ command_id: "cmd-test", status: failed ? "failed" : "completed", failure: failed ? { message: "Model file is not readable" } : null } as CommandStatusView]);
  const create = vi.spyOn(api, "createExperiment");
  const container = document.createElement("div"); document.body.append(container); const root = createRoot(container);
  await act(async () => root.render(<OptimizePage {...({ api, navigate: vi.fn(), refreshShell: vi.fn() } as unknown as PageProps)} />));
  const click = async (text: string) => { await act(async () => { [...container.querySelectorAll("button")].find(button => button.textContent === text)!.click(); }); };
  for (let step = 0; step < 4; step++) await click("Continue");
  return { api, plan, create, container, click, close: async () => { await act(async () => root.unmount()); container.remove(); } };
}
describe("automatic test readiness", () => {
  it("waits for verification then enables submission without repeated plan-check clicks", async () => {
    const view = await scenario();
    try {
      expect(view.plan).toHaveBeenCalledTimes(1);
      expect(view.container.textContent).toContain("Checking model files");
      expect(view.create).not.toHaveBeenCalled();
      await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
      expect(view.plan).toHaveBeenCalledTimes(2);
      expect(view.container.textContent).toContain("Plan ready to submit");
      await view.click("Review and start test");
      expect(view.container.textContent).toContain("Step 6 of 6");
      expect(view.create).not.toHaveBeenCalled(); // Submission still needs explicit confirmation.
    } finally { await view.close(); }
  });
  it("shows a concrete failed-verification reason and stops polling", async () => {
    const view = await scenario(true);
    try {
      await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
      expect(view.container.textContent).toContain("Model file is not readable");
      expect(view.container.textContent).toContain("Needs attention");
      await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
      expect(view.plan).toHaveBeenCalledTimes(1);
      expect(view.create).not.toHaveBeenCalled();
    } finally { await view.close(); }
  });
});

it("offers the small setup preset without relaxing evidence constraints", async () => {
  const view = await scenario();
  try {
    await act(async () => { [...view.container.querySelectorAll("button")].find(b => b.textContent?.replace(/\s/g, "") === "4Search")!.click(); });
    await view.click("Small setup test");
    const values = [...view.container.querySelectorAll<HTMLInputElement>('input[type="number"]')].map(input => input.value);
    expect(values.slice(0, 4)).toEqual(["1", "1", "1", "2"]);
    expect([...view.container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')].every(input => input.checked)).toBe(true);
    expect(view.container.textContent).toContain("does not guarantee a validated recipe");
  } finally { await view.close(); }
});

it("exposes the stale command identity and never offers submit before a ready response", async () => {
  const view = await scenario(true);
  try {
    expect(view.container.textContent).toContain("cmd-test");
    expect(view.container.textContent).toContain("submission blocked");
    expect(view.container.textContent).not.toContain("Create experiment");
    expect(view.create).not.toHaveBeenCalled();
  } finally { await view.close(); }
});
