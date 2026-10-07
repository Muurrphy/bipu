"""Hardware-independent SO-101 motion design, in calibrated degrees.

The gripper always uses 0..100 percent, never degrees. Exporting files does
not connect to hardware. Absolute joint limits are optional offline and
mandatory in the hardware controller.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JOINT_MAP = {
    "pan": "shoulder_pan.pos", "lift": "shoulder_lift.pos",
    "elbow": "elbow_flex.pos", "wrist": "wrist_flex.pos",
    "roll": "wrist_roll.pos", "grip": "gripper.pos",
}
JOINTS = tuple(JOINT_MAP.values())
OFFSET_CAP = {"pan": 15, "lift": 8, "elbow": 12, "wrist": 14, "roll": 20, "grip": 12}
VELOCITY = {joint: (25.0 if joint == "gripper.pos" else 16.0) for joint in JOINTS}
ACCELERATION = {joint: (70.0 if joint == "gripper.pos" else 45.0) for joint in JOINTS}


def read_catalog(path: Path = ROOT / "catalog.json") -> dict:
    catalog = json.loads(path.read_text(encoding="utf-8"))
    ids, names = set(), set()
    for item in catalog["expressions"]:
        if item["id"] in ids or item["name"] in names:
            raise ValueError("Duplicate expression identifier or name")
        ids.add(item["id"]); names.add(item["name"])
        if not item["phases"]:
            raise ValueError(f"No phases for {item['id']}")
        for phase in item["phases"]:
            if not math.isfinite(phase["move_s"]) or phase["move_s"] <= 0:
                raise ValueError("Movement duration must be finite and positive")
            if not math.isfinite(phase["hold_s"]) or phase["hold_s"] < 0:
                raise ValueError("Hold duration must be finite and nonnegative")
            for joint, value in phase["offset"].items():
                if joint not in OFFSET_CAP or not math.isfinite(value) or abs(value) > OFFSET_CAP[joint]:
                    raise ValueError(f"Invalid or excessive offset: {joint}={value}")
    return catalog


def find_expression(catalog: dict, name: str) -> dict:
    for item in catalog["expressions"]:
        if name in (item["id"], item["name"]):
            return item
    raise ValueError(f"Unknown expression: {name}")


def check_pose(pose: dict, limits: dict | None = None) -> dict[str, float]:
    if set(pose) != set(JOINTS):
        raise ValueError("Pose must contain exactly the six SO-101 joint keys")
    clean = {key: float(pose[key]) for key in JOINTS}
    if not all(math.isfinite(value) for value in clean.values()):
        raise ValueError("Pose contains a nonfinite value")
    if not 0 <= clean["gripper.pos"] <= 100:
        raise ValueError("Gripper must be in 0..100 percent")
    if limits:
        for key, value in clean.items():
            if not limits[key][0] <= value <= limits[key][1]:
                raise ValueError(f"Joint outside calibrated limits: {key}={value:.3f}")
    return clean


def compile_motion(catalog: dict, expression: str, neutral: dict, level: str = "light",
                   tempo: float = 1.0, move_gripper: bool = False,
                   limits: dict | None = None) -> dict:
    neutral = check_pose(neutral, limits)
    item = find_expression(catalog, expression)
    if level not in catalog["levels"] or not math.isfinite(tempo) or not 0.5 <= tempo <= 1.5:
        raise ValueError("Invalid level or tempo (allowed tempo: 0.5..1.5)")
    intensity = catalog["levels"][level]
    phases = list(item["phases"]) + [{"label":"回到悬空起始位", "move_s":1.6, "hold_s":0.4, "offset":{}}]
    segments, elapsed, previous = [], 0.0, neutral
    for phase in phases:
        target = dict(neutral)
        for short, value in phase["offset"].items():
            if short == "grip" and not move_gripper:
                continue
            target[JOINT_MAP[short]] += value * intensity
        check_pose(target, limits)
        # Quintic smoothstep peaks: |v| <= 1.875*d/T,
        # |a| <= (10/sqrt(3))*d/T^2. Lengthen, never clip a pose.
        duration = max(phase["move_s"] / tempo,
                       *(1.875 * abs(target[k]-previous[k]) / VELOCITY[k] for k in JOINTS),
                       *(math.sqrt((10/math.sqrt(3))*abs(target[k]-previous[k])/ACCELERATION[k]) for k in JOINTS))
        segments.append({"label":phase["label"], "start":elapsed, "move_s":duration,
                         "hold_s":phase["hold_s"] / tempo, "from":previous, "to":target})
        elapsed += duration + phase["hold_s"] / tempo
        previous = target
    return {"id":item["id"], "name":item["name"], "level":level,
            "units":catalog["units"], "duration_s":elapsed,
            "gripper_enabled":move_gripper, "validation":"offline_design_only",
            "neutral":neutral, "segments":segments}


def compile_pose_motion(start: dict, target: dict, limits: dict,
                        label: str = "整段平滑抬肩", minimum_s: float = 1.0) -> dict:
    """One uninterrupted quintic move; no repeated small-step commands."""
    start, target = check_pose(start, limits), check_pose(target, limits)
    if not math.isfinite(minimum_s) or minimum_s <= 0:
        raise ValueError("Movement duration must be finite and positive")
    duration = max(minimum_s,
                   *(1.875 * abs(target[key] - start[key]) / VELOCITY[key] for key in JOINTS),
                   *(math.sqrt((10 / math.sqrt(3)) * abs(target[key] - start[key]) / ACCELERATION[key])
                     for key in JOINTS))
    return {"id": "lift", "name": label, "neutral": target, "duration_s": duration,
            "segments": [{"label": label, "start": 0.0, "move_s": duration,
                          "hold_s": 0.0, "from": start, "to": target}]}


def sample_motion(motion: dict, timestamp: float) -> tuple[dict[str, float], str]:
    if not math.isfinite(timestamp):
        raise ValueError("Timestamp must be finite")
    for segment in motion["segments"]:
        end = segment["start"] + segment["move_s"] + segment["hold_s"]
        if timestamp <= end:
            alpha = min(1.0, max(0.0, (timestamp-segment["start"])/segment["move_s"]))
            smooth = alpha**3 * (10 + alpha * (-15 + 6*alpha))
            return ({key: segment["from"][key] + (segment["to"][key]-segment["from"][key])*smooth
                     for key in JOINTS}, segment["label"])
    return dict(motion["neutral"]), "完成；保持力矩"


def export_motion(motion: dict, destination: Path, fps: float = 60.0) -> None:
    if not math.isfinite(fps) or not 1 <= fps <= 120:
        raise ValueError("FPS must be in 1..120")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as stream:
        for frame in range(math.ceil(motion["duration_s"]*fps)+1):
            timestamp = min(frame/fps, motion["duration_s"])
            action, label = sample_motion(motion, timestamp)
            stream.write(json.dumps({"frame":frame,"t":timestamp,"action":action,"phase":label,
                                     "validation":"offline_design_only"},ensure_ascii=False)+"\n")
    destination.with_suffix(".meta.json").write_text(json.dumps(motion,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Design/export expression trajectories without hardware")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    export = sub.add_parser("export")
    export.add_argument("expression", help="English identifier, Chinese name, or all")
    export.add_argument("--level", choices=["light","medium","strong","all"], default="all")
    export.add_argument("--neutral", type=Path)
    export.add_argument("--output", type=Path, default=ROOT/"exports")
    export.add_argument("--with-gripper", action="store_true")
    args = parser.parse_args()
    catalog = read_catalog()
    if args.command == "list":
        for item in catalog["expressions"]:
            print(f"{item['id']:16} {item['name']}：{item['motion']}")
        return
    neutral = json.loads(args.neutral.read_text(encoding="utf-8")) if args.neutral else catalog["reference_pose"]
    expressions = catalog["expressions"] if args.expression == "all" else [find_expression(catalog,args.expression)]
    levels = catalog["levels"] if args.level == "all" else [args.level]
    for item in expressions:
        for level in levels:
            motion = compile_motion(catalog,item["id"],neutral,level,move_gripper=args.with_gripper)
            path = args.output/f"{item['id']}_{level}.jsonl"
            export_motion(motion,path)
            print(f"EXPORTED {item['name']} {level} {motion['duration_s']:.2f}s {path}")


if __name__ == "__main__":
    main()
