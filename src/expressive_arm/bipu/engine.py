from __future__ import annotations
import json
import os
import random
import threading
import time
from dataclasses import asdict
from collections import deque
from pathlib import Path
from .policy import PetState, Policy
from .decisions import Rules, DecisionError
from .backends import PreviewBackend, SoundPlayer
from .score import validate_score


class Engine:
    def __init__(
        self,
        assets,
        provider=None,
        backend=None,
        storage=None,
        seed=None,
        speed=1,
        idle_min=45,
        idle_max=90,
        sleep_after=240,
        system_audio=False,
    ):
        if not 0 < speed <= 100:
            raise ValueError("Preview speed must be in (0,100]")
        self.assets = assets
        self.rng = random.Random(seed)
        self.provider = provider or Rules(self.rng)
        self.backend = backend or PreviewBackend()
        if self.backend.kind == "hardware" and speed != 1:
            raise ValueError("Hardware speed must stay 1")
        if not 1 <= idle_min <= idle_max <= 3600:
            raise ValueError("Invalid idle interval")
        from .score import finite

        finite(sleep_after, "sleep_after", minimum=1, maximum=86400)
        self.speed = speed
        self.idle_min, self.idle_max = idle_min, idle_max
        self.policy = Policy(assets, self.rng, sleep_after)
        now = time.time()
        self.state = PetState(last_contact=now, updated=now)
        self.storage = Path(storage) if storage else None
        if self.storage:
            self.storage.mkdir(parents=True, exist_ok=True)
            try:
                old = json.loads((self.storage / "pet-state.json").read_text())
                self.state = PetState(**old)
                self.state.toys_ready = False
                self.state.advance(now)
            except (OSError, ValueError, TypeError):
                pass
        self.lock = threading.RLock()
        self.queue = deque(maxlen=16)
        self.events = deque(maxlen=120)
        self.event_id = 0
        self.cancel = threading.Event()
        self.shutdown = threading.Event()
        self.wakeup = threading.Event()
        self.enabled = False
        self.busy = False
        self.mode = "pet"
        self.current = None
        self.score = None
        self.sound = SoundPlayer(system_audio)
        self.next_idle = now + idle_min
        self.error = None
        self.worker = threading.Thread(
            target=self.run, name="bipu-runtime", daemon=True
        )

    def start_worker(self):
        self.worker.start()

    def log(self, kind, **data):
        with self.lock:
            self.event_id += 1
            e = {"id": self.event_id, "time": time.time(), "kind": kind, **data}
            self.events.append(e)
            if self.storage:
                with (self.storage / "events.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
            return e

    def persist(self):
        if self.storage:
            tmp = self.storage / "pet-state.tmp"
            tmp.write_text(json.dumps(asdict(self.state)))
            os.replace(tmp, self.storage / "pet-state.json")

    def snapshot(self):
        with self.lock:
            return {
                "enabled": self.enabled,
                "busy": self.busy,
                "mode": self.mode,
                "backend": self.backend.kind,
                "provider": self.provider.name,
                "audio": "system" if self.sound.system else "browser",
                "state": self.state.public(time.time()),
                "current": self.current,
                "queue_length": len(self.queue),
                "error": self.error,
                "next_idle_in": max(0, round(self.next_idle - time.time(), 1)),
                "events": list(self.events),
                "motions": list(self.assets.motions.values()),
                "videos": list(self.assets.videos),
                "sounds": [
                    {k: v for k, v in s.items() if k not in ("sha256", "file")}
                    for s in self.assets.sounds
                ],
            }

    def start(self):
        with self.lock:
            if self.busy:
                raise ValueError("上一项正在收尾，请稍后再开始")
            self.cancel.clear()
            self.enabled = True
            self.mode = "pet"
            self.error = None
            self.next_idle = time.time() + self.idle_min
        self.log("started", backend=self.backend.kind, provider=self.provider.name)
        self.wakeup.set()

    def stop(self):
        with self.lock:
            self.enabled = False
            self.cancel.set()
            self.queue.clear()
            self.score = None
            self.state.toys_ready = False
        self.sound.stop()
        try:
            self.backend.stop()
        except Exception as error:
            self.log("stop_error", detail=str(error))
        self.log("stopped", torque_released=False)
        self.wakeup.set()

    def set_toys(self, ready):
        if not isinstance(ready, bool):
            raise ValueError("toys_ready must be boolean")
        with self.lock:
            if self.busy:
                raise ValueError("动作进行中不能修改道具状态")
            self.state.toys_ready = ready
            self.persist()
        self.log("props", ready=ready)

    def message(self, text, source="local"):
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise ValueError("Message needs 1..2000 characters")
        with self.lock:
            if not self.enabled or self.mode != "pet":
                raise ValueError("先开启宠物模式")
            event = {
                "kind": "message",
                "text": text.strip(),
                "source": source,
                "created": time.time(),
            }
            if len(self.queue) == self.queue.maxlen:
                self.queue.popleft()
                self.log("dropped", reason="queue full; oldest discarded")
            self.queue.append(event)
            self.log("message", text=text.strip(), source=source)
        self.wakeup.set()

    def start_score(self, document):
        steps = validate_score(document, self.assets)
        with self.lock:
            if self.busy or self.enabled:
                raise ValueError("先停止宠物模式再运行编排")
            if sum(s["motion"] == "playful" for s in steps) > 1:
                raise ValueError("同一编排仅允许一次玩具动作；重新摆好后再运行下一遍")
            if (
                any(s["motion"] == "playful" for s in steps)
                and not self.state.toys_ready
            ):
                raise ValueError("玩耍需要先确认道具位置")
            self.backend.validate_score(steps)
            self.mode = "score"
            self.score = steps
            self.enabled = True
            self.cancel.clear()
            self.error = None
        self.log("score_started", steps=len(steps))
        self.wakeup.set()

    def perform(self, motion, sounds):
        if self.cancel.is_set():
            raise InterruptedError()
        if motion == "wait":
            self.log("waiting")
            return
        with self.lock:
            if motion == "playful":
                if not self.state.toys_ready:
                    raise ValueError("Props are no longer ready")
                self.state.toys_ready = False
                self.persist()
            self.current = {
                "motion": motion,
                "phase": "preparing",
                "started": None,
                "duration": self.assets.motions[motion]["duration_s"] / self.speed,
            }
        try:
            self.backend.prepare(motion, self.cancel)
        except BaseException:
            with self.lock:
                self.current = None
            raise
        started = threading.Event()
        finish_sounds = threading.Event()

        def audio_loop():
            while not started.wait(0.03):
                if self.cancel.is_set() or finish_sounds.is_set():
                    return
            origin = time.monotonic()
            for cue in sounds:
                target = origin + cue["at"] / self.speed
                while time.monotonic() < target:
                    if self.cancel.is_set() or finish_sounds.wait(
                        min(0.03, max(0, target - time.monotonic()))
                    ):
                        return
                with self.lock:
                    if self.cancel.is_set() or finish_sounds.is_set():
                        return
                    ident = cue["id"]
                    if ident:
                        try:
                            self.sound.play(self.assets.sound_file(ident))
                            self.log("sound", sound=ident, motion=motion)
                        except (OSError, ValueError, RuntimeError) as error:
                            self.log("audio_error", detail=str(error))

        thread = threading.Thread(target=audio_loop, daemon=True)

        def on_started():
            with self.lock:
                if self.cancel.is_set():
                    return
                self.current["phase"] = "playing"
                self.current["started"] = time.time()
            self.log("motion_started", motion=motion, duration=self.current["duration"])
            started.set()

        thread.start()
        try:
            self.backend.play(
                motion,
                self.assets.motions[motion]["duration_s"] / self.speed,
                self.cancel,
                on_started,
            )
            if self.cancel.is_set():
                raise InterruptedError()
            with self.lock:
                self.policy.completed(
                    self.state, motion, sounds[-1]["id"] if sounds else None
                )
                self.persist()
            self.log("motion_finished", motion=motion)
        finally:
            finish_sounds.set()
            thread.join(timeout=1)
            self.sound.stop()
            with self.lock:
                self.current = None

    def react(self, event):
        with self.lock:
            interpretation_context = {
                "pet": self.state.public(time.time()),
                "recent": [
                    e
                    for e in list(self.events)[-16:]
                    if e["kind"] in ("message", "decision", "motion_finished")
                ][-8:],
            }
        if event["kind"] == "message":
            contextual = getattr(self.provider, "classify_with_context", None)
            intent = (
                contextual(event["text"], interpretation_context)
                if contextual
                else self.provider.classify(event["text"])
            )
        else:
            intent = "idle"
        if self.cancel.is_set():
            raise InterruptedError()
        with self.lock:
            motions = self.policy.motions(self.state, event, intent, time.time())
            motions = self.backend.allowed_motions(motions)
            options = self.policy.options(self.state, motions)
            context = {
                "event": event,
                "intent": intent,
                "pet": self.state.public(time.time()),
                "recent": [
                    e
                    for e in list(self.events)[-12:]
                    if e["kind"] in ("message", "motion_finished")
                ],
                "rules": "Props readiness is operator-controlled. Do not infer it from messages. Bipu expresses itself without words.",
            }
            self.persist()
        key = (
            "wait"
            if list(options) == ["wait"]
            else self.provider.choose(context, options)
        )
        if self.cancel.is_set():
            raise InterruptedError()
        if key not in options:
            raise DecisionError("Provider returned an unlisted option")
        chosen = options[key]
        with self.lock:
            self.error = None
        self.log(
            "decision",
            provider=self.provider.name,
            model=getattr(self.provider, "last_model", None),
            intent=intent,
            motion=chosen["motion"],
            sound=chosen["sound"],
        )
        self.perform(
            chosen["motion"],
            [{"id": chosen["sound"], "at": 0.35}] if chosen["sound"] else [],
        )

    def run(self):
        while not self.shutdown.is_set():
            event = None
            steps = None
            with self.lock:
                if self.enabled and not self.busy:
                    if self.mode == "score" and self.score is not None:
                        steps = self.score
                        self.score = None
                    elif self.mode == "pet":
                        while (
                            self.queue and time.time() - self.queue[0]["created"] > 45
                        ):
                            self.queue.popleft()
                            self.log("dropped", reason="message expired")
                        if self.queue:
                            event = self.queue.popleft()
                        elif time.time() >= self.next_idle:
                            event = {"kind": "idle", "created": time.time()}
                    if event is not None or steps is not None:
                        self.busy = True
            if event is None and steps is None:
                self.wakeup.wait(0.15)
                self.wakeup.clear()
                continue
            try:
                if steps is not None:
                    for step in steps:
                        if self.cancel.wait(step["wait_before"] / self.speed):
                            raise InterruptedError()
                        self.perform(step["motion"], step["sounds"])
                    self.log("score_finished")
                    with self.lock:
                        self.enabled = False
                else:
                    self.react(event)
            except InterruptedError:
                self.log("cancelled")
            except DecisionError as error:
                self.log(
                    "decision_error", provider=self.provider.name, detail=str(error)
                )
                with self.lock:
                    self.error = str(error)
            except Exception as error:
                self.stop()
                with self.lock:
                    self.error = str(error)
                self.log("fault", detail=str(error))
            finally:
                with self.lock:
                    self.busy = False
                    self.next_idle = time.time() + self.rng.uniform(
                        self.idle_min, self.idle_max
                    )
                    self.persist()

    def close(self):
        self.stop()
        self.shutdown.set()
        self.wakeup.set()
        if self.worker.is_alive():
            self.worker.join(timeout=18)
        self.backend.close()
