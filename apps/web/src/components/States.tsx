import type { ReactNode } from "react";
import { ApiError } from "../lib/client";

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="stack" data-testid="loading">
      <span className="sr-only">{label}</span>
      <div className="skeleton" style={{ width: "60%", height: 28 }} />
      <div className="skeleton" style={{ width: "90%" }} />
      <div className="skeleton" style={{ width: "75%" }} />
      <div className="skeleton" style={{ width: "82%" }} />
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="state" data-testid="empty-state">
      <h3>{title}</h3>
      {children ? <p>{children}</p> : null}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : "Something went wrong.";
  const trace = error instanceof ApiError ? error.traceId : null;
  return (
    <div className="state" role="alert" data-testid="error-state">
      <h3>That did not load</h3>
      <p>{message}</p>
      {trace ? (
        <p className="mono muted">
          trace id {trace}
        </p>
      ) : null}
      {onRetry ? (
        <button className="btn" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

/** Render loading / error / content for a react-query result. */
export function Async<T>({
  query,
  children,
  empty,
}: {
  query: { data: T | undefined; isPending: boolean; error: unknown; refetch: () => unknown };
  children: (data: T) => ReactNode;
  empty?: (data: T) => ReactNode | null;
}) {
  if (query.isPending) return <Loading />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (query.data === undefined) return null;
  const e = empty?.(query.data);
  return <>{e ?? children(query.data)}</>;
}
