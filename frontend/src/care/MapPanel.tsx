// The care recipient's last phone location on an OpenStreetMap map (Leaflet).
// The location comes from the /me page on their phone, not from the cane.
import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { Location } from "../api";
import { ago } from "./format";

const STALE_MS = 60_000;

export function MapPanel({ location }: { location: Location | null }) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const marker = useRef<L.CircleMarker | null>(null);
  const circle = useRef<L.Circle | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!container.current || map.current) return;
    map.current = L.map(container.current, { zoomControl: true }).setView([43.0096, -81.2737], 13);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map.current);
    return () => {
      map.current?.remove();
      map.current = null;
      marker.current = null;
      circle.current = null;
    };
  }, []);

  const stale = location ? now - new Date(location.ts).getTime() > STALE_MS : true;

  useEffect(() => {
    if (!map.current || !location) return;
    const point: L.LatLngExpression = [location.lat, location.lng];
    const color = stale ? "#888" : "#d33";
    if (!marker.current) {
      marker.current = L.circleMarker(point, { radius: 9, weight: 3, color, fillOpacity: 0.8 }).addTo(
        map.current,
      );
      circle.current = L.circle(point, { radius: location.accuracy ?? 0, color, weight: 1 }).addTo(
        map.current,
      );
      map.current.setView(point, 17);
    } else {
      marker.current.setLatLng(point).setStyle({ color });
      circle.current?.setLatLng(point).setRadius(location.accuracy ?? 0).setStyle({ color });
    }
  }, [location, stale]);

  return (
    <section className="care-card" aria-label="Location">
      <h2>Location</h2>
      <p className={stale ? "hint" : ""}>
        {location
          ? `Phone location updated ${ago(location.ts, now)}` +
            (location.accuracy ? ` (±${Math.round(location.accuracy)} m)` : "") +
            (stale ? ". Not updating: is the /me page open?" : "")
          : "No location yet. Open /me on the user's phone and press Start."}
      </p>
      <div ref={container} className="map" />
    </section>
  );
}
