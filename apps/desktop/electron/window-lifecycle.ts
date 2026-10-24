import type { BrowserWindow, MessageBoxOptions, MessageBoxReturnValue } from "electron";

export function attachWindowLifecycle(window: BrowserWindow, actions: {
  quitting(): boolean;
  hasTray(): boolean;
  choose(options: MessageBoxOptions): Promise<MessageBoxReturnValue>;
  quit(): Promise<void>;
  closed(senderId: number): void;
  error(error: unknown): void;
}): void {
  // webContents is already destroyed when Electron emits `closed`.
  const senderId = window.webContents.id;
  let prompting = false;
  window.once("ready-to-show", () => {
    if (!window.isDestroyed() && window.isVisible()) window.focus();
  });
  window.on("close", (event) => {
    if (actions.quitting()) return;
    event.preventDefault();
    if (prompting) return;
    prompting = true;
    void (async () => {
      try {
        const tray = actions.hasTray();
        const answer = await actions.choose({
          type: "question", title: "Close Inference Lab?", message: "Quit or keep the lab running?",
          detail: tray ? "Quit stops active work and all local services. Minimize keeps jobs running in the system tray." : "Quit stops active work and all local services. Minimize keeps the window in the taskbar because no system tray is available.",
          buttons: ["Quit", tray ? "Minimize to tray" : "Minimize", "Cancel"], defaultId: 2, cancelId: 2,
        });
        if (actions.quitting() || window.isDestroyed()) return;
        if (answer.response === 0) await actions.quit();
        else if (answer.response === 1) {
          if (actions.hasTray()) window.hide();
          else window.minimize();
        }
      } catch (error) { actions.error(error); }
      finally { prompting = false; }
    })();
  });
  window.on("closed", () => actions.closed(senderId));
}
