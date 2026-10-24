import { describe, expect, it } from "vitest";
import { recipeToBash, recipeToSystemd, shellQuote, toYaml } from "./format";

describe("operator export formatting", () => {
  it("quotes shell arguments without interpolation", () => {
    expect(shellQuote("plain")).toBe("'plain'");
    expect(shellQuote("it's $HOME")).toBe("'it'\\''s $HOME'");
  });

  it("renders a deterministic YAML subset", () => {
    const rendered = toYaml({
      schema_version: "1.0.0",
      launch: { argv: ["--model", "a b"], env: { LD_LIBRARY_PATH: "/opt/lib" } },
      enabled: true,
      absent: null,
    });
    expect(rendered).toContain("schema_version: \"1.0.0\"");
    expect(rendered).toContain("argv:");
    expect(rendered).toContain("- \"a b\"");
    expect(rendered).toContain("enabled: true");
    expect(rendered).toContain("absent: null");
  });

  it("exports argv as a bash exec without unsafe joining", () => {
    const script = recipeToBash({
      launch: {
        executable: "/opt/lab/llama-server",
        argv: ["--model", "/models/qwen.gguf", "--n-gpu-layers", "-1"],
        env: { LD_LIBRARY_PATH: "/opt/lab/lib" },
      },
    });
    expect(script).toContain("#!/usr/bin/env bash");
    expect(script).toContain("exec '/opt/lab/llama-server'");
    expect(script).toContain("'--model' '/models/qwen.gguf'");
    expect(script).toContain("LD_LIBRARY_PATH='/opt/lab/lib'");
  });

  it("exports a systemd service with no privileged directives", () => {
    const unit = recipeToSystemd({
      launch: {
        executable: "/opt/lab/llama-server",
        argv: ["--ctx-size", "8192"],
        env: { LD_LIBRARY_PATH: "/opt/lab/lib" },
      },
    });
    expect(unit).toContain("ExecStart=/opt/lab/llama-server --ctx-size 8192");
    expect(unit).toContain("NoNewPrivileges=yes");
    expect(unit).not.toContain("User=root");
  });
});
