import { beforeEach, describe, expect, it } from "vitest";
import { demoRequested, setDemoRequested } from "./api";

describe("offline demo selection", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.history.replaceState({}, "", "/");
  });

  it("clears the URL override when demo mode is disabled", () => {
    window.history.replaceState({}, "", "/?demo=1#/settings");
    expect(demoRequested()).toBe(true);
    setDemoRequested(false);
    expect(demoRequested()).toBe(false);
    expect(window.location.search).toBe("");
    expect(window.location.hash).toBe("#/settings");
  });

  it("persists an explicit demo choice without the URL flag", () => {
    setDemoRequested(true);
    expect(demoRequested()).toBe(true);
    window.history.replaceState({}, "", "/#/overview");
    expect(demoRequested()).toBe(true);
    setDemoRequested(false);
    expect(demoRequested()).toBe(false);
  });
});
