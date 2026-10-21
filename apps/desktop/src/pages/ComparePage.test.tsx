import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createLabApi } from "../lib/api";
import { DEMO_EXPERIMENTS } from "../lib/mock";
import { ComparePage } from "./ComparePage";

async function flush(ms = 60): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });
}

describe("Compare finalization presentation", () => {
  let container: HTMLDivElement;

  beforeEach(() => {
    window.history.replaceState({}, "", "/?demo=1");
    window.localStorage.clear();
    container = document.createElement("div");
    document.body.append(container);
  });

  afterEach(() => {
    container.remove();
    window.history.replaceState({}, "", "/");
  });

  it("renders a measured no-winner result without inventing a winner", async () => {
    const api = createLabApi();
    const root = createRoot(container);
    await act(async () =>
      root.render(
        <ComparePage
          api={api}
          status={null}
          statusError={null}
          experiments={{ total: DEMO_EXPERIMENTS.length, experiments: structuredClone(DEMO_EXPERIMENTS) }}
          experimentsError={null}
          activeExperimentId="exp-demo-no-winner"
          setActiveExperimentId={() => undefined}
          navigate={() => undefined}
          refreshShell={() => undefined}
        />,
      ),
    );
    await flush(120);

    expect(container.textContent).toContain("No validated winner");
    expect(container.textContent).toContain("BELOW_MINIMUM_IMPROVEMENT");
    expect(container.textContent).toContain("CONFIDENCE_INTERVAL_NOT_ABOVE_BASELINE");
    expect(container.textContent).toContain("0.940 – 1.110");
    await act(async () => root.unmount());
  });

  it("keeps a simulated finalization visibly non-deployable", async () => {
    const api = createLabApi();
    const root = createRoot(container);
    await act(async () =>
      root.render(
        <ComparePage
          api={api}
          status={null}
          statusError={null}
          experiments={{ total: DEMO_EXPERIMENTS.length, experiments: structuredClone(DEMO_EXPERIMENTS) }}
          experimentsError={null}
          activeExperimentId="exp-demo-simulated"
          setActiveExperimentId={() => undefined}
          navigate={() => undefined}
          refreshShell={() => undefined}
        />,
      ),
    );
    await flush(120);

    expect(container.textContent).toContain("SIMULATED — never a deployable winner");
    expect(container.textContent).toContain("SIMULATED EVIDENCE — NEVER DEPLOYABLE");
    expect(container.textContent).toContain("SIMULATED_EVIDENCE");
    await act(async () => root.unmount());
  });
});
