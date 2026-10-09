from __future__ import annotations
import json
import os
import time
import threading
import uuid
import subprocess
import shutil
from pathlib import Path


class PreviewBackend:
    kind = "preview"

    def allowed_motions(self, motions):
        return motions

    def validate_score(self, steps):
        pass

    def prepare(self, motion, cancel):
        if cancel.is_set():
            raise InterruptedError()

    def play(self, motion, duration, cancel, on_started):
        on_started()
        if cancel.wait(duration):
            raise InterruptedError()

    def stop(self):
        pass

    def close(self):
        pass


class ControllerBackend:
    """Connects only to an explicitly running controller. Never opens serial itself."""

    kind = "hardware"

    def __init__(self, runtime, assets, approved_transitions):
        import fcntl

        self.root = Path(runtime).resolve()
        self.assets = assets
        self.transitions = set(approved_transitions)
        self.current = "START"
        self.command_id = None
        self.lock = threading.RLock()
        self.pending = set()
        self.active = False
        if not self.root.is_dir():
            raise ValueError("Controller runtime folder does not exist")
        self.owner = (self.root / "bipu-adapter.lock").open("a")
        try:
            fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            self.owner.close()
            raise RuntimeError("Another Bipu hardware adapter is active")
        try:
            state = self.state()
            if state["mode"] != "hold":
                raise RuntimeError(
                    "Controller must already be holding before attachment"
                )
        except Exception:
            self.owner.close()
            raise

    def state(self):
        s = json.loads((self.root / "state.json").read_text())
        age = time.time() - s["heartbeat"]
        if not -1 <= age <= 3:
            raise RuntimeError("Controller heartbeat expired")
        if (
            s.get("controller_protocol") != 2
            or s.get("session_kind") != "human_choreography"
        ):
            raise RuntimeError("Unsupported controller protocol")
        if s.get("mode") in ("closed_torque_retained", "startup_failed"):
            raise RuntimeError("Controller is closed")
        os.kill(s["pid"], 0)
        return s

    def issue(self, command, cancel=None):
        with self.lock:
            if cancel is not None and cancel.is_set():
                raise InterruptedError()
            state = self.state()
            if command["command"] != "hold" and (
                state.get("faulted") or state["mode"] != "hold"
            ):
                raise RuntimeError("Controller is busy or faulted")
            ident = f"{time.time_ns()}_bipu_{uuid.uuid4().hex[:8]}"
            p = self.root / "inbox" / (ident + ".json")
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps({**command, "created_at": time.time()}))
            os.replace(tmp, p)
            self.pending = {q for q in self.pending if q.exists()}
            self.pending.add(p)
            self.command_id = ident
            return ident

    def wait(self, ident, cancel, timeout, on_accepted=None):
        deadline = time.monotonic() + timeout
        accepted = False
        while time.monotonic() < deadline:
            if cancel.is_set():
                raise InterruptedError()
            s = self.state()
            if s.get("faulted"):
                raise RuntimeError("Controller fault: " + str(s.get("last_error")))
            if s.get("last_command") == ident:
                if s.get("last_command_result") != "accepted":
                    raise RuntimeError(
                        "Controller rejected command: " + str(s.get("last_error"))
                    )
                if not accepted:
                    accepted = True
                    if on_accepted:
                        on_accepted()
                if s["mode"] == "hold":
                    return s
            elif accepted:
                raise RuntimeError("Another client changed the controller command")
            cancel.wait(0.05)
        raise TimeoutError("Controller command acknowledgement/completion timed out")

    def allowed_motions(self, motions):
        state = self.state()
        if self.command_id and state.get("last_command") != self.command_id:
            self.current = "START"
        return [
            m
            for m in motions
            if m == "wait" or self.current + "->" + m in self.transitions
        ] or ["wait"]

    def validate_score(self, steps):
        self.allowed_motions(["wait"])
        previous = self.current
        for step in steps:
            motion = step["motion"]
            if previous + "->" + motion not in self.transitions:
                raise ValueError("Transition not reviewed: " + previous + "->" + motion)
            previous = motion

    def prepare(self, motion, cancel):
        s = self.state()
        if self.command_id and s.get("last_command") != self.command_id:
            self.current = "START"
        if self.current + "->" + motion not in self.transitions:
            raise RuntimeError(
                "Transition not reviewed: " + self.current + "->" + motion
            )
        for row in self.assets.rows[motion]:
            for key, value in row["action"].items():
                lo, hi = s["limits"][key]
                if not lo <= value <= hi:
                    raise RuntimeError("Recorded target outside controller limits")
        self.active = True
        ident = self.issue(
            {"command": "prepare", "file": str(self.assets.motion_file(motion))}, cancel
        )
        s = self.wait(ident, cancel, 45)
        first = self.assets.rows[motion][0]["action"]
        if any(abs(s["pose"][k] - v) > 5 for k, v in first.items()):
            raise RuntimeError("Preparation did not reach the first recorded pose")

    def play(self, motion, duration, cancel, on_started):
        ident = self.issue(
            {"command": "replay", "file": str(self.assets.motion_file(motion))}, cancel
        )
        s = self.wait(ident, cancel, duration + 8, on_started)
        # A watchdog HOLD also looks idle. Check final pose before declaring success.
        last = self.assets.rows[motion][-1]["action"]
        if any(abs(s["pose"][k] - v) > 6 for k, v in last.items()):
            raise RuntimeError("Replay stopped before its recorded final pose")
        with self.lock:
            if cancel.is_set():
                raise InterruptedError()
            self.current = motion
            self.active = False

    def stop(self):
        with self.lock:
            for p in list(self.pending):
                p.unlink(missing_ok=True)
            self.pending.clear()
            if self.active:
                self.issue({"command": "hold"})
                self.active = False
            self.current = "START"

    def close(self):
        try:
            self.stop()
        finally:
            self.owner.close()


class SoundPlayer:
    def __init__(self, system=False):
        self.system = system
        self.process = None
        self.lock = threading.Lock()

    def play(self, path):
        if not self.system:
            return
        with self.lock:
            self._stop()
            command = shutil.which("afplay") or shutil.which("aplay")
            if not command:
                raise RuntimeError("No system audio player; use browser audio")
            self.process = subprocess.Popen(
                [command, str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def _stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
        self.process = None

    def stop(self):
        with self.lock:
            self._stop()
