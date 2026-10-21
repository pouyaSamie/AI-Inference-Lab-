export interface ParsedSse {
  event: string;
  id: number | null;
  data: string;
}

/** Parse complete SSE blocks, preserving an incomplete tail for the next chunk. */
export function consumeSseBuffer(buffer: string): { messages: ParsedSse[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const blocks = normalized.split("\n\n");
  const rest = blocks.pop() ?? "";
  const messages: ParsedSse[] = [];
  for (const block of blocks) {
    let event = "message";
    let id: number | null = null;
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (!line || line.startsWith(":")) continue;
      const colon = line.indexOf(":");
      const field = colon === -1 ? line : line.slice(0, colon);
      const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
      if (field === "event") event = value || "message";
      else if (field === "id") {
        const parsed = Number(value);
        id = Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : null;
      } else if (field === "data") data.push(value);
    }
    if (data.length > 0) messages.push({ event, id, data: data.join("\n") });
  }
  return { messages, rest };
}

export function parseSseData(raw: string): unknown {
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return { raw: raw.slice(0, 8_000) };
  }
}
