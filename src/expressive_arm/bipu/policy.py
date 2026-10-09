from __future__ import annotations
from dataclasses import dataclass, asdict
import math


@dataclass
class PetState:
    energy: float = 80
    irritation: float = 0
    asleep: bool = False
    last_contact: float = 0
    updated: float = 0
    last_motion: str | None = None
    last_sound: str | None = None
    toys_ready: bool = False

    def __post_init__(self):
        for key, limit in [
            ("energy", 100),
            ("irritation", 3),
            ("last_contact", 1e12),
            ("updated", 1e12),
        ]:
            value = getattr(self, key)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= limit
            ):
                raise ValueError("Invalid saved pet state")
        if not isinstance(self.asleep, bool) or not isinstance(self.toys_ready, bool):
            raise ValueError("Invalid saved pet state")
        if any(
            v is not None and not isinstance(v, str)
            for v in (self.last_motion, self.last_sound)
        ):
            raise ValueError("Invalid saved pet state")

    def advance(self, now):
        if not self.updated:
            self.updated = now
        dt = max(0, min(3600, now - self.updated))
        self.updated = now
        self.irritation = max(0, self.irritation - dt / 180)
        self.energy = max(
            0, min(100, self.energy + dt * (0.06 if self.asleep else -0.012))
        )

    def public(self, now):
        return {
            **asdict(self),
            "idle_seconds": round(max(0, now - self.last_contact), 1),
        }


class Policy:
    def __init__(self, assets, rng, sleep_after=240):
        self.assets, self.rng, self.sleep_after = assets, rng, sleep_after

    def motions(self, state, event, intent, now):
        state.advance(now)
        previous_irritation = state.irritation
        if event["kind"] == "message":
            state.last_contact = now
            if intent != "sleep":
                state.asleep = False
            if intent == "scold":
                state.irritation = min(3, state.irritation + 1)
                return ["angry"] if state.irritation >= 1.8 else ["startled"]
            if intent == "reassure":
                state.irritation = max(0, state.irritation - 1.2)
                return ["hesitant"] if previous_irritation > 0.8 else ["happy"]
            if intent == "praise":
                state.irritation = max(0, state.irritation - 0.5)
                return ["hesitant"] if previous_irritation > 0.8 else ["happy"]
            if intent == "tease":
                return ["startled", "hesitant"]
            if intent == "toy":
                return ["playful"] if state.toys_ready else ["curious"]
            if intent == "sleep":
                return ["sleepy"]
            if intent == "sad":
                return ["disappointed"]
            if intent == "question":
                return ["curious", "hesitant"]
            return ["curious", "hesitant", "wait"]
        idle = max(0, now - state.last_contact)
        if state.asleep:
            return ["wait"]
        if idle >= self.sleep_after or state.energy < 25:
            return ["sleepy"]
        allowed = ["wait", "curious", "hesitant"]
        if state.toys_ready and state.energy > 45:
            allowed.append("playful")
        return allowed

    def options(self, state, motions):
        options = {}
        for motion in motions:
            if motion == "wait":
                options["wait"] = {"motion": "wait", "sound": None}
                continue
            sounds = self.assets.sound_ids(motion, state.last_sound)
            for sound in sounds:
                row = self.assets.by_id[sound]
                options[motion + ":" + sound] = {
                    "motion": motion,
                    "sound": sound,
                    "description": row.get("label", ""),
                }
            # Silence is a valid reaction even when the sound folder is unavailable.
            options[motion + ":silent"] = {"motion": motion, "sound": None}
        return options

    def completed(self, state, motion, sound):
        state.last_motion, state.last_sound = motion, sound
        state.energy = max(
            0, state.energy - {"playful": 9, "happy": 4, "angry": 5}.get(motion, 2)
        )
        if motion == "sleepy":
            state.asleep = True
