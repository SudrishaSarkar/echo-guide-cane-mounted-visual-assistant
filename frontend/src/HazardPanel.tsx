import type { Hazard, HazardSide } from "./api";

const SIDES: HazardSide[] = ["left", "center", "right"];

function hazardFor(hazards: Hazard[], side: HazardSide): Hazard | undefined {
  return hazards.find((h) => h.side === side);
}

/** P1 panel: current approaching-object hazards per side + last alert. */
export function HazardPanel({
  hazards,
  warning,
}: {
  hazards: Hazard[];
  warning: string;
}) {
  return (
    <section className="panel">
      <h2>Hazards</h2>
      <div className="hazard-grid">
        {SIDES.map((side) => {
          const h = hazardFor(hazards, side);
          const closeness = h ? Math.round(h.closeness * 100) : 0;
          return (
            <div
              key={side}
              className={`hazard-card ${h ? "hazard-active" : ""}`}
            >
              <div className="hazard-side">{side}</div>
              <div className="hazard-label">{h ? h.label : "—"}</div>
              <div className="hazard-bar">
                <div
                  className="hazard-fill"
                  style={{ width: `${closeness}%` }}
                />
              </div>
              <div className="hazard-meta">
                {h?.approaching ? "approaching" : closeness > 0 ? "close" : ""}
              </div>
            </div>
          );
        })}
      </div>
      <div className="status-row">
        <span className="status-label">Last alert</span>
        <span className="status-value status-warning">{warning || "none"}</span>
      </div>
    </section>
  );
}
