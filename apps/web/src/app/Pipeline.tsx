import { PipelineBoard } from "../components/PipelineBoard";
import { Async } from "../components/States";
import { timeAgo } from "../lib/format";
import { usePipeline } from "../lib/queries";

export default function Pipeline() {
  const q = usePipeline();
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Pipeline</p>
          <h1>Every proposal, from draft to hired</h1>
          <p className="lede">Cards move when the marketplace reports a view, reply, interview or decision.</p>
        </div>
        <button className="btn sm" onClick={() => void q.refetch()} disabled={q.isFetching}>
          {q.isFetching ? "Refreshing…" : "Refresh"}
        </button>
      </header>
      <Async query={q}>
        {(board) => (
          <>
            {board.marketplace_degraded ? (
              <p className="callout" role="status">
                Marketplace is unavailable, so these columns may be out of date.
              </p>
            ) : null}
            <PipelineBoard board={board} />
            {board.recent_events.length ? (
              <section className="panel soft" style={{ marginTop: 24 }} aria-labelledby="ev-h">
                <h2 id="ev-h">Latest marketplace events</h2>
                <ul className="ul" data-testid="event-feed">
                  {board.recent_events.map((e) => (
                    <li key={e.event_id}>
                      <span className="mono">{e.type}</span> · {e.summary} <span className="muted">({timeAgo(e.ts)})</span>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </>
        )}
      </Async>
    </div>
  );
}
