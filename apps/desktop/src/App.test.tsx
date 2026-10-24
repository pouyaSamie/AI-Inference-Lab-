import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { DesktopBridge } from "./lib/bridge";
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
    delete window.labDesktop;
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

  it("persists an explicit theme and provides keyboard workspace access", async () => {
    const root = createRoot(container!);
    await act(async () => root.render(<App />));
    const appearance = container!.querySelector<HTMLButtonElement>('[aria-label="Dark appearance"]')!;
    await act(async () => appearance.click());
    expect(appearance.getAttribute("aria-checked")).toBe("true");
    expect(container!.querySelector('.topbar [aria-label="Appearance"]')).toBeNull();
    expect(container!.querySelector('.sidebar-foot [aria-label="Dark appearance"]')).toBeNull();
    expect(container!.querySelector('.topbar [aria-label="Dark appearance"]')).not.toBeNull();
    expect(container!.querySelector('[aria-label="Refresh page data"] svg')).not.toBeNull();
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("lab.theme")).toBe("dark");
    await act(async () => appearance.click());
    expect(appearance.getAttribute("aria-checked")).toBe("false");
    expect(localStorage.getItem("lab.theme")).toBe("light");
    expect(container!.querySelector('.skip-link')?.getAttribute("href")).toBe("#main-content");
    expect(container!.textContent).toContain("Fixture data");
    await act(async () => root.unmount());
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
      "Help & guide",
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
    expect(container!.textContent).toContain("Engine downloads require explicit confirmation");
    expect(container!.querySelector('[aria-label="Engine updates"]')).toBeNull();
    await act(async () => root.unmount());
  });

  it("keeps help accessible when local services fail and links to setup", async () => {
    window.history.replaceState({}, "", "/#/help");
    window.labDesktop = { runtime: { status: async () => ({
      managed: true, state: "error", message: "Local service failed", config: { model_roots: [] }, secure_storage: false
    }) } } as unknown as DesktopBridge;
    const root = createRoot(container!);
    try {
      await act(async () => root.render(<App />));
      await flush(80);
      expect(container!.querySelector("h1")?.textContent).toBe("Help & guide");
      expect(container!.textContent).toContain("No validated winner does not by itself mean the test broke");
      const setup = [...container!.querySelectorAll("button")].find(button => button.textContent === "Open Settings to begin");
      await act(async () => setup!.click());
      expect(window.location.hash).toBe("#/settings");
      expect(container!.querySelector("h1")?.textContent).not.toBe("Help & guide");
    } finally { await act(async () => root.unmount()); delete window.labDesktop; }
  });

  it("searches help, opens matches, and recovers from an empty search result", async () => {
    window.history.replaceState({}, "", "/?demo=1#/help");
    const root = createRoot(container!);
    try {
      await act(async () => root.render(<App />));
      const search = container!.querySelector<HTMLInputElement>('input[type="search"]')!;
      const enter = async (text: string) => act(async () => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(search, text);
        search.dispatchEvent(new Event("input", { bubbles: true }));
      });
      await enter("no validated winner");
      expect(container!.querySelectorAll(".help-topic")).toHaveLength(1);
      expect(container!.querySelector(".help-topic")?.hasAttribute("open")).toBe(true);
      await enter("unmatched-search-term");
      expect(container!.textContent).toContain("No matching help yet");
      await act(async () => [...container!.querySelectorAll("button")].find(button => button.textContent === "Clear search")!.click());
      expect(container!.querySelectorAll(".help-topic")).toHaveLength(9);
    } finally { await act(async () => root.unmount()); }
  });
});
