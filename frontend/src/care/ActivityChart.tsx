// Moving minutes per hour for the last 12 hours (plain SVG bars).
import type { Activity } from "../api";
import { ago } from "./format";

const W = 360;
const H = 120;
const PAD = 18;
const TOP = 8; // room above the chart so the "60" label isn't clipped

function hourLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric" });
}

export function ActivityChart({ activity }: { activity: Activity | null }) {
  // The backend sends {} until it has accelerometer history, so check the
  // fields we use, not just null.
  if (!activity || !Array.isArray(activity.hourly)) {
    return (
      <section className="care-card" aria-label="Activity">
        <h2>Activity</h2>
        <p className="hint">No accelerometer data yet.</p>
      </section>
    );
  }
  const bars = activity.hourly;
  const barW = (W - PAD) / Math.max(bars.length, 1);
  const summary =
    `${activity.moving_minutes_last_hour} moving minutes in the last hour. ` +
    `Last movement ${ago(activity.last_motion_ts)}.`;

  return (
    <section className="care-card" aria-label="Activity">
      <h2>Activity</h2>
      <p>{summary}</p>
      <svg viewBox={`0 -${TOP} ${W} ${H + PAD + TOP}`} className="activity-chart" role="img" aria-label={summary}>
        {[0, 30, 60].map((m) => (
          <g key={m}>
            <line x1={PAD} x2={W} y1={H - (m / 60) * H} y2={H - (m / 60) * H} className="grid" />
            <text x={0} y={H - (m / 60) * H + 4} className="axis">
              {m}
            </text>
          </g>
        ))}
        {bars.map((bar, i) => {
          const h = (Math.min(bar.moving_minutes, 60) / 60) * H;
          return (
            <g key={bar.hour_start}>
              <rect x={PAD + i * barW + 2} y={H - h} width={barW - 4} height={h} className="bar">
                <title>
                  {hourLabel(bar.hour_start)}: {bar.moving_minutes} min
                </title>
              </rect>
              {i % 3 === 0 && (
                <text x={PAD + i * barW + 2} y={H + 14} className="axis">
                  {hourLabel(bar.hour_start)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </section>
  );
}
