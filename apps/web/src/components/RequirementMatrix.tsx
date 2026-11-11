import type { EvidenceRef, FitReport } from "../lib/types";
import { EvidenceHover } from "./EvidenceHover";

/** Requirement -> portfolio evidence matrix. Missing evidence is shown, not hidden. */
export function RequirementMatrix({ fit, evidence }: { fit: FitReport; evidence: EvidenceRef[] }) {
  const byId = new Map(evidence.map((e) => [e.id, e]));
  return (
    <div className="table-wrap">
      <table className="matrix" data-testid="requirement-matrix">
        <caption className="sr-only">Each requirement and the portfolio items that prove it</caption>
        <thead>
          <tr>
            <th scope="col">Requirement</th>
            <th scope="col">Strength</th>
            <th scope="col">Portfolio evidence</th>
          </tr>
        </thead>
        <tbody>
          {fit.matrix.map((row) => {
            const items = row.evidence_ids.map((id) => byId.get(id)).filter((e): e is EvidenceRef => !!e);
            const tone = row.strength >= 0.7 ? "ok" : row.strength >= 0.4 ? "warn" : "bad";
            return (
              <tr key={row.requirement}>
                <th scope="row" style={{ fontWeight: 600, textAlign: "left", padding: "10px 8px" }}>
                  {row.requirement}
                </th>
                <td className="num" style={{ minWidth: 110 }}>
                  {row.strength.toFixed(2)}
                  <div className={`meter ${tone}`} aria-hidden="true" style={{ marginTop: 4 }}>
                    <span style={{ width: `${row.strength * 100}%` }} />
                  </div>
                </td>
                <td>
                  {items.length === 0 ? (
                    <span className="ev-chip missing">No evidence</span>
                  ) : (
                    <span className="chip-row">
                      {items.map((e) => (
                        <EvidenceHover key={e.id} evidence={[e]} heading={e.title} testId="evidence-chip">
                          <span className="ev-chip">
                            <span className="mono">{e.type}</span> {e.title}
                          </span>
                        </EvidenceHover>
                      ))}
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
