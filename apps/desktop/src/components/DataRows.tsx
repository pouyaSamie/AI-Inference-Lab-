import { useId, useMemo, useState, type ReactNode } from "react";

/** Bound DOM work while keeping every retained record reachable. No sampling of evidence. */
export const ROW_PAGE_SIZE = 50;
export function DataRows<T>({ items, columns, label, children, getOrder }: {
  items: readonly T[]; columns: number; label: string;
  children: (item: T, index: number) => ReactNode; getOrder?: (item: T) => number | null | undefined;
}) {
  const [order, setOrder] = useState("retained");
  const [page, setPage] = useState(0);
  const id = useId();
  const ordered = useMemo(() => !getOrder || order === "retained" ? items : [...items].sort((a, b) => {
    const x=getOrder(a), y=getOrder(b);
    if (x == null) return y == null ? 0 : 1;
    if (y == null) return -1;
    return (x-y) * (order === "ascending" ? 1 : -1);
  }), [items, getOrder, order]);
  const last = Math.max(0, Math.ceil(items.length / ROW_PAGE_SIZE) - 1);
  const current = Math.min(page, last);
  const start = current * ROW_PAGE_SIZE;
  return <>
    <tbody id={id}>{ordered.slice(start, start + ROW_PAGE_SIZE).map((item, index) => children(item, start + index))}</tbody>
    {items.length > ROW_PAGE_SIZE || getOrder ? <tfoot><tr><td colSpan={columns}>
      <nav className="data-pagination" aria-label={`${label} pages`}>
        {getOrder ? <label className="field-inline">{label} order<select value={order} onChange={event => {setOrder(event.target.value);setPage(0);}}><option value="retained">Retained order</option><option value="ascending">Ascending</option><option value="descending">Descending</option></select></label> : null}
        <span role="status">{start + 1}–{Math.min(start + ROW_PAGE_SIZE, items.length)} of {items.length} {label}</span>
        <button className="button button-secondary" aria-controls={id} disabled={current === 0} onClick={() => setPage(current - 1)}>Previous</button>
        <button className="button button-secondary" aria-controls={id} disabled={current === last} onClick={() => setPage(current + 1)}>Next</button>
      </nav>
    </td></tr></tfoot> : null}
  </>;
}
