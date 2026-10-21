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
              <line x1={pointX} x2={pointX} y1={y(point.lower)} y2={y(point.upper)} stroke={tone} strokeWidth={3} opacity={0.45} />
            ) : null}
            <circle cx={pointX} cy={y(point.value)} r={6} fill={tone} stroke="var(--surface)" strokeWidth={2} />
            <text x={pointX} y={height - pad.bottom + 22} textAnchor="middle" className="chart-label">
              {point.label}
            </text>
            <text x={pointX} y={y(point.value) - 12} textAnchor="middle" className="chart-value">
              {point.value.toFixed(3)}
            </text>
          </g>
        );
      })}
    </svg>
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
  const width = 720;
  const pad = { top: 22, right: 28, bottom: 58, left: 66 };
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = Math.max(1e-6, maxX - minX);
  const spanY = Math.max(1e-6, maxY - minY);
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const px = (value: number) => pad.left + ((value - minX) / spanX) * plotWidth;
  const py = (value: number) => pad.top + plotHeight - ((value - minY) / spanY) * plotHeight;

  return (
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
      {points.map((point, index) => (
        <g key={`${point.label}-${index}`}>
          <circle
            cx={px(point.x)}
            cy={py(point.y)}
            r={7}
            fill={point.simulated ? "var(--simulated)" : "var(--accent)"}
            stroke="var(--surface)"
            strokeWidth={2}
          >
            <title>{`${point.label}${point.detail ? ` — ${point.detail}` : ""}`}</title>
          </circle>
          <text x={px(point.x)} y={py(point.y) - 12} textAnchor="middle" className="chart-label">
            {point.label}
          </text>
        </g>
      ))}
      <text x={pad.left + plotWidth / 2} y={height - 16} textAnchor="middle" className="chart-axis-label">
        {xLabel}
      </text>
      <text x={16} y={pad.top + plotHeight / 2} textAnchor="middle" transform={`rotate(-90 16 ${pad.top + plotHeight / 2})`} className="chart-axis-label">
        {yLabel}
      </text>
    </svg>
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
