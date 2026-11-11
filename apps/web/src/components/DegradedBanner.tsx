import { useHealth } from "../lib/queries";

/** Shown whenever /api/health says the marketplace is unreachable (or the API itself is). */
export function DegradedBanner() {
  const health = useHealth();
  const apiDown = health.isError;
  const marketplaceDown = health.data ? !health.data.marketplace.ok : false;
  if (!apiDown && !marketplaceDown) return null;
  return (
    <div className="banner degraded" role="alert" data-testid="degraded-banner">
      <span>
        <strong>{apiDown ? "Server unreachable." : "Marketplace unavailable."}</strong>{" "}
        {apiDown
          ? "Showing the last data we have. Changes will not save until the connection is back."
          : "You can still read and edit drafts. Approved proposals and replies are queued and sent when it returns."}
      </span>
      <button className="btn sm" onClick={() => void health.refetch()} disabled={health.isFetching}>
        {health.isFetching ? "Checking..." : "Retry now"}
      </button>
    </div>
  );
}
