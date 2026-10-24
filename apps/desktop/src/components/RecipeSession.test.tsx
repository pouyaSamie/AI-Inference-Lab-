import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { createLabApi } from "../lib/api";
import type { Schemas } from "../lib/contracts";
import { DEMO_RECIPE } from "../lib/mock";
import { RecipeSession } from "./RecipeSession";

const session: Schemas["ServingSession"] = { session_id: "serve-test", recipe_id: DEMO_RECIPE.recipe_id,
  state: "ready", port: 18765, context_tokens: 4096, started_at: DEMO_RECIPE.created_at, message: "Engine ready.",
  bytes_done: 10, bytes_total: 10, files_done: 1, files_total: 1 };

it("shows the ready local endpoint and stops the current session explicitly", async () => {
  window.history.replaceState({}, "", "/?demo=1");
  const api = createLabApi();
  Object.defineProperty(api, "demo", { value: false });
  vi.spyOn(api, "serving").mockResolvedValue(session);
  const stop = vi.spyOn(api, "stopRecipe").mockResolvedValue({ command_id: "stop-test", worker_id: "worker-test",
    command_type: "STOP_RECIPE", status: "completed", attempts: 1, lease_generation: 1, created_at: DEMO_RECIPE.created_at,
    result: { command_type: "STOP_RECIPE", session_id: session.session_id, stopped: true } });
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(<RecipeSession api={api} view={DEMO_RECIPE} workerId="worker-test" />));
    expect(container.querySelector("input")?.value).toBe("http://127.0.0.1:18765/v1");
    expect(container.textContent).toContain("Chat with this model");
    const buttons = [...container.querySelectorAll("button")];
    expect(buttons.find(b => b.textContent === "Run recipe")?.disabled).toBe(true);
    await act(async () => buttons.find(b => b.textContent === "Stop engine")!.click());
    expect(stop).toHaveBeenCalledWith("worker-test", session.session_id);
  } finally {
    await act(async () => root.unmount()); container.remove(); window.history.replaceState({}, "", "/");
  }
});

it("does not launch engines or poll a live worker in demo mode", async () => {
  window.history.replaceState({}, "", "/?demo=1");
  const api = createLabApi(); const run = vi.spyOn(api, "runRecipe"); const status = vi.spyOn(api, "serving");
  const container = document.createElement("div"); document.body.append(container); const root = createRoot(container);
  try {
    await act(async () => root.render(<RecipeSession api={api} view={DEMO_RECIPE} workerId="worker-test" />));
    const button = [...container.querySelectorAll("button")].find(b => b.textContent === "Run recipe")!;
    expect(button.disabled).toBe(true); button.click();
    expect(run).not.toHaveBeenCalled(); expect(status).not.toHaveBeenCalled();
  } finally {
    await act(async () => root.unmount()); container.remove(); window.history.replaceState({}, "", "/");
  }
});
