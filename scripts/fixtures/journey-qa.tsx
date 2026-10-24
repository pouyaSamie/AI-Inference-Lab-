// UI-only visual fixture. Never included in the packaged entry point.
import React from "../../apps/desktop/node_modules/react/index.js";
import { createRoot } from "../../apps/desktop/node_modules/react-dom/client.js";
import { EngineUpdatesPanel } from "../../apps/desktop/src/components/EngineUpdates";
import { ModelVerificationProgress } from "../../apps/desktop/src/components/ModelVerification";
import "../../apps/desktop/src/styles.css";
import "../../apps/desktop/src/workstation.css";
const params = new URLSearchParams(location.search);
document.documentElement.dataset.theme = params.get("theme") ?? "dark";
createRoot(document.getElementById("root")!).render(<main style={{ padding: 24 }}><p>OFFLINE UI FIXTURE · no download, engine or model is contacted</p><h1>Engine maintenance</h1><EngineUpdatesPanel /><ModelVerificationProgress value={{ state: "verifying", updated_at: Date.now()/1000-130, bytes_done: 30, bytes_total: 100, files_done: 0, files_total: 1, current_file: "example-split-model.gguf" }} /></main>);
