"""Small geodesy helpers for walking navigation (no dependencies).

Points are (lat, lng) tuples in degrees. Distances are metres. Accurate enough
for walking distances (a few km), which is all navigation needs.
"""
from __future__ import annotations

import math
from typing import Iterable, Optional, Sequence

Point = tuple[float, float]

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(a: Point, b: Point) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def bearing_deg(a: Point, b: Point) -> float:
    """Initial compass bearing from a to b, 0 = north, clockwise, 0..360."""
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlng = math.radians(b[1] - a[1])
    x = math.sin(dlng) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlng)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def offset(p: Point, north_m: float, east_m: float) -> Point:
    """Move a point by metres north/east (flat-earth approximation)."""
    dlat = north_m / EARTH_RADIUS_M
    dlng = east_m / (EARTH_RADIUS_M * math.cos(math.radians(p[0])))
    return (p[0] + math.degrees(dlat), p[1] + math.degrees(dlng))


def _to_xy(origin: Point, p: Point) -> tuple[float, float]:
    """Local flat projection around origin, in metres (x east, y north)."""
    x = math.radians(p[1] - origin[1]) * EARTH_RADIUS_M * math.cos(math.radians(origin[0]))
    y = math.radians(p[0] - origin[0]) * EARTH_RADIUS_M
    return x, y


def distance_to_segment_m(p: Point, a: Point, b: Point) -> float:
    px, py = 0.0, 0.0
    ax, ay = _to_xy(p, a)
    bx, by = _to_xy(p, b)
    dx, dy = bx - ax, by - ay
    seg_len2 = dx * dx + dy * dy
    if seg_len2 == 0:
        return math.hypot(ax - px, ay - py)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(cx - px, cy - py)


def distance_to_path_m(p: Point, path: Sequence[Point]) -> float:
    if not path:
        return math.inf
    if len(path) == 1:
        return haversine_m(p, path[0])
    return min(distance_to_segment_m(p, path[i], path[i + 1]) for i in range(len(path) - 1))


def path_length_m(path: Sequence[Point]) -> float:
    return sum(haversine_m(path[i], path[i + 1]) for i in range(len(path) - 1))


def point_along(path: Sequence[Point], dist_m: float) -> Point:
    """The point dist_m metres along the path (clamped to its ends)."""
    if not path:
        raise ValueError("empty path")
    remaining = max(0.0, dist_m)
    for i in range(len(path) - 1):
        seg = haversine_m(path[i], path[i + 1])
        if remaining <= seg and seg > 0:
            t = remaining / seg
            a, b = path[i], path[i + 1]
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        remaining -= seg
    return path[-1]


def decode_polyline(encoded: str) -> list[Point]:
    """Decode a Google encoded polyline (precision 5)."""
    points: list[Point] = []
    index = lat = lng = 0
    while index < len(encoded):
        for coord in range(2):
            shift = result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if coord == 0:
                lat += delta
            else:
                lng += delta
        points.append((lat / 1e5, lng / 1e5))
    return points


def clock_direction(heading_deg: Optional[float], target_bearing_deg: float) -> Optional[str]:
    """Relative direction as a clock position ("12 o'clock" = straight ahead)."""
    if heading_deg is None:
        return None
    rel = (target_bearing_deg - heading_deg + 360.0) % 360.0
    hour = round(rel / 30.0) % 12
    return f"{12 if hour == 0 else hour} o'clock"


def compass_word(bearing: float) -> str:
    names = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]
    return names[round(bearing / 45.0) % 8]


def spoken_distance(metres: float) -> str:
    """Round a distance the way a person would say it."""
    if metres < 10:
        return "a few metres"
    if metres < 100:
        return f"{int(round(metres / 5.0) * 5)} metres"
    if metres < 1000:
        return f"{int(round(metres / 10.0) * 10)} metres"
    km = round(metres / 1000.0, 1)
    if km == 1:
        return "1 kilometre"
    return f"{km:g} kilometres"


def nearest_index(p: Point, points: Iterable[Point]) -> int:
    best, best_d = 0, math.inf
    for i, q in enumerate(points):
        d = haversine_m(p, q)
        if d < best_d:
            best, best_d = i, d
    return best
