"""Names for human recordings, independent of the AI motion catalog."""
from __future__ import annotations

import json
from pathlib import Path

from motion_library import ROOT


def read_repertoire(path: Path = ROOT / "human_repertoire.json") -> dict:
    repertoire = json.loads(path.read_text(encoding="utf-8"))
    labels = set()
    for item in repertoire["expressions"]:
        for label in (item["id"], item["name"], *item.get("aliases", [])):
            if label in labels:
                raise ValueError(f"Duplicate recording label: {label}")
            labels.add(label)
    return repertoire


def find_recording_expression(name: str) -> dict:
    for item in read_repertoire()["expressions"]:
        if name.strip() in (item["id"], item["name"], *item.get("aliases", [])):
            return item
    raise ValueError(f"本轮录制清单中没有这个动作：{name}")


if __name__ == "__main__":
    for index, item in enumerate(read_repertoire()["expressions"], 1):
        print(f"{index:02d}. {item['name']} ({item['id']}) — {item['intent']}")
