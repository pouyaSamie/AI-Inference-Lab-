import { DataRows } from "./DataRows";
import type { ReactNode } from "react";

interface RangePoint {
  label: string;
  value: number;
  lower?: number | null;
  upper?: number | null;
  qualified?: boolean;
}

export function RangeChart({
  points,
  baseline = 1,
  height = 230,
}: {
  points: RangePoint[];
  baseline?: number;
  height?: number;
}) {
  if (points.length === 0) return <div className="chart-empty">No paired scores yet.</div>;
  const total = points.length;
  points = points.slice(0, 40);
  const width = 720;
  const pad = { top: 22, right: 28, bottom: 52, left: 54 };
  const values = points.flatMap((point) => [point.value, point.lower ?? point.value, point.upper ?? point.value]);
  const min = Math.min(baseline, ...values) - 0.04;
  const max = Math.max(baseline, ...values) + 0.04;
  const span = Math.max(0.1, max - min);
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const x = (index: number) =>
    pad.left + (points.length === 1 ? plotWidth / 2 : (index / (points.length - 1)) * plotWidth);
  const y = (value: number) => pad.top + plotHeight - ((value - min) / span) * plotHeight;
  const ticks = Array.from({ length: 5 }, (_, index) => min + (span * index) / 4);

  return (
    <>
    <p className="chart-coverage">{Math.min(total, 40)} of {total} paired scores shown in retained order. {total > 40 ? "Plot limit: 40. All evaluations remain in the paged evidence tables." : "All paired scores shown."}</p>
    <svg className="chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Paired objective ratio by context">
      {ticks.map((tick) => (
        <g key={tick}>
          <line x1={pad.left} x2={width - pad.right} y1={y(tick)} y2={y(tick)} className="chart-grid" />
          <text x={pad.left - 8} y={y(tick) + 4} textAnchor="end" className="chart-tick">
            {tick.toFixed(2)}
          </text>
        </g>
      ))}
      <line x1={pad.left} x2={width - pad.right} y1={y(baseline)} y2={y(baseline)} className="chart-baseline" />
      <text x={width - pad.right} y={y(baseline) - 6} textAnchor="end" className="chart-baseline-label">
        baseline 1.00
      </text>
      {points.map((point, index) => {
        const pointX = x(index);
        const tone = point.qualified ? "var(--ok)" : "var(--muted)";
        return (
          <g key={`${point.label}-${index}`}>
            {point.lower !== null && point.lower !== undefined && point.upper !== null && point.upper !== undefined ? (
              <line x1={pointX} x2={pointX} y1={y(point.lower)} y2={y(point.upper)} stroke={tone} strokeWidth={3} opacity={1} />
            ) : null}
            <circle cx={pointX} cy={y(point.value)} r={6} fill={tone} stroke="var(--surface)" strokeWidth={2} />
            {index % Math.ceil(points.length / 8) === 0 ? <text x={pointX} y={height - pad.bottom + 22} textAnchor="middle" className="chart-label">
              {point.label}
            </text> : null}
            {points.length <= 12 ? <text x={pointX} y={y(point.value) - 12} textAnchor="middle" className="chart-value">
              {point.value.toFixed(3)}
            </text> : null}
          </g>
        );
      })}
    </svg>
    <details className="chart-data"><summary>Paired plot data</summary><div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable data table"><table><thead><tr><th scope="col">Evaluation</th><th scope="col" className="numeric">Ratio</th><th scope="col">Interval</th><th scope="col">Qualification</th></tr></thead>
      <DataRows items={points} columns={4} label="plotted scores">{(point, index) => <tr key={index}><td>{point.label}</td><td className="numeric">{point.value.toFixed(3)}</td><td>{point.lower != null && point.upper != null ? `${point.lower.toFixed(3)}–${point.upper.toFixed(3)}` : "Insufficient evidence"}</td><td>{point.qualified ? "Qualified" : "Not qualified"}</td></tr>}</DataRows>
    </table></div></details>
    </>
  );
}

interface ScatterPoint {
  label: string;
  x: number;
  y: number;
  detail?: string;
  simulated?: boolean;
}

