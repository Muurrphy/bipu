import math


def finite(value, name, minimum=0, maximum=3600):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not minimum <= value <= maximum
    ):
        raise ValueError("Invalid " + name)
    return float(value)


def validate_score(document, assets):
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ValueError("Score version must be 1")
    steps = document.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 100:
        raise ValueError("Score needs 1..100 steps")
    result = []
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("Invalid score step")
        motion = step.get("motion")
        if not isinstance(motion, str) or motion not in assets.motions:
            raise ValueError("Unknown score motion")
        gap = finite(step.get("wait_before", 0), "wait_before", maximum=300)
        duration = assets.motions[motion]["duration_s"]
        sounds = []
        cues = step.get("sounds", [])
        if not isinstance(cues, list):
            raise ValueError("Sounds must be an array")
        for cue in cues:
            if not isinstance(cue, dict) or not isinstance(cue.get("id"), str):
                raise ValueError("Invalid sound cue")
            if len(sounds) >= 12:
                raise ValueError("Too many sound cues in one motion")
            ident = cue.get("id")
            at = finite(cue.get("at", 0), "sound offset", maximum=duration)
            assets.validate_sound(motion, ident)
            sounds.append({"id": ident, "at": at})
        previous_end = 0
        for cue in sorted(sounds, key=lambda x: x["at"]):
            end = cue["at"] + assets.by_id[cue["id"]]["duration_s"]
            if cue["at"] < previous_end or end > duration:
                raise ValueError("Sounds must not overlap or extend beyond the motion")
            previous_end = end
        result.append(
            {
                "motion": motion,
                "wait_before": gap,
                "sounds": sorted(sounds, key=lambda x: x["at"]),
            }
        )
    return result
