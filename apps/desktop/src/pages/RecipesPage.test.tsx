import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { createLabApi } from "../lib/api";
import { DEMO_RECIPE } from "../lib/mock";
import type { Schemas } from "../lib/contracts";
import { RecipesPage } from "./RecipesPage";
import type { PageProps } from "./types";

it("ends the loading state after failure and recovers through Retry", async () => {
  window.history.replaceState({}, "", "/?demo=1");
  const api = createLabApi();
  const recipes = vi.spyOn(api, "recipes")
    .mockRejectedValueOnce(Error("Controller temporarily unavailable"))
    .mockResolvedValue({ recipes: [], total: 0 });
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => {
      root.render(<RecipesPage {...({ api, navigate: vi.fn() } as unknown as PageProps)} />);
    });
    expect(container.textContent).toContain("Controller temporarily unavailable");
    expect(container.textContent).not.toContain("Loading recipes");
    await act(async () => {
      [...container.querySelectorAll("button")].find(button => button.textContent === "Retry")!.click();
    });
    expect(recipes).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain("No validated recipes");
    expect(container.textContent).not.toContain("Request failed");
  } finally {
    await act(async () => root.unmount());
    container.remove();
    window.history.replaceState({}, "", "/");
  }
});

it("follows queued recipe verification to its worker result instead of leaving pending JSON", async () => {
  window.history.replaceState({}, "", "/?demo=1");
  const api = createLabApi();
  const recipe = { ...DEMO_RECIPE, recipe: { ...DEMO_RECIPE.recipe, hardware: { worker_id: "worker-test" } } };
  vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [recipe], total: 1 });
  const verify = vi.spyOn(api, "verifyRecipe").mockResolvedValue({ command_id: "verify-test", status: "pending" });
  vi.spyOn(api, "workerCommands").mockResolvedValue([{
    command_id: "verify-test", worker_id: "worker-test", command_type: "VERIFY_RECIPE",
    status: "completed", attempts: 1, lease_generation: 1, created_at: DEMO_RECIPE.created_at,
    result: { command_type: "VERIFY_RECIPE", recipe_id: recipe.recipe_id, verified: true,
      mismatches: [], message: "recipe identities match the current inventory" },
  } as Schemas["CommandStatusView"]]);
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => {
      root.render(<RecipesPage {...({ api, navigate: vi.fn() } as unknown as PageProps)} />);
    });
    await act(async () => {
      [...container.querySelectorAll("button")].find(button => button.textContent === "Verify installation")!.click();
    });
    expect(verify).toHaveBeenCalledTimes(1);
    expect(api.workerCommands).toHaveBeenCalledWith("worker-test");
    expect(container.textContent).toContain("recipe identities match the current inventory");
    expect(container.textContent).toContain('"verified": true');
    expect(container.textContent).not.toContain('"status": "pending"');
  } finally {
    await act(async () => root.unmount());
    container.remove();
    window.history.replaceState({}, "", "/");
  }
});

it("uses the persisted recipe status and contract fields rather than demo-only validation flags", async () => {
  window.history.replaceState({}, "", "/?demo=1");
  const api = createLabApi();
  const recipe = {
    ...DEMO_RECIPE,
    recipe: {
      ...DEMO_RECIPE.recipe,
      constraints: undefined,
      context_tokens: 4096,
      validation: { claim_scope: ["4K"], validated_at: DEMO_RECIPE.created_at },
    },
  };
  vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [recipe], total: 1 });
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => {
      root.render(<RecipesPage {...({ api, navigate: vi.fn() } as unknown as PageProps)} />);
    });
    expect(container.textContent).toContain("Recipe validation recorded");
    expect(container.textContent).not.toContain("Recipe is not validated");
    expect(container.textContent).toContain("4,096 tokens");
    expect(container.textContent).toContain("Validated scope4K");
    expect(container.textContent).not.toContain("not required");
  } finally {
    await act(async () => root.unmount());
    container.remove();
    window.history.replaceState({}, "", "/");
  }
});
