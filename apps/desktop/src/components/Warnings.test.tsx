import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";
import { WarningList } from "./ui";

it("explains GPU contention without rendering raw process arguments", async () => {
  const container = document.createElement("div"); const root = createRoot(container);
  await act(async () => root.render(<WarningList warnings={["EXTERNAL_GPU_COMPUTE_PROCESS:browser:123 --opaque-sensitive-flag=123", "GPU_UTILIZATION_BUSY:GPU-1:30%", "CONTEXT_FEASIBILITY_UNPROVEN"]} />));
  try {
    expect(container.textContent).toContain("at the last inventory scan");
    expect(container.textContent).toContain("The selected context sizes have not been tested yet");
    expect(container.textContent).not.toContain("opaque-sensitive-flag");
    expect(container.querySelector("details")?.open).toBe(false);
  } finally { await act(async () => root.unmount()); }
});
