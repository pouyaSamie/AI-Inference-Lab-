import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { App } from "./App";

async function flush(ms = 30): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });
}

describe("desktop app shell", () => {
  let container: HTMLDivElement | null = null;

  beforeEach(() => {
    window.localStorage.clear();
    window.history.replaceState({}, "", "/?demo=1#/overview");
    container = document.createElement("div");
    document.body.append(container);
  });

  afterEach(() => {
    if (container) {
      act(() => {
        container?.remove();
      });
      container = null;
    }
    window.localStorage.clear();
    window.history.replaceState({}, "", "/");
  });

  it("renders every primary screen and labels offline demo data", async () => {
    const root = createRoot(container!);
    await act(async () => root.render(<App />));
    await flush(80);

    expect(container!.textContent).toContain("OFFLINE DEMO MODE");
    for (const label of [
      "Overview",
      "Models",
      "Engines",
      "Workers",
      "Optimize",
      "Live Runs",
      "Compare",
      "Recipes",
      "Updates",
      "Settings",
    ]) {
      expect(container!.textContent).toContain(label);
    }

    const compare = [...container!.querySelectorAll("button")].find(
      (button) => button.textContent?.trim().endsWith("Compare"),
    );
    expect(compare).toBeTruthy();
    await act(async () => compare?.click());
    await flush(120);

    expect(container!.textContent).toContain("SIMULATED — never a deployable winner");
    expect(container!.textContent).toContain("no qualified winner");
    expect(container!.textContent).toContain("Highest throughput alone is never a pass");
    await act(async () => root.unmount());
  });

  it("renders read-only release intelligence on Updates", async () => {
    window.history.replaceState({}, "", "/?demo=1#/updates");
    const root = createRoot(container!);
    await act(async () => root.render(<App />));
    await flush(120);
    expect(container!.textContent).toContain("Offline import only — no upstream egress");
    expect(container!.textContent).toContain("0.7.1-demo");
    expect(container!.textContent).toContain("Keep the current engine");
    expect(container!.textContent).toContain("Upgrade approval remains false");
    expect(container!.textContent).toContain("Never download, replace, or patch an engine or model");
    await act(async () => root.unmount());
  });
});
