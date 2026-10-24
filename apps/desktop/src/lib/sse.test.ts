import { describe, expect, it } from "vitest";
import { consumeSseBuffer, dispatchSseMessage } from "./sse";

describe("SSE parser", () => {
  it("parses event, id and multi-line data", () => {
    const parsed = consumeSseBuffer(
      "id: 7\nevent: snapshot\ndata: {\"a\":1}\ndata: {\"b\":2}\n\n",
    );
    expect(parsed.rest).toBe("");
    expect(parsed.messages).toEqual([
      { event: "snapshot", id: 7, data: "{\"a\":1}\n{\"b\":2}" },
    ]);
  });

  it("keeps incomplete blocks for the next chunk", () => {
    const first = consumeSseBuffer("id: 9\nevent: job\ndata: {\"x\":");
    expect(first.messages).toHaveLength(0);
    expect(first.rest).toContain("data");
    const second = consumeSseBuffer(`${first.rest}1}\n\n`);
    expect(second.messages).toEqual([{ event: "job", id: 9, data: "{\"x\":1}" }]);
  });

  it("handles CRLF, comments and default event names", () => {
    const parsed = consumeSseBuffer(": keepalive\r\ndata: hello\r\n\r\n");
    expect(parsed.messages).toEqual([{ event: "message", id: null, data: "hello" }]);
  });

  it("dispatches JSON and retains non-JSON safely", () => {
    const seen: unknown[] = [];
    dispatchSseMessage({ event: "x", id: 3, data: "{\"ok\":true}" }, (_event, _id, data) => seen.push(data));
    dispatchSseMessage({ event: "x", id: 4, data: "not-json" }, (_event, _id, data) => seen.push(data));
    expect(seen).toEqual([{ ok: true }, { raw: "not-json" }]);
  });
});
