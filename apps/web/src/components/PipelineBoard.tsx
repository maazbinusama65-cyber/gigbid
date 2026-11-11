import { Link } from "react-router-dom";
import { money, timeAgo } from "../lib/format";
import type { PipelineBoardT, PipelineCardT } from "../lib/types";
import { EmptyState } from "./States";

function Card({ card }: { card: PipelineCardT }) {
  const href = card.stage === "drafted" ? `/studio/${card.job_id}` : card.thread_id ? `/messages/${card.thread_id}` : null;
  return (
    <li className="kcard" data-testid="pipeline-card" data-job={card.job_id}>
      <h3>{href ? <Link to={href}>{card.title}</Link> : card.title}</h3>
      <div className="meta">{card.client_name}</div>
      <div className="meta">
        {money(card.bid_amount, card.currency)} · {card.connects_spent} Connects
      </div>
      <div className="meta" style={{ marginTop: 4 }}>
        {card.last_event} · {timeAgo(card.updated_at)}
      </div>
    </li>
  );
}

/** Kanban of every proposal. Columns follow the marketplace event stream. */
export function PipelineBoard({ board }: { board: PipelineBoardT }) {
  const total = board.columns.reduce((n, c) => n + c.cards.length, 0);
  if (total === 0) {
    return (
      <EmptyState title="No proposals yet" action={<Link className="btn" to="/">Open the job inbox</Link>}>
        Approved drafts show up here and move right as clients view, reply and hire.
      </EmptyState>
    );
  }
  return (
    <div className="board" data-testid="pipeline-board" role="list" aria-label="Proposal pipeline">
      {board.columns.map((col) => (
        <section key={col.stage} className="col" data-stage={col.stage} data-testid={`col-${col.stage}`} aria-label={`${col.label}, ${col.cards.length} proposals`} role="listitem">
          <div className="col-head">
            <span>{col.label}</span>
            <span>{col.cards.length}</span>
          </div>
          {col.cards.length === 0 ? (
            <p className="col-empty">Nothing here.</p>
          ) : (
            <ul>
              {col.cards.map((c) => (
                <Card key={c.proposal_id} card={c} />
              ))}
            </ul>
          )}
        </section>
      ))}
    </div>
  );
}
