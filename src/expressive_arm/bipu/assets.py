from __future__ import annotations
import hashlib
import json
from pathlib import Path
from importlib.resources import files
from ..trajectory import catalog, load


class Assets:
    def __init__(self, sound_root=None, videos=None, sound_manifest=None):
        self.root = Path(sound_root).expanduser().resolve() if sound_root else None
        self.videos = {
            k: Path(v).expanduser().resolve() for k, v in (videos or {}).items()
        }
        self.motions = {m["id"]: m for m in catalog()["expressions"]}
        self.sounds = json.loads(
            Path(sound_manifest).expanduser().read_text()
            if sound_manifest
            else files(__package__).joinpath("sounds.json").read_text()
        )
        if not isinstance(self.sounds, list):
            raise ValueError("Sound manifest must be an array")
        ids = set()
        for row in self.sounds:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("id"), str)
                or not row["id"]
                or row["id"] in ids
            ):
                raise ValueError("Invalid or duplicate sound ID")
            ids.add(row["id"])
            if row.get("group") not in (*self.motions, "signature", "backup"):
                raise ValueError("Unknown sound group")
            if not isinstance(row.get("file"), str) or not isinstance(
                row.get("sha256"), str
            ):
                raise ValueError("Sound file and checksum required")
            from .score import finite

            finite(row.get("duration_s"), "sound duration", minimum=0.01, maximum=300)
        self.by_id = {s["id"]: s for s in self.sounds}
        for row in self.sounds:
            row.setdefault("label", row["id"])
            try:
                self.sound_file(row["id"])
                row["available"] = True
            except (ValueError, OSError):
                row["available"] = False
        self.rows = {k: load(k) for k in self.motions}

    def motion_file(self, name):
        if name not in self.motions:
            raise ValueError("Unknown motion")
        return Path(
            str(files("expressive_arm").joinpath("motions", self.motions[name]["file"]))
        )

    def sound_file(self, ident):
        if not self.root or ident not in self.by_id:
            raise ValueError("Sound library not configured")
        row = self.by_id[ident]
        p = (self.root / row["file"]).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError("Sound path escapes library")
        if not p.is_file():
            raise ValueError("Sound file unavailable: " + ident)
        if hashlib.sha256(p.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Sound checksum mismatch: " + ident)
        return p

    def sound_ids(self, motion, last=None):
        choices = []
        for row in self.sounds:
            if row["group"] == motion and row.get("default", True):
                try:
                    self.sound_file(row["id"])
                except (ValueError, OSError):
                    continue
                choices.append(row["id"])
        return [s for s in choices if s != last] if len(choices) > 1 else choices

    def validate_sound(self, motion, ident):
        if ident is None:
            return
        if ident not in self.by_id or self.by_id[ident]["group"] not in (
            motion,
            "signature",
            "backup",
        ):
            raise ValueError("Sound does not belong to this expression")
        self.sound_file(ident)
