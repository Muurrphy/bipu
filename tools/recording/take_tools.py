"""Inspect full human takes, cut explicit reviewed bounds, archive on approval."""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

from controller import atomic_json, BODY_JOINTS
from human_controller import load_clip
from motion_library import ROOT
from human_repertoire import find_recording_expression

PENDING = ROOT / "人工编舞" / "候选片段"
ARCHIVE = ROOT / "人工编舞" / "已确认"


def inspect_take(path: Path, tail_s=90.0, bin_s=.5):
    rows, times = load_clip(path)
    cutoff = max(times[0], times[-1]-tail_s)
    bins = []
    bucket = []
    begin = None
    for row in rows:
        if row["t"] < cutoff: continue
        if begin is None: begin = row["t"]
        if row["t"]-begin >= bin_s and bucket:
            bins.append(summarize(bucket)); bucket = []; begin = row["t"]
        bucket.append(row)
    if bucket: bins.append(summarize(bucket))
    return {"source": str(path), "duration_s": times[-1]-times[0], "frames": len(rows),
            "tail_s": tail_s, "bins": bins,
            "selection": "候选边界需结合末尾重复及归位动作判断，未自动选定"}


def summarize(rows):
    key = "observed" if "observed" in rows[0] else "action"
    return {"start": round(rows[0]["t"], 3), "end": round(rows[-1]["t"], 3),
            "pose": {joint: round(rows[-1][key][joint], 2) for joint in BODY_JOINTS},
            "span_deg": {joint: round(max(row[key][joint] for row in rows)-min(row[key][joint] for row in rows), 2) for joint in BODY_JOINTS}}


def cut_take(source: Path, expression: str, start: float, end: float, park_start: float,
             destination: Path | None = None):
    item = find_recording_expression(expression)
    rows, times = load_clip(source)
    if not times[0] <= start < end <= park_start <= times[-1]:
        raise ValueError("边界须满足：录制起点 <= 动作开始 < 动作结束 <= 落桌归位开始 <= 录制终点")
    selected = [row for row in rows if start <= row["t"] <= end]
    if len(selected) < 2: raise ValueError("选段不足两帧")
    path = destination or PENDING / f"{item['id']}_{datetime.now():%Y%m%d_%H%M%S_%f}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    zero = selected[0]["t"]
    with path.open("x", encoding="utf-8") as stream:
        for frame, row in enumerate(selected):
            result = dict(row, frame=frame, t=row["t"]-zero, original_t=row["t"])
            stream.write(json.dumps(result, ensure_ascii=False, separators=(",", ":"))+"\n")
    atomic_json(path.with_suffix(".meta.json"), {
        "status": "awaiting_user_review", "expression": item["id"], "name": item["name"],
        "source": str(source.resolve()), "requested_start": start, "requested_end": end,
        "actual_start": selected[0]["t"], "actual_end": selected[-1]["t"],
        "park_start": park_start, "parking_excluded": True, "frames": len(selected),
        "duration_s": selected[-1]["t"]-zero, "shape_edits": "none; original timing preserved"})
    return path


def archive_clip(source: Path, confirmed=False):
    if not confirmed: raise ValueError("回放得到用户明确确认后，才能将候选片段存入已确认目录")
    metadata = json.loads(source.with_suffix(".meta.json").read_text(encoding="utf-8"))
    if not metadata.get("parking_excluded"): raise ValueError("没有排除最后落桌归位的记录")
    rows, times = load_clip(source)
    destination = ARCHIVE / metadata["expression"] / f"{datetime.now():%Y%m%d_%H%M%S_%f}"
    destination.mkdir(parents=True, exist_ok=False)
    path = destination / "motion.jsonl"
    shutil.copyfile(source, path)
    metadata.update({"status": "user_confirmed", "confirmed_at": datetime.now().isoformat(),
                     "candidate": str(source.resolve()), "frames": len(rows), "duration_s": times[-1]-times[0]})
    atomic_json(destination / "metadata.json", metadata)
    return path


def main():
    parser = argparse.ArgumentParser(description="Human take inspection, explicit cuts and approved archive")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect"); inspect.add_argument("source", type=Path)
    inspect.add_argument("--tail", type=float, default=90); inspect.add_argument("--bin", type=float, default=.5)
    cut = sub.add_parser("cut"); cut.add_argument("source", type=Path); cut.add_argument("expression")
    for name in ("start", "end", "park-start"): cut.add_argument("--"+name, type=float, required=True)
    archive = sub.add_parser("archive"); archive.add_argument("source", type=Path)
    archive.add_argument("--confirmed", action="store_true")
    args = parser.parse_args()
    if args.command == "inspect": print(json.dumps(inspect_take(args.source, args.tail, args.bin), ensure_ascii=False, indent=2))
    elif args.command == "cut": print(cut_take(args.source, args.expression, args.start, args.end, args.park_start))
    else: print(archive_clip(args.source, args.confirmed))


if __name__ == "__main__": main()
