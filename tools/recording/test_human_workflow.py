"""Offline checks for the human-led, five-minute recording workflow."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from human_controller import HumanSession, TrackingFilter, load_clip
from motion_library import JOINTS, read_catalog
from take_tools import archive_clip, cut_take


class HumanWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.pose = read_catalog()["reference_pose"]
        self.limits = {key: (-105, 105) for key in JOINTS}; self.limits["gripper.pos"] = (0, 100)

    def test_relative_start_and_five_minute_durable_record_then_hold(self):
        clock = [1000.0]
        initial = dict(self.pose)
        class Bus:
            pose = dict(initial)
            def sync_read(inner, name): return {key.removesuffix(".pos"): value for key, value in inner.pose.items()}
        class Arm:
            bus = Bus()
            def send_action(inner, action): inner.bus.pose = dict(action)
        class Master:
            pose = {key: value+15 for key, value in initial.items()}
            def get_action(inner): return dict(inner.pose)
        with tempfile.TemporaryDirectory() as directory, patch("human_controller.TAKES", Path(directory)), patch("human_controller.time.perf_counter", side_effect=lambda: clock[0]):
            session = HumanSession(Arm(), self.limits, initial, Path(directory))
            session.master = Master()
            session.accept({"command": "start", "expression": "玩耍", "mapping": "relative"})
            path = session.take_path
            session.step(clock[0])
            self.assertEqual(session.arm.bus.pose, initial)
            for frame in range(1, 18001):
                clock[0] = 1000+frame/60
                session.master.pose["shoulder_pan.pos"] = initial["shoulder_pan.pos"]+15+(frame%180)/40
                session.step(clock[0])
            self.assertTrue(path.stat().st_size > 0)
            session.accept({"command": "finish"})
            self.assertEqual(session.mode, "hold")
            self.assertIsNone(session.stream)
            rows, times = load_clip(path)
            self.assertEqual(len(rows), 18001)
            self.assertAlmostEqual(times[-1], 300)
            self.assertIn("leader", rows[-1]); self.assertIn("observed", rows[-1])
            metadata = json.loads(path.with_suffix(".meta.json").read_text())
            self.assertEqual(metadata["frames"], 18001)
            self.assertEqual(metadata["status"], "recorded_raw")
            self.assertEqual(metadata["expression"], "playful")
            self.assertEqual(metadata["name"], "玩耍")

    def test_cut_excludes_parking_and_requires_archive_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/"long.jsonl"
            rows = [{"frame": frame, "t": frame*.1, "action": dict(self.pose)} for frame in range(101)]
            for row in rows[81:]: row["action"]["shoulder_lift.pos"] += (row["t"]-8)*25
            source.write_text("\n".join(json.dumps(row) for row in rows)+"\n")
            candidate = cut_take(source, "害怕", 5, 7.9, 8, root/"candidate.jsonl")
            clipped, times = load_clip(candidate)
            self.assertAlmostEqual(times[0], 0)
            self.assertTrue(all(row["original_t"] < 8 for row in clipped))
            with self.assertRaises(ValueError): cut_take(source, "害怕", 5, 9, 8, root/"bad.jsonl")
            with self.assertRaises(ValueError): archive_clip(candidate)
            with patch("take_tools.ARCHIVE", root/"archive"):
                saved = archive_clip(candidate, confirmed=True)
            self.assertEqual(saved.read_text(), candidate.read_text())
            self.assertEqual(json.loads((saved.parent/"metadata.json").read_text())["expression"], "fearful")
            self.assertEqual(len(load_clip(source)[0]), 101)

    def test_tracking_filter_bounds_each_frame_without_start_jump(self):
        tracker = TrackingFilter(self.pose, self.limits)
        unchanged, flags = tracker.update(self.pose, 1/60)
        self.assertEqual(unchanged, self.pose)
        target = dict(self.pose); target["shoulder_pan.pos"] += 60
        previous = dict(unchanged)
        for frame in range(600):
            action, flags = tracker.update(target, 1/60)
            for key in JOINTS:
                self.assertLessEqual(abs(action[key]-previous[key]), (80 if key == "gripper.pos" else 40)/60+.000001)
                self.assertTrue(self.limits[key][0] <= action[key] <= self.limits[key][1])
            previous = action
        self.assertAlmostEqual(action["shoulder_pan.pos"], target["shoulder_pan.pos"], places=3)

    def test_direct_teleop_records_and_replays_fast_human_timing(self):
        clock = [1000.0]
        initial = dict(self.pose)
        class Bus:
            pose = dict(initial)
            def sync_read(inner, name): return {key.removesuffix(".pos"): value for key, value in inner.pose.items()}
        class Arm:
            bus = Bus()
            def send_action(inner, action): inner.bus.pose = dict(action)
        class Master:
            pose = dict(initial)
            def get_action(inner): return dict(inner.pose)
        with tempfile.TemporaryDirectory() as directory, patch("human_controller.TAKES", Path(directory)), patch("human_controller.time.perf_counter", side_effect=lambda: clock[0]):
            session = HumanSession(Arm(), self.limits, initial, Path(directory))
            session.master = Master()
            session.accept({"command": "start", "expression": "困倦"})
            source = session.take_path
            session.step(clock[0])
            self.assertEqual(session.arm.bus.pose, initial)
            # 3 degrees in 20 ms exceeded the former 40 deg/s smoothing cap.
            clock[0] += .02
            session.master.pose["shoulder_pan.pos"] += 3
            session.step(clock[0])
            self.assertAlmostEqual(session.arm.bus.pose["shoulder_pan.pos"], initial["shoulder_pan.pos"]+3)
            clock[0] += .02
            session.master.pose["shoulder_pan.pos"] -= 3
            session.step(clock[0])
            session.accept({"command": "finish"})
            rows, times = load_clip(source)
            self.assertTrue(all(row["tracking"] == "direct" for row in rows))
            metadata = json.loads(source.with_suffix(".meta.json").read_text())
            self.assertIsNone(metadata["software_velocity_limit"])
            self.assertEqual(metadata["mapping"], "absolute_calibrated_degrees")
            self.assertTrue(all(value==0 for value in metadata["offset"].values()))
            candidate = cut_take(source, "困倦", times[0], times[-1], times[-1], Path(directory)/"candidate.jsonl")
            session.accept({"command": "replay", "file": str(candidate)})
            session.step(clock[0]+.02)
            self.assertAlmostEqual(session.arm.bus.pose["shoulder_pan.pos"], initial["shoulder_pan.pos"]+3)
            session.step(clock[0]+.06)
            self.assertEqual(session.mode, "hold")
            self.assertEqual(session.arm.bus.pose, initial)

    def test_misaligned_start_requires_continuous_alignment_not_a_new_offset(self):
        clock=[1000.0]
        initial=dict(self.pose)
        target=dict(initial); target["shoulder_lift.pos"]-=22.6
        class Bus:
            pose=dict(initial)
            def sync_read(inner,name): return {key.removesuffix(".pos"): value for key,value in inner.pose.items()}
        class Arm:
            bus=Bus()
            def send_action(inner,action): inner.bus.pose=dict(action)
        class Master:
            def get_action(inner): return dict(target)
        with tempfile.TemporaryDirectory() as directory, patch("human_controller.TAKES",Path(directory)), patch("human_controller.time.perf_counter",side_effect=lambda:clock[0]):
            session=HumanSession(Arm(),self.limits,initial,Path(directory)); session.master=Master()
            with self.assertRaisesRegex(RuntimeError,"先执行 align"):
                session.accept({"command":"start","expression":"玩耍"})
            self.assertEqual(session.arm.bus.pose,initial)
            self.assertIsNone(session.stream)
            session.accept({"command":"align"})
            began=session.started; duration=session.motion["duration_s"]
            self.assertEqual(len(session.motion["segments"]),1)
            for frame in range(int(duration*60)+2): session.step(began+min(frame/60,duration))
            self.assertEqual(session.mode,"hold")
            self.assertEqual(session.arm.bus.pose,target)
            session.accept({"command":"start","expression":"玩耍"})
            self.assertEqual(session.offset,{key:0.0 for key in JOINTS})
            target["shoulder_lift.pos"]-=5
            clock[0]+=.02; session.step(clock[0])
            self.assertEqual(session.arm.bus.pose,target)
            session.accept({"command":"finish"})

    def test_prepare_lifts_first_then_replay_holds_the_selected_end(self):
        initial = dict(self.pose); initial["shoulder_lift.pos"] = 45
        class Bus:
            pose = dict(initial)
            def sync_read(inner, name): return {key.removesuffix(".pos"): value for key, value in inner.pose.items()}
        class Arm:
            bus = Bus()
            def send_action(inner, action): inner.bus.pose = dict(action)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/"candidate.jsonl"
            rows = []
            for frame in range(61):
                pose = dict(self.pose); pose["shoulder_pan.pos"] += frame/60*3
                rows.append({"t": frame/60, "action": pose})
            source.write_text("\n".join(json.dumps(row) for row in rows)+"\n")
            session = HumanSession(Arm(), self.limits, initial, Path(directory))
            session.accept({"command": "prepare", "file": str(source)})
            self.assertEqual(session.motion["segments"][0]["to"]["shoulder_lift.pos"], -30)
            for key in JOINTS:
                if key != "shoulder_lift.pos": self.assertEqual(session.motion["segments"][0]["to"][key], initial[key])
            for stage in range(2):
                began, duration = session.started, session.motion["duration_s"]
                for frame in range(int(duration*60)+2): session.step(began+min(frame/60,duration))
            self.assertEqual(session.mode, "hold")
            session.accept({"command": "replay", "file": str(source)})
            began = session.started
            for frame in range(62): session.step(began+frame/60)
            self.assertEqual(session.mode, "hold")
            self.assertEqual(session.arm.bus.pose, rows[-1]["action"])
            self.assertEqual(session.arm.bus.pose["shoulder_lift.pos"], -30)

    def test_finish_closes_recording_despite_small_measured_tracking_error(self):
        self._check_finish_with_measured_error(-105.25, outside_calibration=False)

    def test_finish_stops_and_closes_even_if_measurement_exceeds_calibration(self):
        self._check_finish_with_measured_error(-107.01, outside_calibration=True)

    def _check_finish_with_measured_error(self, angle, outside_calibration):
        initial = dict(self.pose)
        class Bus:
            pose = dict(initial)
            def sync_read(inner, name): return {key.removesuffix(".pos"): value for key, value in inner.pose.items()}
        class Arm:
            bus = Bus()
            writes = []
            def send_action(inner, action):
                inner.writes.append(dict(action)); inner.bus.pose = dict(action)
        class Master:
            def get_action(inner): return dict(initial)
        with tempfile.TemporaryDirectory() as directory, patch("human_controller.TAKES", Path(directory)):
            session = HumanSession(Arm(), self.limits, initial, Path(directory)); session.master = Master()
            session.accept({"command": "start", "expression": "困倦"})
            session.step(session.record_started)
            session.step(session.record_started+.02)
            writes_before = len(session.arm.writes)
            observed = dict(initial); observed["shoulder_lift.pos"] = angle
            session.arm.bus.pose = dict(observed)
            if outside_calibration:
                with self.assertRaises(ValueError): session.accept({"command": "finish"})
                self.assertEqual(len(session.arm.writes), writes_before)
            else:
                session.accept({"command": "finish"})
                self.assertEqual(session.pose, observed)
                self.assertEqual(session.last_sent["shoulder_lift.pos"], -105)
                self.assertEqual(self.limits["shoulder_lift.pos"], (-105, 105))
            self.assertEqual(session.mode, "hold")
            self.assertIsNone(session.motion)
            self.assertIsNone(session.stream)
            metadata = json.loads(session.take_path.with_suffix(".meta.json").read_text())
            self.assertEqual(metadata["status"], "recorded_raw")
            self.assertEqual(metadata["frames"], 2)

    def test_alignment_accepts_measured_margin_and_keeps_absolute_direct_following(self):
        initial = dict(self.pose); initial["shoulder_lift.pos"] = -105.25
        target = dict(self.pose)
        original_limits = dict(self.limits)
        class Bus:
            pose = dict(initial)
            def sync_read(inner, name): return {key.removesuffix(".pos"): value for key, value in inner.pose.items()}
        class Arm:
            bus = Bus()
            def send_action(inner, action):
                for key, value in action.items(): self.assertTrue(self.limits[key][0] <= value <= self.limits[key][1])
                inner.bus.pose = dict(action)
        class Master:
            def get_action(inner): return dict(target)
        with tempfile.TemporaryDirectory() as directory, patch("human_controller.TAKES", Path(directory)):
            session = HumanSession(Arm(), self.limits, initial, Path(directory)); session.master = Master()
            session.accept({"command": "align"})
            began, duration = session.started, session.motion["duration_s"]
            for frame in range(int(duration*60)+2): session.step(began+min(frame/60, duration))
            self.assertEqual(session.mode, "hold")
            session.accept({"command": "start", "expression": "难过"})
            self.assertEqual(session.tracking, "direct")
            self.assertEqual(session.offset, {key: 0.0 for key in JOINTS})
            target["shoulder_pan.pos"] += 3
            session.step(session.record_started+.02)
            self.assertEqual(session.arm.bus.pose, target)
            session.accept({"command": "finish"})
            self.assertEqual(self.limits, original_limits)


if __name__ == "__main__": unittest.main()
