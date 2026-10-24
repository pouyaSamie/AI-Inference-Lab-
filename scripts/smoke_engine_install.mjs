// Synthetic archives exercise the actual downloader/hash/extractor/publication path.
// No downloaded code, real engine, installer script, model or user folder is used.
import { createRequire } from "node:module";
import { promises as fs } from "node:fs";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import path from "node:path";
import os from "node:os";
const require = createRequire(import.meta.url);
const { EngineUpdates } = require("../apps/desktop/dist-electron/engine-updates.js");
const backend = path.resolve(process.argv[2] ?? "apps/desktop/release/linux-deb/opt/ai-inference-lab/desktop/resources/app/backend");
const python = path.join(backend, "python/bin/python3");
const temp = await fs.mkdtemp(path.join(os.tmpdir(), "lab-engine-install-smoke-"));
try {
  execFileSync(python, ["-I", "-c", `
import io,tarfile,sys
from pathlib import Path
root=Path(sys.argv[1])
def make(name,files):
 with tarfile.open(root/name,'w:gz') as tar:
  for file in files:
   info=tarfile.TarInfo(file);info.mode=0o700
   data=b'# synthetic fixture: never execute\\n';info.size=len(data)
   tar.addfile(info,io.BytesIO(data))
make('llama.tar.gz',['llama/bin/llama-server','llama/bin/llama-bench'])
make('cudart.tar.gz',['cuda/lib/libcudart.so.12'])
make('strata.tar.gz',['engine/strata'])
# A standalone interpreter entry point can be a relative symlink.
with tarfile.open(root/'control.tar.gz','w:gz') as tar:
 for file in ['strata-control/serve/server.py','strata-control/python/bin/python3.12']:
  info=tarfile.TarInfo(file);info.mode=0o700;data=b'# fixture: never execute\\n';info.size=len(data);tar.addfile(info,io.BytesIO(data))
 info=tarfile.TarInfo('strata-control/python/bin/python3');info.type=tarfile.SYMTYPE;info.linkname='python3.12';tar.addfile(info)
`, temp]);
  const binaries = new Map();
  const asset = async (id, family, tag, name, fixture) => {
    const bytes = await fs.readFile(path.join(temp, fixture));
    const repo = family === "llamacpp" ? "ggml-org/llama.cpp" : "Niko1221/Strata";
    const url = `https://github.com/${repo}/releases/download/${tag}/${name}`;
    binaries.set(url, bytes);
    return { id, name, size: bytes.length, digest: "sha256:" + createHash("sha256").update(bytes).digest("hex"), browser_download_url: url };
  };
  const llama = { tag_name: "v0.7.0", assets: [await asset(1, "llamacpp", "v0.7.0", "llama-b123-bin-ubuntu-x64-cuda-12.8.tar.gz", "llama.tar.gz"), await asset(4, "llamacpp", "v0.7.0", "cudart-llama-b123-bin-ubuntu-x64-cuda-12.8.tar.gz", "cudart.tar.gz")] };
  const strata = { tag_name: "v0.2.2", assets: [await asset(2, "strata", "v0.2.2", "strata-engine-0.1.47-linux-x86_64-cuda-cuda12.tar.gz", "strata.tar.gz"), await asset(3, "strata", "v0.2.2", "strata-control-0.1.47-linux-x86_64.tar.gz", "control.tar.gz")] };
  const current = () => ({ config: { model_roots: [] }, engine_candidates: ["llamacpp", "strata"].map(engine_id => ({ id: engine_id, engine_id, version: "0.1.0", version_source: "build metadata", paths: {}, missing: [] })) });
  const manager = new EngineUpdates(temp, backend, current, async url => {
    if (binaries.has(url)) return new Response(binaries.get(url));
    return new Response(JSON.stringify(url.includes("ggml-org") ? llama : strata));
  });
  const status = await manager.check();
  if (status.error) throw new Error(status.error);
  const root = await manager.install("llamacpp", 1);
  await manager.install("strata", 2);
  const result = execFileSync(python, ["-I", "-c", `
import sys,json
sys.path[:0]=[sys.argv[1],sys.argv[2]]
from pathlib import Path
from lab_worker.engine_locations import discover_engine_locations
found=discover_engine_locations((Path(sys.argv[3]),))
assert list(Path(sys.argv[3]).rglob('libcudart.so.12')), 'CUDA runtime library was not installed'
assert len(found)==2,found
assert all(not b['missing'] for b in found),found
assert {b['version'] for b in found}=={'v0.7.0','0.1.47'},found
print('Real bundled extractor: two synthetic side-by-side engine installs, CUDA runtime libraries and Strata server/interpreter discovery passed; no engine executed.')
`, path.join(backend, "site-packages"), path.join(backend, "packages"), root], { encoding: "utf8" });
  console.log(result.trim());
} finally { await fs.rm(temp, { recursive: true, force: true }); }
