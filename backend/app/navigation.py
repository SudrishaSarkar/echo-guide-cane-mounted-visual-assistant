"""Real-time walking navigation driven by the phone's GPS (Person 3).

Flow: the voice assistant (assistant.py) or POST /api/nav/start asks for a
destination -> maps.py finds the place and a walking route -> every location
fix from the /me phone page (care.set_location) is fed to Navigator.on_location,
which speaks turn-by-turn guidance:

    start      "Starting directions to Shoppers Drug Mart. 450 metres, about 6 minutes..."
    prepare    "In 40 metres, turn left onto King Street."
    turn now   "Now, turn left onto King Street."
    reassure   "Continue. Turn left in 120 metres."  (if nothing said for a while)
    off route  "You may be off the route. Finding a new route." -> re-routes
    arrive     "You have arrived near Shoppers Drug Mart... at your 2 o'clock."

Directions use clock positions when the phone reports a compass heading.
GPS is only accurate to ~5-15 m, so guidance is phrased as approximate and
never says a path or crossing is safe: the cane and the user's own judgement
come first.

Speech goes to the cane earbuds (hooks.say -> audio.say) and to the /me phone
(SessionState.phone_say / phone_say_id). Navigation progress is published as
SessionState.nav for the dashboard map.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import care, geo, hooks, maps
from .geo import Point, spoken_distance

log = logging.getLogger("echoguide.navigation")

PREPARE_M = 40.0          # "In 40 metres, turn left"
TURN_NOW_M = 12.0         # "Now, turn left"
ARRIVE_M = 15.0           # destination reached
OFF_ROUTE_M = 35.0        # further than this (+ GPS accuracy) from the route
OFF_ROUTE_FIXES = 2       # consecutive off-route fixes before re-routing
REROUTE_COOLDOWN_S = 20.0
REASSURE_S = 45.0         # say something if silent this long
LOST_FIX_S = 25.0         # warn if the phone stops sending locations
MAX_ACCURACY_M = 30.0     # cap how much a bad fix widens the thresholds
MAX_ROUTE_M = 8000.0      # refuse walking routes longer than this


class NavError(Exception):
    """A failure whose message is safe to speak to the user."""


# Speech to both outputs -------------------------------------------------------

_say_lock = threading.Lock()
_say_id = 0


def speak(text: str) -> None:
    """Say text on the cane (earbuds) and on the /me phone."""
    global _say_id
    with _say_lock:
        _say_id += 1
        n = _say_id
    hooks.say(text)
    hooks.update_state(phone_say=text, phone_say_id=n)


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


class Navigator:
    def __init__(
        self,
        provider: Callable[[], maps.MapsProvider] = maps.get_provider,
        clock: Callable[[], float] = time.monotonic,
        say: Callable[[str], None] = speak,
        publish: Optional[Callable[[dict], None]] = None,
        run_async: Optional[Callable[[Callable[[], None]], None]] = None,
        location: Callable[[], Optional[dict]] = care.latest_location,
    ) -> None:
        self._provider = provider
        self._clock = clock
        self._say = say
        self._publish = publish or (lambda snap: hooks.update_state(nav=snap))
        self._run_async = run_async or (
            lambda fn: threading.Thread(target=fn, daemon=True, name="echoguide-reroute").start()
        )
        self._location = location
        self._lock = threading.RLock()
        self._reset()

    def _reset(self) -> None:
        self.status = "idle"          # idle | routing | navigating | arrived | error
        self.route: Optional[maps.Route] = None
        self.step = 0
        self.prepared = False         # announced "In N metres" for the current step's end
        self.off_count = 0
        self.rerouting = False
        self.last_reroute = -1e9
        self.last_spoken = 0.0
        self.last_fix_at: Optional[float] = None
        self.lost_warned = False
        self.heading: Optional[float] = None
        self.position: Optional[Point] = None
        self.message = ""
        self.generation = 0

    # Public API ---------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self.status in ("routing", "navigating")

    def start(self, query: str, nearest: bool = False) -> str:
        """Find `query`, route to it and start guidance. Returns what was spoken."""
        query = query.strip()
        if not query:
            raise NavError("Where would you like to go?")
        fix = self._location()
        if not fix:
            raise NavError(
                "I don't know where you are yet. On your phone, open EchoGuide and press Start."
            )
        origin = (fix["lat"], fix["lng"])
        with self._lock:
            self.generation += 1
            gen = self.generation
            self.status = "routing"
            self.heading = fix.get("heading", self.heading)
            self._emit()
        try:
            provider = self._provider()
            place = provider.find_place(query, origin, nearest)
            route = provider.walking_route(origin, place)
        except maps.MapsError as exc:
            self._fail(gen, str(exc))
            raise NavError(str(exc)) from exc
        except Exception as exc:
            log.exception("route lookup failed")
            self._fail(gen, "Something went wrong finding a route.")
            raise NavError("Something went wrong finding a route.") from exc
        if route.distance_m > MAX_ROUTE_M:
            msg = (
                f"{place.name} is {spoken_distance(route.distance_m)} away. "
                "That's too far for me to guide you on foot."
            )
            self._fail(gen, msg)
            raise NavError(msg)

        with self._lock:
            if gen != self.generation:  # stopped or replaced while looking up
                raise NavError("Navigation was cancelled.")
            self.route = route
            self.step = 0
            self.prepared = False
            self.off_count = 0
            self.position = origin
            self.last_fix_at = self._clock()
            self.lost_warned = False
            self.status = "navigating"
            minutes = max(1, round(route.duration_s / 60))
            text = (
                f"Starting directions to {place.name}. "
                f"{spoken_distance(route.distance_m).capitalize()}, about {minutes} "
                f"minute{'s' if minutes != 1 else ''} walking. "
                "Directions are approximate, so keep using your cane. "
                + self._first_instruction(origin)
            )
            self._announce(text)
            return text

    def stop(self, announce: bool = True) -> None:
        with self._lock:
            was_active = self.active
            self.generation += 1
            self._reset_route()
            self.status = "idle"
            if announce and was_active:
                self._announce("Navigation stopped.")
            else:
                self._emit()

    def repeat(self) -> str:
        with self._lock:
            if not self.route or self.status != "navigating":
                text = self.message or "You're not navigating anywhere right now."
            else:
                text = self._next_phrase(self.position)
            self._announce(text)
            return text

    def status_sentence(self) -> str:
        with self._lock:
            if self.route and self.status == "arrived":
                return f"You've arrived near {self.route.destination.name}."
            if not self.route or self.status != "navigating":
                return "You're not navigating anywhere right now."
            remaining = self._remaining_m(self.position)
            return (
                f"You're heading to {self.route.destination.name}, "
                f"about {spoken_distance(remaining)} to go. {self._next_phrase(self.position)}"
            )

    def on_location(self, fix: dict) -> None:
        """Feed one GPS fix {lat, lng, accuracy, heading?}. Called for every phone update."""
        with self._lock:
            if fix.get("heading") is not None:
                self.heading = float(fix["heading"])
            if self.status != "navigating" or not self.route:
                return
            p: Point = (float(fix["lat"]), float(fix["lng"]))
            acc = min(float(fix.get("accuracy") or 10.0), MAX_ACCURACY_M)
            self.position = p
            self.last_fix_at = self._clock()
            self.lost_warned = False
            route = self.route

            # Arrived?
            to_dest = geo.haversine_m(p, route.destination.location)
            if to_dest <= ARRIVE_M + acc * 0.5:
                self._arrive(p, to_dest)
                return

            # Off route?
            remaining_path = [q for s in route.steps[self.step:] for q in s.path]
            off_by = geo.distance_to_path_m(p, remaining_path)
            if off_by > OFF_ROUTE_M + acc:
                self.off_count += 1
                if self.off_count >= OFF_ROUTE_FIXES:
                    self._maybe_reroute(p)
                self._emit()
                return
            self.off_count = 0

            # Skip ahead if GPS shows we're already on a later step.
            self._catch_up(p)

            step = route.steps[self.step]
            to_turn = geo.haversine_m(p, step.end)
            has_next = self.step + 1 < len(route.steps)

            if has_next and to_turn <= TURN_NOW_M + acc * 0.5:
                self.step += 1
                self.prepared = False
                text = "Now, " + _lower_first(_sentence(route.steps[self.step].instruction))
                text += self._then_hint()
                self._announce(text)
                return

            if has_next and not self.prepared and to_turn <= PREPARE_M:
                self.prepared = True
                nxt = route.steps[self.step + 1].instruction
                self._announce(f"In {spoken_distance(to_turn)}, {_lower_first(_sentence(nxt))}")
                return

            if self._clock() - self.last_spoken >= REASSURE_S:
                self._announce("Continue. " + self._next_phrase(p))
                return
            self._emit()

    def tick(self) -> None:
        """Call every second or so: warns if the phone stops sending locations."""
        with self._lock:
            if self.status != "navigating" or self.last_fix_at is None or self.lost_warned:
                return
            if self._clock() - self.last_fix_at > LOST_FIX_S:
                self.lost_warned = True
                self._announce(
                    "I've lost your location. Keep the EchoGuide page open on your phone. "
                    "Stop and use your cane until directions come back."
                )

    def snapshot(self) -> dict:
        with self._lock:
            route = self.route
            snap: dict[str, Any] = {
                "status": self.status,
                "destination": None,
                "step_index": self.step,
                "steps_total": len(route.steps) if route else 0,
                "next_instruction": None,
                "distance_to_next_m": None,
                "remaining_m": None,
                "duration_s": route.duration_s if route else None,
                "path": [[round(a, 6), round(b, 6)] for a, b in route.path] if route else [],
                "off_route": self.off_count >= OFF_ROUTE_FIXES,
                "message": self.message,
                "demo_maps": maps.using_fake(),
            }
            if route:
                d = route.destination
                snap["destination"] = {
                    "name": d.name, "address": d.address, "lat": d.location[0], "lng": d.location[1],
                }
                if self.status == "navigating":
                    p = self.position or route.steps[0].start
                    step = route.steps[self.step]
                    nxt = route.steps[self.step + 1] if self.step + 1 < len(route.steps) else None
                    snap["next_instruction"] = nxt.instruction if nxt else f"Arrive at {d.name}"
                    snap["distance_to_next_m"] = round(
                        geo.haversine_m(p, step.end if nxt else d.location)
                    )
                    snap["remaining_m"] = round(self._remaining_m(p))
            return snap

    # Internals ----------------------------------------------------------------

    def _reset_route(self) -> None:
        self.route = None
        self.step = 0
        self.prepared = False
        self.off_count = 0
        self.rerouting = False
        self.last_fix_at = None

    def _announce(self, text: str) -> None:
        self.message = text
        self.last_spoken = self._clock()
        self._emit()
        try:
            self._say(text)
        except Exception:
            log.exception("speak failed")

    def _emit(self) -> None:
        try:
            self._publish(self.snapshot())
        except Exception:
            log.exception("publishing nav state failed")

    def _fail(self, gen: int, message: str) -> None:
        with self._lock:
            if gen == self.generation:
                self._reset_route()
                self.status = "error"
                self.message = message
                self._emit()

    def _first_instruction(self, origin: Point) -> str:
        assert self.route is not None
        step = self.route.steps[0]
        text = _sentence(step.instruction)
        target = step.path[1] if len(step.path) > 1 else step.end
        clock = geo.clock_direction(self.heading, geo.bearing_deg(origin, target))
        if clock and clock not in ("12 o'clock", "11 o'clock", "1 o'clock"):
            text = f"Turn to face your {clock}. Then {_lower_first(text)}"
        return text + self._then_hint()

    def _then_hint(self) -> str:
        """For a short step, warn about the following turn straight away."""
        assert self.route is not None
        steps = self.route.steps
        if self.step + 1 < len(steps) and steps[self.step].distance_m < PREPARE_M + 10:
            self.prepared = True
            nxt = steps[self.step + 1].instruction
            return f" Then, in {spoken_distance(steps[self.step].distance_m)}, {_lower_first(_sentence(nxt))}"
        return ""

    def _next_phrase(self, p: Optional[Point]) -> str:
        assert self.route is not None
        p = p or self.route.steps[0].start
        steps = self.route.steps
        if self.step + 1 < len(steps):
            d = geo.haversine_m(p, steps[self.step].end)
            return f"{_sentence(steps[self.step + 1].instruction)[:-1]} in {spoken_distance(d)}."
        d = geo.haversine_m(p, self.route.destination.location)
        return f"{self.route.destination.name} is about {spoken_distance(d)} ahead."

    def _remaining_m(self, p: Optional[Point]) -> float:
        assert self.route is not None
        steps = self.route.steps
        p = p or steps[0].start
        return geo.haversine_m(p, steps[self.step].end) + sum(s.distance_m for s in steps[self.step + 1:])

    def _catch_up(self, p: Point) -> None:
        assert self.route is not None
        steps = self.route.steps
        current = geo.distance_to_path_m(p, steps[self.step].path)
        best, best_d = self.step, current
        for k in range(self.step + 1, len(steps)):
            d = geo.distance_to_path_m(p, steps[k].path)
            if d < best_d:
                best, best_d = k, d
        if best > self.step and best_d < OFF_ROUTE_M and best_d < current - 5:
            self.step = best
            self.prepared = False

    def _arrive(self, p: Point, to_dest: float) -> None:
        assert self.route is not None
        dest = self.route.destination
        clock = geo.clock_direction(self.heading, geo.bearing_deg(p, dest.location))
        where = f", at about your {clock}" if clock else ""
        self.status = "arrived"
        self.position = p
        self._announce(
            f"You have arrived near {dest.name}. It should be within about "
            f"{spoken_distance(max(to_dest, 10))}{where}. Use your cane to find the entrance."
        )

    def _maybe_reroute(self, p: Point) -> None:
        now = self._clock()
        if self.rerouting or now - self.last_reroute < REROUTE_COOLDOWN_S or not self.route:
            return
        self.rerouting = True
        self.last_reroute = now
        gen = self.generation
        dest = self.route.destination
        self._announce("You may be off the route. Stop for a moment while I find a new route.")

        def work() -> None:
            try:
                route = self._provider().walking_route(p, dest)
            except Exception as exc:
                log.warning("re-route failed: %s", exc)
                with self._lock:
                    if gen == self.generation:
                        self.rerouting = False
                        self._announce("I couldn't find a new route. Try going back the way you came.")
                return
            with self._lock:
                if gen != self.generation or self.status != "navigating":
                    return
                self.route = route
                self.step = 0
                self.prepared = False
                self.off_count = 0
                self.rerouting = False
                self._announce("New route ready. " + self._first_instruction(p))

        self._run_async(work)


# Module singleton + routes -----------------------------------------------------

_navigator: Optional[Navigator] = None


def get_navigator() -> Navigator:
    global _navigator
    if _navigator is None:
        _navigator = Navigator()
    return _navigator


def set_navigator(nav: Optional[Navigator]) -> None:
    global _navigator
    _navigator = nav


def _on_location(fix: dict) -> None:
    get_navigator().on_location(fix)


def register() -> None:
    """Feed phone location fixes into the navigator."""
    if _on_location not in care.location_listeners:
        care.location_listeners.append(_on_location)
    get_navigator()._emit()


ACTIONS: dict[str, Callable[[], Any]] = {
    "NAV_REPEAT": lambda: get_navigator().repeat(),
    "NAV_STOP": lambda: get_navigator().stop(),
}


class StartBody(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    nearest: bool = False


router = APIRouter()


@router.get("/api/nav")
def api_nav() -> dict:
    return get_navigator().snapshot()


@router.post("/api/nav/start")
def api_nav_start(body: StartBody) -> dict:
    try:
        text = get_navigator().start(body.query, body.nearest)
    except NavError as exc:
        speak(str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"spoken": text, "nav": get_navigator().snapshot()}


@router.post("/api/nav/stop")
def api_nav_stop() -> dict:
    get_navigator().stop()
    return get_navigator().snapshot()


@router.post("/api/nav/repeat")
def api_nav_repeat() -> dict:
    return {"spoken": get_navigator().repeat()}
