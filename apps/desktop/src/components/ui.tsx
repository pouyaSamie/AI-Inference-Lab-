import type { ReactNode } from "react";
import { humanEnum } from "../lib/format";

export type Tone = "neutral" | "ok" | "warn" | "danger" | "info" | "simulated";

export function Badge({
  tone = "neutral",
  children,
  title,
}: {
  tone?: Tone;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  );
}

export function StatusBadge({ value }: { value: string | null | undefined }) {
  const normalized = (value ?? "").toLowerCase();
  const tone: Tone =
    normalized.includes("complete") ||
    normalized.includes("validated") ||
    normalized === "online" ||
    normalized === "ready" ||
    normalized === "passed"
      ? "ok"
      : normalized.includes("fail") ||
          normalized.includes("error") ||
          normalized.includes("infeasible") ||
          normalized.includes("blocked")
        ? "danger"
        : normalized.includes("simulat")
          ? "simulated"
          : normalized.includes("run") ||
              normalized.includes("progress") ||
              normalized.includes("screen") ||
              normalized.includes("preflight")
            ? "info"
            : normalized.includes("pause") ||
                normalized.includes("pending") ||
                normalized.includes("queued") ||
                normalized.includes("inconclusive") ||
                normalized.includes("ineligible")
              ? "warn"
              : "neutral";
  return <Badge tone={tone}>{humanEnum(value ?? "unknown")}</Badge>;
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
        <h1>{title}</h1>
        {description ? <p className="page-description">{description}</p> : null}
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}

export function Panel({
  title,
  subtitle,
  actions,
  children,
  className = "",
}: {
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`.trim()}>
      {title || actions ? (
        <div className="panel-heading">
          <div>
            {title ? <h2>{title}</h2> : null}
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
          {actions ? <div className="panel-actions">{actions}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function Stat({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: Tone;
}) {
  return (
    <div className={`stat ${tone ? `stat-${tone}` : ""}`}>
      <span className="stat-label">{label}</span>
      <strong className="stat-value">{value}</strong>
      {detail ? <span className="stat-detail">{detail}</span> : null}
    </div>
  );
}

export function EmptyState({
  title,
  detail,
  action,
}: {
  title: string;
  detail?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      {detail ? <p>{detail}</p> : null}
      {action}
    </div>
  );
}

export function ErrorNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="notice notice-danger" role="alert">
      <div>
        <strong>Request failed</strong>
        <p>{message}</p>
      </div>
      {onRetry ? (
        <button className="button button-secondary" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}

export function Notice({
  tone = "info",
  title,
  children,
}: {
  tone?: Tone;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className={`notice notice-${tone}`} role={tone === "danger" ? "alert" : undefined}>
      <div>
        <strong>{title}</strong>
        {children ? <div className="notice-body">{children}</div> : null}
      </div>
    </div>
  );
}

export function SimulationBanner({
  simulated,
  warnings = [],
}: {
  simulated: boolean;
  warnings?: string[];
}) {
  if (!simulated && warnings.length === 0) return null;
  return (
    <div className={`simulation-banner ${simulated ? "is-simulated" : ""}`}>
      <strong>{simulated ? "SIMULATED EVIDENCE — NEVER DEPLOYABLE" : "Evidence boundary"}</strong>
      <p>
        {simulated
          ? "This experiment used the explicit simulation lane. It can exercise the workflow, but it cannot produce a validated recipe."
          : "Read the warnings below before interpreting these results."}
      </p>
      {warnings.length > 0 ? (
        <ul>
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}…
    </div>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.value}
          role="tab"
          aria-selected={tab.value === value}
          className={`tab ${tab.value === value ? "active" : ""}`}
          onClick={() => onChange(tab.value)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function KeyValues({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="key-values">
      {items.map((item) => (
        <div key={item.label}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
