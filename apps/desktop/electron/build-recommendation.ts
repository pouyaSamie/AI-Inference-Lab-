import type { EngineRelease } from "./engine-updates";
export interface HardwareProfile {
  architecture: string; cpu_avx2: boolean; warnings: string[];
  gpus: { vendor: string; name: string; driver_version?: string; compute_capability?: string; architecture?: string; vulkan_version?: string; device_type?: string; vram_bytes?: number }[];
}
export interface BuildRecommendation { asset_id: number | null; label: string; reason: string; hardware: string }
// Conservative corresponding-driver requirements, rather than assuming that
// every archive works through CUDA minor-version compatibility:
// https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html#cuda-driver
// Strata's release packaging declares variant requirements independently:
// https://github.com/Niko1221/Strata/blob/v0.2.2/packaging/build_cuda_linux.sh
const CUDA_DRIVERS: Record<string, number[]> = {
  "12.8": [570, 124, 6], "12.9": [575, 57, 8], "13.0": [580, 65, 6],
  "13.1": [590], "13.2": [595], "13.3": [610], "13.4": [615],
};
function atLeast(actual: string | undefined, required: number[]): boolean {
  if (!actual || !/^\d+(?:\.\d+)*$/.test(actual)) return false;
  const parts = actual.split(".").map(Number);
  for (let i = 0; i < Math.max(parts.length, required.length); i++) {
    if ((parts[i] ?? 0) !== (required[i] ?? 0)) return (parts[i] ?? 0) > (required[i] ?? 0);
  }
  return true;
}
export function recommendBuild(release: EngineRelease, profile: HardwareProfile): BuildRecommendation {
  const gpus = [...profile.gpus].sort((a, b) => Number(b.device_type === "discrete") - Number(a.device_type === "discrete") || (b.vram_bytes ?? 0) - (a.vram_bytes ?? 0));
  const matches: { id: number; score: number; label: string; reason: string; hardware: string }[] = [];
  for (const gpu of gpus) {
    const hardware = `${gpu.name}${gpu.driver_version ? ` · driver ${gpu.driver_version}` : ""}`;
    const capability = Number(gpu.compute_capability);
    for (const asset of release.assets) {
      if (gpu.vendor === "nvidia" && Number.isFinite(capability) && capability >= 7.5) {
        const tag = /-cuda-(\d+\.\d+)-/.exec(asset.name)?.[1];
        const toolkit = release.engine_id === "strata" ? /-cuda-cuda(12|13)\./.exec(asset.name)?.[1] : tag;
        const minimum = toolkit === "12" ? [575, 57, 8] : toolkit === "13" ? [580, 65, 6] : toolkit ? CUDA_DRIVERS[toolkit] : undefined;
        // Require a documented full-support driver rather than assuming minor compatibility/PTX behavior.
        if (toolkit && minimum && atLeast(gpu.driver_version, minimum)) {
          matches.push({ id: asset.id, score: 1000 + Number(toolkit), label: `NVIDIA GPU acceleration · CUDA ${toolkit}`, reason: "Matches the detected NVIDIA GPU and installed driver. Required runtime libraries are included.", hardware });
        }
      }
      if (gpu.vendor === "amd" && release.engine_id === "strata") {
        const family = ({ gfx1100: "rx7900", gfx1201: "rx9070", gfx1151: "halo" } as Record<string, string>)[gpu.architecture ?? ""];
        if (family && asset.name.includes(`-hip-${family}.`)) matches.push({ id: asset.id, score: 900, label: `AMD GPU acceleration · ${gpu.architecture}`, reason: "Matches the GPU architecture reported by the AMD driver.", hardware });
      }
      if (release.engine_id === "llamacpp" && atLeast(gpu.vulkan_version, [1, 2]) && asset.name.includes("-vulkan-")) {
        matches.push({ id: asset.id, score: 500, label: "GPU acceleration · Vulkan", reason: "The installed Vulkan driver reports a physical GPU with Vulkan 1.2 or newer.", hardware });
      }
    }
  }
  matches.sort((a, b) => b.score - a.score); // Stable ordering favors a discrete GPU, then observed VRAM.
  const best = matches[0];
  if (best) return { asset_id: best.id, label: best.label, reason: best.reason, hardware: best.hardware };
  if (!gpus.length && (profile.cpu_avx2 || ["arm64", "aarch64"].includes(profile.architecture)) && release.engine_id === "llamacpp") {
    const cpu = release.assets.find(a => /-bin-ubuntu-(x64|arm64)\.tar\.gz$/.test(a.name));
    if (cpu) return { asset_id: cpu.id, label: "CPU build", reason: "No usable GPU driver was detected. Your CPU supports this build; CPU execution is slower and the current optimization lane still requires a supported GPU.", hardware: profile.architecture };
  }
  return { asset_id: null, label: "Compatibility check needed", hardware: gpus.map(g => g.name).join(", ") || profile.architecture,
    reason: !gpus.length ? "No usable GPU driver was detected. Keep your current build, check the driver, then restart the app to detect hardware again." : "No published build could be matched confidently to the detected GPU and driver. Keep your current engine; advanced builds remain available for review." };
}
