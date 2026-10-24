import { describe, expect, it } from "vitest";
import { recommendBuild, type HardwareProfile } from "./build-recommendation";
import { parseRelease, type EngineRelease } from "./engine-updates";
const asset = (id: number, name: string) => ({ id, name, size: 10, digest: "sha256:" + "a".repeat(64), url: "https://github.com/project/release" });
const llama: EngineRelease = { engine_id: "llamacpp", version: "1.0.0", tag: "v1", published: "", preview: false, installed_version: null, update: "unknown", page: "", assets: [asset(1, "llama-b1-bin-ubuntu-cuda-12.8-x64.tar.gz"), asset(2, "llama-b1-bin-ubuntu-cuda-13.4-x64.tar.gz"), asset(3, "llama-b1-bin-ubuntu-vulkan-x64.tar.gz"), asset(4, "llama-b1-bin-ubuntu-x64.tar.gz")] };
const profile = (gpu: HardwareProfile["gpus"][number]): HardwareProfile => ({ architecture: "x86_64", cpu_avx2: true, gpus: [gpu], warnings: [] });
const nvidia = { vendor: "nvidia", name: "NVIDIA GeForce RTX 3060", driver_version: "595.99.02", compute_capability: "8.6", device_type: "discrete" };
const strata: EngineRelease = { ...llama, engine_id: "strata", assets: [asset(5, "strata-engine-1.0-linux-x86_64-cuda-cuda12.tar.gz"), asset(6, "strata-engine-1.0-linux-x86_64-cuda-cuda13.tar.gz"), asset(7, "strata-engine-1.0-linux-x86_64-hip-rx7900.tar.gz")] };
describe("dynamic hardware build matching", () => {
  it("uses the detected driver, rather than always choosing the newest CUDA archive", () => {
    expect(recommendBuild(llama, profile(nvidia)).asset_id).toBe(1);
    expect(recommendBuild(llama, profile({ ...nvidia, driver_version: "615.20" })).asset_id).toBe(2);
    expect(recommendBuild(strata, profile(nvidia)).asset_id).toBe(6);
    expect(recommendBuild(strata, profile({ ...nvidia, driver_version: "575.57.08" })).asset_id).toBe(5);
  });
  it.each(["intel", "amd", "other"])("matches a physical %s Vulkan GPU without relying on marketing names", vendor => {
    expect(recommendBuild(llama, profile({ vendor, name: "Any supported card", vulkan_version: "1.3" })).asset_id).toBe(3);
  });
  it("matches AMD native assets by observed architecture", () => {
    expect(recommendBuild(strata, profile({ vendor: "amd", name: "AMD GPU", architecture: "gfx1100" })).asset_id).toBe(7);
    expect(recommendBuild(strata, profile({ vendor: "amd", name: "AMD GPU", architecture: "gfx9999" })).asset_id).toBeNull();
  });
  it("offers a CPU build only with known CPU support, and no invented Strata fallback", () => {
    expect(recommendBuild(llama, { architecture: "x86_64", cpu_avx2: true, warnings: [], gpus: [] }).asset_id).toBe(4);
    expect(recommendBuild(llama, { architecture: "x86_64", cpu_avx2: false, warnings: [], gpus: [] }).asset_id).toBeNull();
    expect(recommendBuild(strata, { architecture: "x86_64", cpu_avx2: true, warnings: [], gpus: [] }).asset_id).toBeNull();
  });
  it("handles mixed GPUs and missing drivers without inventing CUDA compatibility", () => {
    const mixed = { ...profile(nvidia), gpus: [{ vendor: "intel", name: "Integrated GPU", vulkan_version: "1.3", device_type: "integrated" }, nvidia] };
    expect(recommendBuild(llama, mixed).asset_id).toBe(1);
    expect(recommendBuild(llama, profile({ ...nvidia, driver_version: undefined })).asset_id).toBeNull();
    expect(recommendBuild(strata, profile({ ...nvidia, compute_capability: "6.1" })).asset_id).toBeNull();
  });
  it("requires a checksum-verified CUDA runtime archive before offering a CUDA build", () => {
    const name = "llama-b1-bin-ubuntu-cuda-12.8-x64.tar.gz";
    const raw = { tag_name: "b1", assets: [{ ...asset(1, name), browser_download_url: `https://github.com/ggml-org/llama.cpp/releases/download/b1/${name}` }] };
    expect(parseRelease("llamacpp", raw, "x64").assets).toHaveLength(0);
    raw.assets.push({ ...asset(2, `cudart-${name}`), browser_download_url: `https://github.com/ggml-org/llama.cpp/releases/download/b1/cudart-${name}` });
    const result = parseRelease("llamacpp", raw, "x64");
    expect(result.assets).toHaveLength(1); expect(result.dependencies?.[1]?.[0]?.id).toBe(2);
  });
});
