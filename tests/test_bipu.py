"""Offline behavior, cancellation, authorization, and hardware-protocol regression tests."""

import hashlib
import json
import os
import random
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from expressive_arm.bipu.assets import Assets
from expressive_arm.bipu.policy import PetState, Policy
from expressive_arm.bipu.decisions import Rules, Jev, DecisionError
from expressive_arm.bipu.engine import Engine
from expressive_arm.bipu.backends import PreviewBackend, ControllerBackend
from expressive_arm.bipu.score import validate_score
from expressive_arm.bipu.server import Server
from expressive_arm.bipu.telegram import TelegramBridge


class MemoryAssets:
    def __init__(self):
        self.motions = {
            m: {"id": m, "duration_s": 0.12}
            for m in (
                "curious",
                "happy",
                "sleepy",
                "disappointed",
                "hesitant",
                "startled",
                "angry",
                "playful",
            )
        }
        self.sounds = []
        self.by_id = {}
        self.videos = {}

    def sound_ids(self, *args):
        return []

    def validate_sound(self, motion, ident):
        if ident not in self.by_id:
            raise ValueError("Missing sound")


class Immediate(PreviewBackend):
    def __init__(self):
        self.played = []

    def play(self, motion, duration, cancel, on_started):
        if cancel.is_set():
            raise InterruptedError()
        on_started()
        self.played.append(motion)


class Behavior(unittest.TestCase):
    def setUp(self):
        self.assets = MemoryAssets()
        self.policy = Policy(self.assets, random.Random(1))
        self.state = PetState(last_contact=100, updated=100)

    def react(self, intent, now=100):
        return self.policy.motions(self.state, {"kind": "message"}, intent, now)

    def test_scold_then_reassure_has_memory(self):
        self.assertEqual(self.react("scold"), ["startled"])
        self.assertEqual(self.react("scold", 101), ["angry"])
        self.assertEqual(self.react("reassure", 102), ["hesitant"])
        self.assertEqual(self.react("praise", 103), ["happy"])

    def test_toy_message_does_not_claim_props(self):
        self.assertEqual(self.react("toy"), ["curious"])
        self.state.toys_ready = True
        self.assertEqual(self.react("toy"), ["playful"])

    def test_sleep_once_then_wait(self):
        self.assertEqual(
            self.policy.motions(self.state, {"kind": "idle"}, "idle", 341), ["sleepy"]
        )
        self.policy.completed(self.state, "sleepy", None)
        self.assertEqual(
            self.policy.motions(self.state, {"kind": "idle"}, "idle", 500), ["wait"]
        )
        self.assertEqual(self.react("praise", 501), ["happy"])
        self.assertFalse(self.state.asleep)

    def test_invalid_persisted_state_rejected(self):
        for value in ("bad", float("nan"), -2, True):
            with self.assertRaises(ValueError):
                PetState(energy=value)

    def test_default_rules_negation_and_user_phrases(self):
        r = Rules()
        for text, intent in [
            ("还不错", "praise"),
            ("不拿了", "reassure"),
            ("你不乖", "scold"),
            ("给你两块积木", "toy"),
            ("那我把积木收走了？", "tease"),
        ]:
            self.assertEqual(r.classify(text), intent)

    def test_idle_wait_not_diluted_by_large_sound_pool(self):
        r = Rules(random.Random(1))
        options = {"wait": {"motion": "wait"}}
        options.update({str(i): {"motion": "happy"} for i in range(100)})
        count = sum(r.choose({}, options) == "wait" for _ in range(1000))
        self.assertGreater(count, 750)


