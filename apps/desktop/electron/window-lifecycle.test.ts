import { EventEmitter } from "node:events";
import type { BrowserWindow } from "electron";
import { describe, expect, it, vi } from "vitest";
import { attachWindowLifecycle } from "./window-lifecycle";

class Window extends EventEmitter {
  destroyed = false;
  get webContents() { if (this.destroyed) throw new Error("Object has been destroyed"); return { id: 42 }; }
  isDestroyed = () => this.destroyed;
  isVisible = () => true;
  focus = vi.fn(); hide = vi.fn(); minimize = vi.fn();
}
function setup(response = 2, tray = true) {
  const window = new Window();
  const actions = { quitting: () => false, hasTray: () => tray, choose: vi.fn(async () => ({ response, checkboxChecked: false })), quit: vi.fn(async () => {}), closed: vi.fn(), error: vi.fn() };
  attachWindowLifecycle(window as unknown as BrowserWindow, actions);
  return { window, actions };
}
const settle = () => new Promise(resolve => setTimeout(resolve, 0));
describe("window close lifecycle", () => {
  it("cleans up with a cached sender ID after webContents is destroyed", () => {
    const { window, actions } = setup(); window.destroyed = true;
    expect(() => window.emit("closed")).not.toThrow();
    window.emit("ready-to-show");
    expect(actions.closed).toHaveBeenCalledWith(42);
    expect(window.focus).not.toHaveBeenCalled();
  });
  it.each([[0, true, "quit"], [1, true, "hide"], [1, false, "minimize"], [2, true, "cancel"]] as const)("handles response %s with tray %s", async (response, tray, result) => {
    const { window, actions } = setup(response, tray); const preventDefault = vi.fn();
    window.emit("close", { preventDefault }); await settle();
    expect(preventDefault).toHaveBeenCalled();
    expect(actions.quit).toHaveBeenCalledTimes(result === "quit" ? 1 : 0);
    expect(window.hide).toHaveBeenCalledTimes(result === "hide" ? 1 : 0);
    expect(window.minimize).toHaveBeenCalledTimes(result === "minimize" ? 1 : 0);
  });
  it("coalesces repeated close requests and ignores a destroyed window after the prompt", async () => {
    const { window, actions } = setup(1);
    window.emit("close", { preventDefault: vi.fn() });
    window.emit("close", { preventDefault: vi.fn() });
    window.destroyed = true; await settle();
    expect(actions.choose).toHaveBeenCalledTimes(1);
    expect(window.hide).not.toHaveBeenCalled();
    expect(actions.error).not.toHaveBeenCalled();
  });
});
