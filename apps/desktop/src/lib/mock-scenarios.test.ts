import { afterEach, expect, it } from "vitest";
import { createMockApi } from "./mock";
import { createLabApi } from "./api";

afterEach(() => { localStorage.clear(); window.history.replaceState({},"","/"); });
it("keeps large and missing-metric fixtures explicit and distinct from real evidence", async () => {
  const large = await createMockApi("large").experiment("exp-demo-simulated");
  expect(large.candidates).toHaveLength(5000); expect(large.simulation).toBe(true);
  const partial = await createMockApi("partial").experiment("exp-demo-simulated");
  expect(partial.observations?.every(o => o.measurement_status === "unavailable" && !o.metrics?.decode_tokens_per_sec)).toBe(true);
});
it("blocks stale fixture planning and rejects demo creation through the API facade", async () => {
  window.history.replaceState({},"","/?demo=1&demoScenario=stale");
  const api = createLabApi(), view = await api.experiment("exp-demo-simulated");
  const plan = await api.plan({worker_id:view.spec.worker_id,model_id:view.spec.model.model_id,engine_id:"llamacpp",contexts:[4096]});
  expect(plan.status).toBe("preflight_required"); expect(plan.command_id).toBe("cmd-demo-stale-snapshot");
  await expect(api.createExperiment(view.plan)).rejects.toThrow("cannot create experiment evidence");
});