class JevContract(unittest.TestCase):
    def answer(self, key="praise", confidence=0.9):
        return {
            "answers": {
                "decision": {"type": "choice", "choice": key, "confidence": confidence}
            }
        }

    def test_documented_request_and_allowlisted_choice(self):
        payload = []

        def transport(p):
            payload.append(p)
            return self.answer()

        self.assertEqual(
            Jev("test-only", transport=transport).classify("还不错"), "praise"
        )
        self.assertEqual(payload[0]["model"], "jev-latest")
        self.assertEqual(payload[0]["questions"]["decision"]["type"], "choice")
        self.assertIsInstance(payload[0]["state"], str)

    def test_uncertain_unknown_and_malformed_do_not_move(self):
        for answer in [
            self.answer("invented"),
            self.answer(confidence=0.2),
            self.answer(confidence=float("nan")),
            self.answer(confidence=True),
            {},
        ]:
            with self.assertRaises(DecisionError):
                Jev("test-only", transport=lambda _, a=answer: a).classify("hi")

    def test_network_error_does_not_leak_key(self):
        def broken(_):
            raise RuntimeError("test-secret")

        with self.assertRaises(DecisionError) as e:
            Jev("test-secret", transport=broken).classify("hi")
        self.assertNotIn("test-secret", str(e.exception))


class Runtime(unittest.TestCase):
    def setUp(self):
        self.assets = MemoryAssets()
        self.backend = Immediate()
        self.e = Engine(self.assets, backend=self.backend, idle_min=3600, idle_max=3600)
        self.e.start_worker()

    def tearDown(self):
        self.e.close()

    def wait(self, predicate):
        deadline = time.monotonic() + 2
        while not predicate():
            if time.monotonic() > deadline:
                self.fail("Runtime did not reach expected state")
            time.sleep(0.005)

    def test_messages_react_and_stop_clears_queue(self):
        self.e.start()
        self.e.message("还不错")
        self.wait(lambda: len(self.backend.played) == 1)
        self.assertEqual(self.backend.played, ["happy"])
        self.e.stop()
        self.assertFalse(self.e.enabled)
        self.assertEqual(len(self.e.queue), 0)

    def test_stop_during_decision_cannot_start_motion(self):
        entered = threading.Event()
        release = threading.Event()

        class Slow(Rules):
            def classify(self, text):
                entered.set()
                release.wait(1)
                return "praise"

        self.e.provider = Slow()
        self.e.start()
        self.e.message("hello")
        self.assertTrue(entered.wait(1))
        self.e.stop()
        release.set()
        self.wait(lambda: not self.e.busy)
        self.assertEqual(self.backend.played, [])

    def test_stop_during_prepare_cannot_replay(self):
        entered = threading.Event()

        class Slow(Immediate):
            def prepare(self, motion, cancel):
                entered.set()
                cancel.wait(2)
                raise InterruptedError()

        backend = Slow()
        self.e.backend = backend
        self.e.start()
        self.e.message("还不错")
        self.assertTrue(entered.wait(1))
        self.e.stop()
        self.wait(lambda: not self.e.busy)
        self.assertEqual(backend.played, [])
        self.assertIsNone(self.e.current)

    def test_play_consumes_props(self):
        self.e.set_toys(True)
        self.e.start()
        self.e.message("给你积木")
        self.wait(lambda: len(self.backend.played) == 1)
        self.assertEqual(self.backend.played, ["playful"])
        self.assertFalse(self.e.state.toys_ready)
        self.e.message("给你积木")
        self.wait(lambda: len(self.backend.played) == 2)
        self.assertEqual(self.backend.played[1], "curious")

    def test_entire_score_is_validated_before_running(self):
        with self.assertRaises(ValueError):
            self.e.start_score(
                {"version": 1, "steps": [{"motion": "happy"}, {"motion": "invented"}]}
            )
        self.assertFalse(self.e.enabled)
        self.assertEqual(self.backend.played, [])

    def test_score_order_and_stops_after_last(self):
        self.e.start_score(
            {"version": 1, "steps": [{"motion": "happy"}, {"motion": "curious"}]}
        )
        self.wait(lambda: len(self.backend.played) == 2 and not self.e.busy)
        self.assertEqual(self.backend.played, ["happy", "curious"])
        self.assertFalse(self.e.enabled)

    def test_expired_messages_do_not_trigger(self):
        self.e.start()
        with self.e.lock:
            self.e.queue.append(
                {"kind": "message", "text": "还不错", "created": time.time() - 46}
            )
        self.e.wakeup.set()
        self.wait(lambda: any(e["kind"] == "dropped" for e in self.e.events))
        self.assertEqual(self.backend.played, [])

    def test_saved_mood_restored_but_props_never_restored(self):
        with tempfile.TemporaryDirectory() as d:
            e = Engine(self.assets, storage=d)
            e.state.irritation = 2
            e.state.toys_ready = True
            e.persist()
            e.close()
            other = Engine(self.assets, storage=d)
            self.assertGreater(other.state.irritation, 1.9)
            self.assertFalse(other.state.toys_ready)
            self.assertFalse(other.enabled)
            other.close()


