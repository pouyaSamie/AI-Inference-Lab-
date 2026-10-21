import { describe, expect, it } from "vitest";
import { consumeSseBuffer, parseSseData } from "./sse-parser";

describe("main-process SSE parser", () => {
  it("parses replay frames identically to the renderer parser", () => {
    const parsed = consumeSseBuffer("id: 44\nevent: event.gap\ndata: {\"from\":10}\n\n");
    expect(parsed.messages).toEqual([{ event: "event.gap", id: 44, data: "{\"from\":10}" }]);
  });

  it("handles chunk boundaries", () => {
    const first = consumeSseBuffer("id: 1\ndata: {\"snap");
    expect(first.messages).toHaveLength(0);
    const second = consumeSseBuffer(`${first.rest}shot\":true}\n\nid: 2\ndata: x\n\n`);
    expect(second.messages).toHaveLength(2);
    expect(second.messages[0]?.id).toBe(1);
  });

  it("parses JSON and falls back to bounded raw data", () => {
    expect(parseSseData("{\"x\":1}")).toEqual({ x: 1 });
    expect(parseSseData("not json")).toEqual({ raw: "not json" });
  });
});
