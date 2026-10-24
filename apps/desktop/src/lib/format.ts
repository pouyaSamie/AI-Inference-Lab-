import { CONTEXT_LABELS } from "./contracts";

export function contextLabel(context: number): string {
  return CONTEXT_LABELS[context] ?? `${context}`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return "unavailable";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let value = Math.max(0, bytes);
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 100 || unit === 0 ? 0 : value >= 10 ? 1 : 2)} ${units[unit]}`;
}

export function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "unavailable";
  return value.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "unavailable";
  return `${(value * 100).toFixed(1)}%`;
}

export function formatDelta(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "unavailable";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return "never";
  const date = new Date(value);
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (!Number.isFinite(seconds)) return value;
  if (Math.abs(seconds) < 60) return `${seconds}s ago`;
  if (Math.abs(seconds) < 3_600) return `${Math.round(seconds / 60)}m ago`;
  if (Math.abs(seconds) < 86_400) return `${Math.round(seconds / 3_600)}h ago`;
  return `${Math.round(seconds / 86_400)}d ago`;
}

export function shortId(value: string | null | undefined, length = 12): string {
  if (!value) return "—";
  return value.length <= length ? value : `${value.slice(0, length)}…`;
}

export function humanEnum(value: string | null | undefined): string {
  if (!value) return "—";
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function shellQuote(value: string): string {
  return `'${value.replaceAll("'", "'\\''")}'`;
}

export function downloadText(name: string, content: string, type = "text/plain"): void {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function toYaml(value: unknown, indent = 0): string {
  const pad = "  ".repeat(indent);
  if (value === null || value === undefined) return "null";
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    return value
      .map((item) => {
        const rendered = toYaml(item, indent + 1);
        if (rendered.includes("\n") || (typeof item === "object" && item !== null)) {
          return `${pad}- ${rendered.replace(/^\s+/, "")}`;
        }
        return `${pad}- ${rendered}`;
      })
      .join("\n");
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return "{}";
    return entries
      .map(([key, item]) => {
        if (item === null || item === undefined) return `${pad}${key}: null`;
        if (typeof item === "object") {
          return `${pad}${key}:\n${toYaml(item, indent + 1)}`;
        }
        return `${pad}${key}: ${toYaml(item, indent)}`;
      })
      .join("\n");
  }
  return String(value);
}

export function recipeToBash(recipe: Record<string, unknown>): string {
  const launch = (recipe.launch ?? {}) as {
    executable?: string;
    argv?: string[];
    env?: Record<string, string>;
  };
  const env = Object.entries(launch.env ?? {})
    .map(([key, value]) => `${key}=${shellQuote(value)}`)
    .join(" ");
  const executable = shellQuote(launch.executable ?? "<missing-executable>");
  const args = (launch.argv ?? []).map(shellQuote).join(" ");
  return `#!/usr/bin/env bash\nset -euo pipefail\n\nexport ${env || "# no extra environment"}\nexec ${executable} ${args}\n`;
}

export function recipeToSystemd(recipe: Record<string, unknown>): string {
  const launch = (recipe.launch ?? {}) as {
    executable?: string;
    argv?: string[];
    env?: Record<string, string>;
  };
  const args = (launch.argv ?? []).map(quoteSystemdArg).join(" ");
  const environment = Object.entries(launch.env ?? {})
    .map(([key, value]) => `Environment=${JSON.stringify(`${key}=${value}`)}`)
    .join("\n");
  return `[Unit]\nDescription=AI Inference Optimization Lab validated recipe\nAfter=network.target\n\n[Service]\nType=simple\n${environment ? `${environment}\n` : ""}ExecStart=${launch.executable ?? "/missing-executable"} ${args}\nRestart=on-failure\nNoNewPrivileges=yes\nPrivateTmp=yes\n\n[Install]\nWantedBy=multi-user.target\n`;
}

function quoteSystemdArg(value: string): string {
  if (/^[A-Za-z0-9_./:@%+=,-]+$/.test(value)) return value;
  return `"${value.replaceAll("\\", "\\\\").replaceAll('"', '\\"')}"`;
}

export function metric(
  value: number | null | undefined,
  suffix = "",
  digits = 1,
): string {
  const rendered = formatNumber(value, digits);
  return rendered === "unavailable" ? rendered : `${rendered}${suffix}`;
}
