import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LocalRuntimePanel } from "./LocalRuntime";
import type { DesktopBridge, LocalRuntimeStatus } from "../lib/bridge";

const base: LocalRuntimeStatus = { managed: true, state: "needs_configuration", message: "Found 10 models. Choose an engine build.", config: { model_roots: ["/models"] }, secure_storage: false, inventory: { models: 10, engines: 0, gpus: 1, verified_models: 0, warnings: [] } };

describe("local lab setup wizard", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => { delete window.labDesktop; localStorage.clear(); });
  it("starts with two folder choices and keeps individual paths under Advanced", async () => {
    const select = vi.fn(async () => base);
    window.labDesktop = { runtime: { status: async () => base, select, retry: async () => base } } as unknown as DesktopBridge;
    const container = document.createElement("div");
    const root = createRoot(container);
    try {
      await act(async () => { root.render(<LocalRuntimePanel />); });
      expect(container.textContent).toContain("no API setup is needed");
      expect(container.textContent).toContain("10 models discovered");
      expect(container.querySelector("details.setup-advanced")?.hasAttribute("open")).toBe(false);
      const button = [...container.querySelectorAll("button")].find((b) => b.textContent === "Add inference folder")!;
      await act(async () => { button.click(); });
      expect(select).toHaveBeenCalledWith("engine_roots");
      expect(container.querySelector("input")).toBeNull();
    } finally { await act(async () => root.unmount()); }
  });
  it("saves wizard progress and allows editing completed setup without clearing paths", async () => {
    window.labDesktop = { runtime: { status: async () => base } } as unknown as DesktopBridge;
    const container = document.createElement("div");
    let root = createRoot(container);
    const click = async (label: string) => { await act(async () => { [...container.querySelectorAll("button")].find((b) => b.textContent === label)!.click(); }); };
    try {
      await act(async () => { root.render(<LocalRuntimePanel />); });
      await click("Continue");
      expect(localStorage.getItem("lab.setup.step")).toBe("1");
      await act(async () => root.unmount());
      root = createRoot(container);
      await act(async () => { root.render(<LocalRuntimePanel />); });
      expect(container.textContent).toContain("Step 2 of 3");
      await click("Continue"); await click("Save setup");
      expect(localStorage.getItem("lab.setup.complete")).toBe("1");
      expect(container.textContent).toContain("/models");
      await click("Edit setup");
      expect(container.textContent).toContain("Review your setup");
      expect(container.textContent).toContain("/models");
    } finally { await act(async () => root.unmount()); }
  });
  it("chooses a discovered build by ID, never by a renderer-supplied path", async () => {
    localStorage.setItem("lab.setup.step", "1");
    const value = { ...base, engine_candidates: [{ id: "a".repeat(24), engine_id: "llamacpp" as const, label: "llama.cpp · current", paths: { llama_server_path: "/engines/bin/llama-server" }, missing: [] }] };
    const useEngine = vi.fn(async () => value);
    window.labDesktop = { runtime: { status: async () => value, useEngine } } as unknown as DesktopBridge;
    const container = document.createElement("div"); const root = createRoot(container);
    try {
      await act(async () => root.render(<LocalRuntimePanel />));
      await act(async () => { [...container.querySelectorAll("button")].find((b) => b.textContent === "Use this build")!.click(); });
      expect(useEngine).toHaveBeenCalledWith("a".repeat(24));
    } finally { await act(async () => root.unmount()); }
  });
  it("keeps folder actions disabled during discovery", async () => {
    const value = { ...base, state: "starting" as const, message: "Reading model metadata" };
    window.labDesktop = { runtime: { status: async () => value } } as unknown as DesktopBridge;
    const container = document.createElement("div"); const root = createRoot(container);
    try {
      await act(async () => root.render(<LocalRuntimePanel />));
      const button = [...container.querySelectorAll("button")].find((b) => b.textContent === "Add model folder")!;
      expect(button.disabled).toBe(true);
      expect(container.textContent).toContain("Reading model metadata");
    } finally { await act(async () => root.unmount()); }
  });
});
