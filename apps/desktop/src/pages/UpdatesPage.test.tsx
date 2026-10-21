import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createMockApi } from "../lib/mock";
import { UpdatesPage } from "./UpdatesPage";
import type { PageProps } from "./types";

async function flush(ms = 40): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });
}

function findButton(container: HTMLElement, label: string): HTMLButtonElement | undefined {
  return [...container.querySelectorAll("button")].find(
    (button) => button.textContent?.trim() === label,
  );
}

function setTextarea(container: HTMLElement, value: string): void {
  const textarea = container.querySelector("textarea");
  expect(textarea).toBeTruthy();
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype,
    "value",
  )?.set;
  setter?.call(textarea, value);
  textarea!.dispatchEvent(new Event("input", { bubbles: true }));
}

const props = (): PageProps => ({
  api: createMockApi() as unknown as PageProps["api"],
  status: null,
  statusError: null,
  experiments: null,
  experimentsError: null,
  activeExperimentId: null,
  setActiveExperimentId: () => undefined,
  navigate: () => undefined,
  refreshShell: () => undefined,
});

describe("UpdatesPage", () => {
  let container: HTMLDivElement | null = null;

  beforeEach(() => {
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
  });

  it("shows impact, proposals, regression results and pinned decisions", async () => {
    const root = createRoot(container!);
    await act(async () => root.render(<UpdatesPage {...props()} />));
    await flush(120);

    expect(container!.textContent).toContain("0.7.1-demo");
    expect(container!.textContent).toContain("A/B required");
    expect(container!.textContent).toContain("Keep the current engine");
    expect(container!.textContent).toContain("never installs automatically");

    const create = findButton(container!, "Create A/B proposal");
    expect(create).toBeTruthy();
    await act(async () => create?.click());
    await flush(80);
    expect(container!.textContent).toContain("Awaiting paired measured evidence");

    const pin = findButton(container!, "Pin current build");
    expect(pin).toBeTruthy();
    await act(async () => pin?.click());
    await flush(80);
    expect(container!.textContent).toContain("Pinned");

    await act(async () => root.unmount());
  });

  it("imports offline metadata and never claims an install", async () => {
    const root = createRoot(container!);
    await act(async () => root.render(<UpdatesPage {...props()} />));
    await flush(120);

    const release = {
      engine_id: "llamacpp",
      version: "0.7.9-demo",
      build: "799-demo",
      backend: "cuda",
      executable_id: "llama-server",
      artifact_sha256: "d".repeat(64),
      released_at: "2026-10-21T00:00:00Z",
      source: "offline_import",
      changed_paths: ["ggml/src/ggml-cuda/mmq.cu"],
      changelog: "Offline test metadata.",
    };
    await act(async () => setTextarea(container!, JSON.stringify(release)));
    const importButton = findButton(container!, "Import offline metadata");
    expect(importButton).toBeTruthy();
    await act(async () => importButton?.click());
    await flush(120);

    expect(container!.textContent).toContain("Release metadata imported");
    expect(container!.textContent).toContain("0.7.9-demo");
    expect(container!.textContent).toContain("No upstream request or download occurred");
    expect(container!.textContent).not.toContain("installed successfully");

    await act(async () => root.unmount());
  });
});