export function ScatterChart({
  points,
  xLabel,
  yLabel,
  height = 280,
}: {
  points: ScatterPoint[];
  xLabel: string;
  yLabel: string;
  height?: number;
}) {
  if (points.length === 0) return <div className="chart-empty">No observations with both metrics yet.</div>;
  const total = points.length;
  points = points.slice(0, 200);
  const width = 720;
  const pad = { top: 22, right: 28, bottom: 58, left: 66 };
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const dx = Math.max(1, Math.max(...xs) - Math.min(...xs)) * 0.08;
  const dy = Math.max(1, Math.max(...ys) - Math.min(...ys)) * 0.08;
  const minX = Math.max(0, Math.min(...xs) - dx);
  const maxX = Math.max(...xs) + dx;
  const minY = Math.max(0, Math.min(...ys) - dy);
  const maxY = Math.max(...ys) + dy;
  const spanX = Math.max(1e-6, maxX - minX);
  const spanY = Math.max(1e-6, maxY - minY);
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const px = (value: number) => pad.left + ((value - minX) / spanX) * plotWidth;
  const py = (value: number) => pad.top + plotHeight - ((value - minY) / spanY) * plotHeight;

  return (
    <>
    <p className="chart-coverage">{Math.min(total, 200)} of {total} matching observations shown in retained order. {total > 200 ? "Plot limit: 200. All records remain in the evidence tables." : "All matching observations shown."} Squares: simulated; circles: real lane.</p>
    <svg className="chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${yLabel} versus ${xLabel}`}>
      {[0, 0.25, 0.5, 0.75, 1].map((fraction) => {
        const yValue = minY + spanY * fraction;
        return (
          <g key={fraction}>
            <line x1={pad.left} x2={width - pad.right} y1={py(yValue)} y2={py(yValue)} className="chart-grid" />
            <text x={pad.left - 8} y={py(yValue) + 4} textAnchor="end" className="chart-tick">
              {yValue.toFixed(1)}
            </text>
          </g>
        );
      })}
      {[0, 0.25, 0.5, 0.75, 1].map(fraction => <text key={fraction} x={pad.left + fraction * plotWidth} y={height - pad.bottom + 18} textAnchor="middle" className="chart-tick">{(minX + fraction * spanX).toFixed(1)}</text>)}
      {points.map((point, index) => (
        <g key={`${point.label}-${index}`}>
          {point.simulated ? <rect x={px(point.x) - 6} y={py(point.y) - 6} width={12} height={12} fill="var(--simulated)" stroke="var(--surface)" strokeWidth={2}><title>{`${point.label} — simulated — ${point.detail ?? ""}`}</title></rect> : <circle
            cx={px(point.x)}
            cy={py(point.y)}
            r={7}
            fill={point.simulated ? "var(--simulated)" : "var(--accent)"}
            stroke="var(--surface)"
            strokeWidth={2}
          >
            <title>{`${point.label}${point.detail ? ` — ${point.detail}` : ""}`}</title>
          </circle>}
          {points.length <= 20 ? <text x={px(point.x)} y={py(point.y) - 12} textAnchor="middle" className="chart-label">
            {point.label}
          </text> : null}
        </g>
      ))}
      <text x={pad.left + plotWidth / 2} y={height - 16} textAnchor="middle" className="chart-axis-label">
        {xLabel}
      </text>
      <text x={16} y={pad.top + plotHeight / 2} textAnchor="middle" transform={`rotate(-90 16 ${pad.top + plotHeight / 2})`} className="chart-axis-label">
        {yLabel}
      </text>
    </svg>
    <details className="chart-data"><summary>Throughput plot data</summary><div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable data table"><table><thead><tr><th scope="col">Trial / provenance</th><th scope="col" className="numeric">{xLabel}</th><th scope="col" className="numeric">{yLabel}</th><th scope="col">Lane</th></tr></thead>
      <DataRows items={points} columns={4} label="plotted observations">{(point, index) => <tr key={index}><td>{point.label}<small>{point.detail}</small></td><td className="numeric">{point.x}</td><td className="numeric">{point.y}</td><td>{point.simulated ? "Simulated" : "Real"}</td></tr>}</DataRows>
    </table></div></details>
    </>
  );
}

export function Bar({ value, max, tone }: { value: number; max: number; tone?: string }) {
  const pct = max <= 0 ? 0 : Math.max(0, Math.min(100, (value / max) * 100));
  return <span className="mini-bar"><span style={{ width: `${pct}%`, background: tone }} /></span>;
}

export function ChartFrame({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="chart-frame">
      <h3 className="subsection-title">{title}</h3>
      {children}
    </div>
  );
}
