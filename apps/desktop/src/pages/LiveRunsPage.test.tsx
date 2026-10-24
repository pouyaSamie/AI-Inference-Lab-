import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createLabApi } from "../lib/api";
import { LiveRunsPage } from "./LiveRunsPage";
import type { PageProps } from "./types";

afterEach(() => { vi.useRealTimers(); window.history.replaceState({}, "", "/"); });
async function setup(state = "running", failedTrials = false, unavailable = false) {
  window.history.replaceState({}, "", "/?demo=1");
  const api = createLabApi();
  const experiments = await api.experiments();
  const id = experiments.experiments[0]!.experiment_id;
  const original = await api.experiment(id);
  vi.spyOn(api, "experiment").mockResolvedValue({ ...original, observations: unavailable ? (original.observations ?? []).map(item => ({ ...item, measurement_status: "unavailable" as const, failure: null })) : failedTrials ? (original.observations ?? []).map(item => ({ ...item, measurement_status: "invalid" as const, failure: { kind: "EXTERNAL_GPU_CONTENTION" as const, stage: "unknown" as const, message: "EXTERNAL_GPU_COMPUTE:foreign --private-secret=do-not-render", retryable: false } })) : original.observations, status: { ...original.status, state: state as typeof original.status.state, stage: "preflight", error_code: state === "blocked" ? "PREFLIGHT_EXECUTION_FAILED" : null, error_message: state === "blocked" ? "The selected engine could not start safely." : null } });
  const cancel = vi.spyOn(api, "cancel").mockResolvedValue(original);
  const retry = vi.spyOn(api, "retryPreflight").mockResolvedValue(original);
  const prompt = vi.spyOn(window, "prompt").mockImplementation(() => { throw Error("prompt unsupported"); });
  const container = document.createElement("div"); document.body.append(container); const root = createRoot(container);
  await act(async () => { root.render(<LiveRunsPage {...({ api, experiments, activeExperimentId: id, setActiveExperimentId: vi.fn(), navigate: vi.fn(), refreshShell: vi.fn() } as unknown as PageProps)} />); });
  const click = async (text: string) => { await act(async () => { [...container.querySelectorAll("button")].find(b => b.textContent === text)!.click(); }); };
  return { api, container, id, cancel, retry, prompt, click, close: async () => { await act(async () => root.unmount()); container.remove(); prompt.mockRestore(); } };
}
describe("run recovery", () => {
  it("inspects a selected immutable trial with units and explicit evidence status", async () => {
    const view = await setup();
    try {
      const inspector = () => view.container.querySelector('[aria-label="Selected trial inspector"]')!;
      expect(inspector().textContent).toContain("Trial 0");
      await view.click("Trial 1");
      expect(inspector().textContent).toContain("Trial 1");
      expect(inspector().textContent).toContain("cand-demo-1");
      expect(inspector().textContent).toContain("tok/s");
      expect(inspector().textContent).toContain("Simulated fixture evidence");
    } finally { await view.close(); }
  });
  it("does not present finished invalid trials as a successful benchmark or expose process arguments", async () => {
    const view = await setup("completed", true);
    try {
      expect(view.container.textContent).toContain("Finished without valid measurements");
      expect(view.container.textContent).toContain("No performance measurement was taken");
      expect(view.container.textContent).toContain("EXTERNAL_GPU_CONTENTION");
      expect(view.container.textContent).not.toContain("--private-secret");
    } finally { await view.close(); }
  });
  it("explains finished observations with unavailable metrics", async () => {
    const view = await setup("completed", false, true);
    try {
      expect(view.container.textContent).toContain("Finished without valid measurements");
      expect(view.container.textContent).toContain("measurements unavailable");
      expect(view.container.textContent).toContain("cannot qualify a recipe");
    } finally { await view.close(); }
  });
  it("uses a supported cancellation dialog, keeps work running on dismissal, and submits an optional reason", async () => {
    const view = await setup();
    try {
      await view.click("Cancel");
      expect(view.container.querySelector('[role="dialog"]')?.textContent).toContain("Reason (optional)");
      await view.click("Keep running"); expect(view.cancel).not.toHaveBeenCalled();
      await view.click("Cancel");
      await act(async () => { view.container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
      expect(view.cancel).toHaveBeenCalledWith(view.id, "operator cancelled from desktop UI");
      expect(view.prompt).not.toHaveBeenCalled();
      expect(view.container.querySelector('[role="dialog"]')).toBeNull();
    } finally { await view.close(); }
  });
  it("shows preflight failure and enables the controller's blocked-state retry", async () => {
    const view = await setup("blocked");
    try {
      expect(view.container.textContent).toContain("The selected engine could not start safely.");
      await view.click("Retry preflight"); expect(view.retry).toHaveBeenCalledWith(view.id);
    } finally { await view.close(); }
  });
  it("retains the dialog and explains a failed cancellation request", async () => {
    const view = await setup();
    try {
      view.cancel.mockRejectedValueOnce(Error("Worker temporarily unavailable"));
      await view.click("Cancel");
      await act(async () => { view.container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
      expect(view.container.querySelector('[role="dialog"]')?.textContent).toContain("Worker temporarily unavailable");
    } finally { await view.close(); }
  });
});

it("does not call disconnected history empty or infer a failed run", async () => {
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(<LiveRunsPage {...({ api: createLabApi(), experiments: null, experimentsError: Error("Controller unreachable"), activeExperimentId: null, setActiveExperimentId: vi.fn(), navigate: vi.fn(), refreshShell: vi.fn() } as unknown as PageProps)} />));
  expect(container.textContent).toContain("Run history unavailable");
  expect(container.textContent).not.toContain("No experiments");
  expect(container.textContent).toContain("does not indicate that any run failed");
  await act(async () => root.unmount()); container.remove();
});

it("retains last known run state on disconnect and disables stale mutations", async () => {
  vi.useFakeTimers(); const view = await setup();
  try {
    vi.mocked(view.api.experiment).mockRejectedValueOnce(Error("Connection lost"));
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    expect(view.container.textContent).toContain("Last known run state");
    expect(view.container.textContent).toContain("does not indicate a failed or stopped run");
    const cancel = [...view.container.querySelectorAll('button')].find(b=>b.textContent==='Cancel')!;
    expect(cancel.disabled).toBe(true); expect(view.cancel).not.toHaveBeenCalled();
  } finally { await view.close(); }
});
it("collapses the inspector and reopens it when an immutable trial is selected", async () => {
  const view = await setup();
  try {
    await view.click("Hide inspector"); expect(view.container.querySelector('aside')).toBeNull();
    await view.click("Trial 1"); expect(view.container.querySelector('aside')?.textContent).toContain("Trial 1");
  } finally { await view.close(); }
});