class Scores(unittest.TestCase):
    def test_bad_shapes_nonfinite_and_overlap(self):
        assets = MemoryAssets()
        assets.motions["happy"]["duration_s"] = 5
        assets.by_id["a"] = {"duration_s": 2}
        for sounds in [
            "bad",
            [None],
            [{"id": None}],
            [{"id": "a", "at": float("nan")}],
            [{"id": "a", "at": 4}],
            [{"id": "a", "at": 0}, {"id": "a", "at": 1}],
        ]:
            with self.assertRaises(ValueError):
                validate_score(
                    {"version": 1, "steps": [{"motion": "happy", "sounds": sounds}]},
                    assets,
                )

    def test_valid_multiple_cues(self):
        assets = MemoryAssets()
        assets.motions["happy"]["duration_s"] = 5
        assets.by_id["a"] = {"duration_s": 2}
        self.assertEqual(
            len(
                validate_score(
                    {
                        "version": 1,
                        "steps": [
                            {
                                "motion": "happy",
                                "sounds": [
                                    {"id": "a", "at": 0},
                                    {"id": "a", "at": 2.5},
                                ],
                            }
                        ],
                    },
                    assets,
                )
            ),
            1,
        )


class HardwareProtocol(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        (self.path / "inbox").mkdir()
        self.assets = Assets()
        self.cancel = threading.Event()
        self.data = {
            "pid": os.getpid(),
            "heartbeat": time.time(),
            "controller_protocol": 2,
            "session_kind": "human_choreography",
            "mode": "hold",
            "faulted": False,
            "pose": self.assets.rows["curious"][0]["action"],
            "limits": {
                k: [-10000, 10000] for k in self.assets.rows["curious"][0]["action"]
            },
        }
        self.save()
        self.backend = ControllerBackend(self.path, self.assets, ["START->curious"])

    def save(self):
        self.data["heartbeat"] = time.time()
        p = self.path / "state.tmp"
        p.write_text(json.dumps(self.data))
        p.replace(self.path / "state.json")

    def tearDown(self):
        self.backend.active = False
        self.backend.close()
        self.temp.cleanup()

    def test_only_reviewed_next_motions_are_available(self):
        self.assertEqual(
            self.backend.allowed_motions(["curious", "happy"]), ["curious"]
        )
        self.assertEqual(self.backend.allowed_motions(["happy"]), ["wait"])

    def test_score_rejects_later_unreviewed_transition_before_play(self):
        with self.assertRaises(ValueError):
            self.backend.validate_score([{"motion": "curious"}, {"motion": "happy"}])
        self.assertEqual(list((self.path / "inbox").glob("*.json")), [])

    def test_stale_controller_rejected(self):
        self.data["heartbeat"] = time.time() - 5
        (self.path / "state.json").write_text(json.dumps(self.data))
        with self.assertRaises(RuntimeError):
            self.backend.state()

    def test_unreviewed_transition_never_queued(self):
        with self.assertRaises(RuntimeError):
            self.backend.prepare("happy", self.cancel)
        self.assertEqual(list((self.path / "inbox").glob("*.json")), [])

    def test_outside_limits_never_queued(self):
        key = next(iter(self.data["limits"]))
        self.data["limits"][key] = [0, 0]
        self.save()
        with self.assertRaises(RuntimeError):
            self.backend.prepare("curious", self.cancel)
        self.assertEqual(list((self.path / "inbox").glob("*.json")), [])

    def test_rejection_not_reported_as_success(self):
        ident = self.backend.issue({"command": "prepare"}, self.cancel)
        self.data.update(
            last_command=ident,
            last_command_result="rejected",
            last_error="test rejection",
        )
        self.save()
        with self.assertRaises(RuntimeError):
            self.backend.wait(ident, self.cancel, 0.1)

    def test_timeout_and_cancel(self):
        ident = self.backend.issue({"command": "prepare"}, self.cancel)
        with self.assertRaises(TimeoutError):
            self.backend.wait(ident, self.cancel, 0.01)
        self.cancel.set()
        with self.assertRaises(InterruptedError):
            self.backend.issue({"command": "replay"}, self.cancel)

    def test_stop_removes_own_queued_commands_then_holds(self):
        self.backend.issue({"command": "replay"}, self.cancel)
        self.backend.active = True
        self.backend.stop()
        queued = [
            json.loads(p.read_text()) for p in (self.path / "inbox").glob("*.json")
        ]
        self.assertEqual([x["command"] for x in queued], ["hold"])

    def test_early_hold_wrong_pose_not_success(self):
        self.data["pose"] = {k: 1000 for k in self.data["pose"]}
        self.save()
        original = self.backend.issue

        def ack(command, cancel):
            ident = original(command, cancel)
            self.data.update(last_command=ident, last_command_result="accepted")
            self.save()
            return ident

        self.backend.issue = ack
        with self.assertRaises(RuntimeError):
            self.backend.play("curious", 1, self.cancel, lambda: None)


class LocalHTTP(unittest.TestCase):
    def setUp(self):
        self.e = Engine(MemoryAssets())
        self.server = Server(("127.0.0.1", 0), self.e)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.e.close()
        self.thread.join()

    def request(self, headers):
        req = urllib.request.Request(self.url + "/api/start", b"{}", headers)
        return urllib.request.urlopen(req, timeout=2)

    def test_no_token_or_cross_origin_blocked(self):
        for headers in [
            {},
            {"X-Bipu-Token": self.server.token, "Origin": "https://evil.example"},
            {"X-Bipu-Token": self.server.token, "Host": "evil.example"},
        ]:
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.request(headers)
            self.assertEqual(e.exception.code, 403)
            e.exception.close()
        self.assertFalse(self.e.enabled)

    def test_local_authenticated_start(self):
        with self.request({"X-Bipu-Token": self.server.token}) as r:
            self.assertEqual(r.status, 200)
        self.assertTrue(self.e.enabled)

    def test_page_does_not_expose_paths_or_credentials(self):
        with urllib.request.urlopen(self.url) as r:
            html = r.read().decode()
        self.assertIn("Bipu", html)
        self.assertNotIn("__TOKEN__", html)
        self.assertNotIn("/Users/", html)


class Telegram(unittest.TestCase):
    def test_only_fresh_allowlisted_private_messages(self):
        e = Engine(MemoryAssets())
        e.start()
        b = TelegramBridge(e, "test-only", [10])

        def msg(ident=10, kind="private", age=0):
            return {
                "message": {
                    "chat": {"id": ident, "type": kind},
                    "date": time.time() - age,
                    "text": "还不错",
                }
            }

        for m in [msg(11), msg(kind="group"), msg(age=46), msg(age=-60)]:
            b.handle(m)
        self.assertEqual(len(e.queue), 0)
        b.handle(msg())
        self.assertEqual(len(e.queue), 1)
        self.assertEqual(e.queue[0]["source"], "telegram")
        e.close()


class PackagedAssets(unittest.TestCase):
    def test_eight_unchanged_motions_and_heart_sounds(self):
        a = Assets()
        self.assertEqual(len(a.motions), 8)
        self.assertEqual(len(a.sounds), 39)
        self.assertEqual(
            {s["id"] for s in a.sounds if s.get("favorite")},
            {"v6_H05", "v6_H11", "v6_H20", "v6_H24"},
        )
        self.assertFalse(
            any(s.get("default") for s in a.sounds if s["group"] == "backup")
        )

    def test_sound_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            a = Assets(d)
            a.by_id["test"] = {
                "file": "test.wav",
                "sha256": hashlib.sha256(b"original").hexdigest(),
            }
            Path(d, "test.wav").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                a.sound_file("test")
            a.by_id["test"]["file"] = "../outside.wav"
            with self.assertRaises(ValueError):
                a.sound_file("test")


if __name__ == "__main__":
    unittest.main()
