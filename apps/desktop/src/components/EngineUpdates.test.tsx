import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DesktopBridge, EngineUpdateStatus } from "../lib/bridge";
import { EngineUpdatesPanel, StartupUpdateSuggestion } from "./EngineUpdates";

const status: EngineUpdateStatus = { enabled: true, checking: false, checked_at: "2026-10-21T00:00:00Z", error: null, operation: null, releases: [{ engine_id: "llamacpp", version: "0.7.0", tag: "v0.7.0", published: "", preview: false, installed_version: "0.6.0", update: "available", assets: [{ id: 123, name: "llama-linux-cuda-x64.tar.gz", size: 1024, digest: "sha256:" + "a".repeat(64) }], page: "https://github.com/ggml-org/llama.cpp/releases/tag/v0.7.0" }] };
afterEach(() => { delete window.labDesktop; });
async function render(element: React.ReactNode) {
  const container = document.createElement("div"); const root = createRoot(container);
  await act(async () => root.render(element));
  return { container, close: () => act(async () => root.unmount()) };
}
describe("engine update experience", () => {
  it("shows an update suggestion at startup and dismisses it for this session", async () => {
    window.labDesktop = { engineUpdates: { status: async () => status } } as unknown as DesktopBridge;
    const view = await render(<StartupUpdateSuggestion />);
    try {
      expect(view.container.querySelector('[role="dialog"]')?.textContent).toContain("Engine updates available");
      await act(async () => { [...view.container.querySelectorAll("button")].find(b => b.textContent === "Later")!.click(); });
      expect(view.container.querySelector('[role="dialog"]')).toBeNull();
    } finally { await view.close(); }
  });
  it("preselects a hardware match and offers one recommended install action", async () => {
    const recommended = { ...status, releases: status.releases.map(release => ({ ...release, recommendation: { asset_id: 123, label: "NVIDIA GPU acceleration", hardware: "Detected GPU · driver 595", reason: "Matches your detected hardware" } })) };
    const install = vi.fn(async () => ({ canceled: true }));
    window.labDesktop = { engineUpdates: { status: async () => recommended, install } } as unknown as DesktopBridge;
    const view = await render(<EngineUpdatesPanel />);
    try {
      const button = [...view.container.querySelectorAll("button")].find(b => b.textContent === "Install recommended update…")!;
      expect(button.disabled).toBe(false);
      expect(view.container.textContent).toContain("Recommended for your hardware");
      expect(view.container.textContent).toContain("Selected build: llama-linux-cuda-x64.tar.gz");
      expect(view.container.querySelector("details")?.open).toBe(false);
      await act(async () => button.click());
      expect(install).toHaveBeenCalledWith("llamacpp", 123);
    } finally { await view.close(); }
  });
  it("keeps startup quiet when checks are disabled or installed version is current", async () => {
    for (const value of [{ ...status, enabled: false }, { ...status, releases: status.releases.map(r => ({ ...r, update: "current" as const })) }]) {
      window.labDesktop = { engineUpdates: { status: async () => value } } as unknown as DesktopBridge;
      const view = await render(<StartupUpdateSuggestion />);
      expect(view.container.querySelector('[role="dialog"]')).toBeNull(); await view.close();
    }
  });
  it("requires an advanced choice when hardware cannot be matched and sends only the release asset ID for native confirmation", async () => {
    const install = vi.fn(async () => ({ canceled: true }));
    const setEnabled = vi.fn(async () => ({ ...status, enabled: false }));
    window.labDesktop = { engineUpdates: { status: async () => status, install, setEnabled } } as unknown as DesktopBridge;
    const view = await render(<EngineUpdatesPanel />);
    try {
      const button = [...view.container.querySelectorAll("button")].find(b => b.textContent === "Install custom build…")!;
      expect(button.disabled).toBe(true);
      const select = view.container.querySelector("select")!;
      await act(async () => { select.value = "123"; select.dispatchEvent(new Event("change", { bubbles: true })); });
      await act(async () => button.click());
      expect(install).toHaveBeenCalledWith("llamacpp", 123);
      await act(async () => view.container.querySelector("input")!.click());
      expect(setEnabled).toHaveBeenCalledWith(false);
    } finally { await view.close(); }
  });
});

it("closes with Escape after expanding updates replaces the focused review button", async () => {
  window.labDesktop = { engineUpdates: { status: async () => status } } as unknown as DesktopBridge;
  const view = await render(<StartupUpdateSuggestion />); document.body.append(view.container);
  try {
    await act(async () => { [...view.container.querySelectorAll("button")].find(b => b.textContent === "Review updates")!.click(); });
    await act(async () => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
    expect(view.container.querySelector('[role="dialog"]')).toBeNull();
    expect(document.body.style.overflow).not.toBe("hidden");
  } finally { await view.close(); view.container.remove(); }
});


it("separates engine families and shows observed download progress", async () => {
  const value: EngineUpdateStatus = { ...status, operation: "Downloading archive", installation: { engine_id: "llamacpp", asset_id: 123, version: "0.7.0", phase: "downloading", bytes_done: 512, bytes_total: 1024 }, releases: [...status.releases, { ...status.releases[0]!, engine_id: "strata", version: "0.1.48" }] };
  window.labDesktop = { engineUpdates: { status: async () => value } } as unknown as DesktopBridge;
  const view = await render(<EngineUpdatesPanel />);
  try {
    expect(view.container.textContent).toContain("50% downloaded");
    expect(view.container.querySelector("progress")?.value).toBe(512);
    expect(view.container.querySelectorAll(".engine-release")).toHaveLength(1);
    expect(view.container.querySelector(".engine-release")?.textContent).toContain("llama.cpp");
    await act(async () => { [...view.container.querySelectorAll("button")].find(b => b.textContent === "Strata")!.click(); });
    expect(view.container.querySelector(".engine-release")?.textContent).toContain("Strata 0.1.48");
  } finally { await view.close(); }
});

it("shows verified installation completion and selects only the matching discovered build", async () => {
  const useEngine = vi.fn(async () => ({}));
  const value = { ...status, installation: { engine_id: "llamacpp", asset_id: 123, version: "0.7.0", phase: "complete", bytes_done: 1024, bytes_total: 1024 } };
  window.labDesktop = { engineUpdates: { status: async () => value }, runtime: { status: async () => ({ state: "ready", config: {}, engine_candidates: [{ engine_id: "llamacpp", id: "matching", paths: { llama_server_path: "/lab/llamacpp-123/engine/bin/llama-server" } }] }), useEngine } } as unknown as DesktopBridge;
  const view = await render(<EngineUpdatesPanel />);
  try {
    expect(view.container.textContent).toContain("llama.cpp 0.7.0 installed");
    expect(view.container.textContent).toContain("Installed · select to use");
    expect([...view.container.querySelectorAll("button")].find(b => b.textContent === "Build installed")?.disabled).toBe(true);
    await act(async () => { [...view.container.querySelectorAll("button")].find(b => b.textContent === "Use this engine")!.click(); });
    expect(useEngine).toHaveBeenCalledWith("matching");
  } finally { await view.close(); }
});
