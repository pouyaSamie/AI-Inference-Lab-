import { WorkstationIcon } from "./Icons";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { humanEnum } from "../lib/format";

export function Modal({ title, children, onClose, busy = false }: {
  title: string; children: ReactNode; onClose(): void; busy?: boolean;
}) {
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const siblings: { element: HTMLElement; inert: boolean }[] = [];
    let branch: HTMLElement | null = panel.current?.parentElement ?? null;
    while (branch?.parentElement) {
      for (const sibling of Array.from(branch.parentElement.children)) {
        if (sibling !== branch && sibling instanceof HTMLElement) {
          siblings.push({ element: sibling, inert: sibling.inert === true }); sibling.inert = true;
        }
      }
      branch = branch.parentElement;
      if (branch === document.body) break;
    }
    panel.current?.focus();
    return () => {
      siblings.forEach(({ element, inert }) => { element.inert = inert; });
      document.body.style.overflow = overflow; if (previous?.isConnected) previous.focus();
    };
  }, []);
  useEffect(() => {
    if (panel.current && !panel.current.contains(document.activeElement)) panel.current.focus();
  });
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); if (!busy) onClose(); }
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [busy, onClose]);
  return <div className="engine-update-overlay"><section ref={panel} className="engine-update-dialog" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}
    onKeyDown={event => {
      if (event.key === "Tab") {
        const controls = Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], summary, [tabindex="0"]') ?? []).filter(el => el.getClientRects().length > 0).sort((a, b) => a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1);
        const first = controls[0], last = controls.at(-1);
        if (!first) { event.preventDefault(); return; }
        if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && (document.activeElement === last || document.activeElement === panel.current)) { event.preventDefault(); first.focus(); }
      }
    }}><h2>{title}</h2>{children}</section></div>;
}

function warningSummary(value: string): string {
  if (value.startsWith("EXTERNAL_GPU_COMPUTE_PROCESS")) return "Other applications were using the GPU at the last inventory scan. The worker checks again before measurements.";
  if (value.startsWith("GPU_UTILIZATION_BUSY")) return "The GPU is busy. A quiet GPU is required for reliable measurements.";
  if (value.startsWith("CONTEXT_FEASIBILITY_UNPROVEN")) return "The selected context sizes have not been tested yet. Preflight will check whether the model fits; no action is needed while it runs. If a context fails, choose a smaller context and try again.";
  if (value === "NO_BASELINE_EVIDENCE") return "There is no measured baseline to compare against.";
  if (value === "NO_VALIDATED_WINNER") return "No configuration has qualified as a validated winner.";
  return humanEnum(value.split(":")[0] ?? value).slice(0, 200);
}

export function WarningList({ warnings }: { warnings: string[] }) {
  if (!warnings.length) return null;
  const details = warnings.map(value => value.startsWith("EXTERNAL_GPU_COMPUTE_PROCESS") ? "EXTERNAL_GPU_COMPUTE_PROCESS (process arguments omitted)" : (value.split(" --")[0] ?? value).slice(0, 300));
  return <div className="warning-list"><ul>{[...new Set(warnings.map(warningSummary))].map(text => <li key={text}>{text}</li>)}</ul><details><summary>Technical details</summary><ul>{[...new Set(details)].map(text => <li key={text}>{text}</li>)}</ul></details></div>;
}

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
  // Negative/uncertain states take precedence over substrings such as "complete".
  const tone: Tone = normalized.includes("simulat") ? "simulated"
    : /fail|error|infeasible|blocked|not.validated/.test(normalized) ? "danger"
    : /incomplete|inconclusive|ineligible|unavailable|unknown|stale|offline|pause|pending|queued|cancelling/.test(normalized) ? "warn"
    : ["completed", "validated", "online", "ready", "passed", "optimizer online"].includes(normalized) ? "ok"
    : /run|progress|screen|preflight/.test(normalized) ? "info" : "neutral";
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
    <div className={`notice notice-${tone}`} role={tone === "danger" ? "alert" : "status"}>
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
      <strong>{simulated ? "SIMULATED EVIDENCE — NEVER DEPLOYABLE" : warnings.every(value => value.startsWith("CONTEXT_FEASIBILITY_UNPROVEN")) ? "Context check pending" : "Measurement cautions"}</strong>
      <p>
        {simulated
          ? "This experiment used the explicit simulation lane. It can exercise the workflow, but it cannot produce a validated recipe."
          : "These checks explain what is still unproven. They do not by themselves mean the run failed."}
      </p>
      {warnings.length > 0 ? (
        <WarningList warnings={warnings} />
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

export function Tabs<T extends string>({ tabs, value, onChange, children, label = "Views" }: {
  tabs: { value: T; label: string }[]; value: T; onChange: (value: T) => void;
  children: ReactNode; label?: string;
}) {
  const id = useId();
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const active = Math.max(0, tabs.findIndex(tab => tab.value === value));
  return <>
    <div className="tabs" role="tablist" aria-label={label} onKeyDown={event => {
      let index = active;
      if (event.key === "ArrowRight") index = (active + 1) % tabs.length;
      else if (event.key === "ArrowLeft") index = (active - 1 + tabs.length) % tabs.length;
      else if (event.key === "Home") index = 0;
      else if (event.key === "End") index = tabs.length - 1;
      else return;
      event.preventDefault(); onChange(tabs[index]!.value); buttons.current[index]?.focus();
    }}>
      {tabs.map((tab, index) => <button key={tab.value} ref={element => { buttons.current[index] = element; }}
        id={`${id}-${index}`} role="tab" type="button" aria-controls={`${id}-panel`}
        aria-selected={index === active} tabIndex={index === active ? 0 : -1}
        className={`tab ${index === active ? "active" : ""}`} onClick={() => onChange(tab.value)}>{tab.label}</button>)}
    </div>
    <div id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-${active}`} tabIndex={0}>{children}</div>
  </>;
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

export function RefreshButton({ onClick, label = "Refresh page data", disabled = false }: { onClick(): void; label?: string; disabled?: boolean }) {
  return <button type="button" className="icon-button toolbar-icon" aria-label={label} title={label} disabled={disabled} onClick={onClick}><WorkstationIcon name="refresh" /></button>;
}
