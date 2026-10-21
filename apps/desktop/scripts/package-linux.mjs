import { spawnSync } from "node:child_process";
import { promises as fs } from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const packageJson = JSON.parse(await fs.readFile(path.join(root, "package.json"), "utf8"));
const version = String(packageJson.version ?? "0.0.0");
const arch = process.arch === "arm64" ? "arm64" : "amd64";
const releaseDir = path.join(root, "release");
const stage = path.join(releaseDir, "linux-deb");
const appRoot = path.join(stage, "opt/ai-inference-lab/desktop");
const electronDist = path.join(root, "node_modules/electron/dist");
const output = path.join(releaseDir, `ai-inference-lab-desktop_${version}_${arch}.deb`);

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: root,
    stdio: "inherit",
    env: process.env,
    ...options,
  });
  if (result.status !== 0) {
    throw new Error(`${command} exited with status ${result.status ?? "unknown"}`);
  }
}

async function copyDirectory(source, destination) {
  await fs.cp(source, destination, { recursive: true, dereference: true });
}

async function write(file, content, mode) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  await fs.writeFile(file, content, { encoding: "utf8", mode });
}

async function normalizeTree(directory, mode) {
  const entries = await fs.readdir(directory, { withFileTypes: true });
  for (const entry of entries) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      await fs.chmod(target, 0o755);
      await normalizeTree(target, mode);
    } else if (entry.isFile()) {
      await fs.chmod(target, mode);
    }
  }
}

async function normalizeDirectories(directory) {
  const entries = await fs.readdir(directory, { withFileTypes: true });
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const target = path.join(directory, entry.name);
    await fs.chmod(target, 0o755);
    await normalizeDirectories(target);
  }
}

await fs.access(electronDist).catch(() => {
  throw new Error("Electron is not installed. Run `npm install` in apps/desktop first.");
});

run(process.execPath, [path.join(root, "scripts/build.mjs")]);

await fs.rm(stage, { recursive: true, force: true });
await fs.mkdir(releaseDir, { recursive: true });
await copyDirectory(electronDist, appRoot);

const resources = path.join(appRoot, "resources");
await fs.rm(path.join(resources, "default_app.asar"), { force: true });
const packagedApp = path.join(resources, "app");
await fs.mkdir(packagedApp, { recursive: true });
await copyDirectory(path.join(root, "dist"), path.join(packagedApp, "dist"));
await copyDirectory(path.join(root, "dist-electron"), path.join(packagedApp, "dist-electron"));
await normalizeTree(packagedApp, 0o644);
await write(
  path.join(packagedApp, "package.json"),
  `${JSON.stringify(
    {
      name: "ai-inference-lab-desktop",
      productName: "AI Inference Optimization Lab",
      version,
      private: true,
      description: "Local Electron operator console for the AI Inference Optimization Lab",
      type: "module",
      main: "dist-electron/main.js",
    },
    null,
    2,
  )}\n`,
  0o644,
);

const chromeSandbox = path.join(appRoot, "chrome-sandbox");
await fs.chmod(chromeSandbox, 0o4755);

await write(
  path.join(stage, "usr/bin/ai-inference-lab"),
  "#!/bin/sh\nexec /opt/ai-inference-lab/desktop/electron \"$@\"\n",
  0o755,
);
await write(
  path.join(stage, "usr/share/applications/ai-inference-lab.desktop"),
  `[Desktop Entry]
Type=Application
Name=AI Inference Optimization Lab
Comment=Local-first inference optimization operator console
Exec=/usr/bin/ai-inference-lab %U
Icon=ai-inference-lab
Terminal=false
Categories=Development;Science;
StartupWMClass=AI Inference Optimization Lab
`,
  0o644,
);
await fs.mkdir(path.join(stage, "usr/share/icons/hicolor/scalable/apps"), { recursive: true });
const iconTarget = path.join(stage, "usr/share/icons/hicolor/scalable/apps/ai-inference-lab.svg");
await fs.copyFile(path.join(root, "build/icon.svg"), iconTarget);
await fs.chmod(iconTarget, 0o644);

await write(
  path.join(stage, "DEBIAN/control"),
  `Package: ai-inference-lab-desktop
Version: ${version}
Section: utils
Priority: optional
Architecture: ${arch}
Maintainer: AI Inference Optimization Lab <operator@localhost>
Description: Local-first AI inference optimization operator console
 Electron operator UI for the AI Inference Optimization Lab. It connects to a
 separately managed FastAPI controller and never owns benchmark processes.
Depends: libgtk-3-0, libnss3, libx11-xcb1, libxcomposite1, libxdamage1, libxrandr2, libgbm1, libasound2, libatk-bridge2.0-0, libcups2, libdrm2, libxkbcommon0, libpango-1.0-0, libcairo2, libatspi2.0-0
`,
  0o644,
);
await write(
  path.join(stage, "DEBIAN/postinst"),
  `#!/bin/sh
set -e
chown root:root /opt/ai-inference-lab/desktop/chrome-sandbox || true
chmod 4755 /opt/ai-inference-lab/desktop/chrome-sandbox || true
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi
exit 0
`,
  0o755,
);

await normalizeDirectories(stage);
await fs.chmod(chromeSandbox, 0o4755);
await fs.chmod(path.join(stage, "usr/bin/ai-inference-lab"), 0o755);
await fs.chmod(path.join(stage, "DEBIAN/postinst"), 0o755);
await fs.chmod(iconTarget, 0o644);
run("dpkg-deb", ["--root-owner-group", "--build", stage, output]);
const stat = await fs.stat(output);
console.log(`Built ${output} (${(stat.size / 1_048_576).toFixed(1)} MiB).`);
console.log("Installation, signing and AppImage packaging remain explicit operator/release steps.");
