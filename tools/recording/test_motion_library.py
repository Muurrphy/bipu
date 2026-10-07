"""Offline checks: units, all 75 designs, limits, smoothness, torque startup."""
import math
import unittest

from controller import acquire_without_reconfigure, hardware_limits, planning_pose, Session
from motion_library import ACCELERATION, JOINTS, VELOCITY, check_pose, compile_motion, compile_pose_motion, read_catalog, sample_motion


class MotionTests(unittest.TestCase):
    def setUp(self):
        self.catalog = read_catalog()
        self.neutral = self.catalog["reference_pose"]

    def test_all_75_are_smooth_and_return_without_opening_gripper(self):
        self.assertEqual(len(self.catalog["expressions"]),25)
        self.assertTrue({"好奇","开心","失落","害羞","犹豫","亲昵"}.issubset({item["name"] for item in self.catalog["expressions"]}))
        for item in self.catalog["expressions"]:
            for level in self.catalog["levels"]:
                motion = compile_motion(self.catalog,item["id"],self.neutral,level)
                previous,_ = sample_motion(motion,0)
                velocity_previous = {key:0 for key in JOINTS}
                for frame in range(1,math.ceil(motion["duration_s"]*120)+1):
                    current,_ = sample_motion(motion,frame/120)
                    self.assertEqual(current["gripper.pos"],self.neutral["gripper.pos"])
                    for key in JOINTS:
                        velocity = (current[key]-previous[key])*120
                        self.assertLessEqual(abs(velocity),VELOCITY[key]+0.02)
                        self.assertLessEqual(abs(velocity-velocity_previous[key])*120,ACCELERATION[key]+0.1)
                        velocity_previous[key] = velocity
                    previous = current
                final,_ = sample_motion(motion,motion["duration_s"]+1)
                self.assertEqual(final,self.neutral)

    def test_bad_pose_and_limit_exceedance_are_rejected(self):
        pose = dict(self.neutral); pose["gripper.pos"] = 101
        with self.assertRaises(ValueError): check_pose(pose)
        pose = dict(self.neutral); pose["wrist_roll.pos"] = float("nan")
        with self.assertRaises(ValueError): check_pose(pose)
        limits = {key:(value-0.1,value+0.1) for key,value in self.neutral.items()}
        with self.assertRaises(ValueError): compile_motion(self.catalog,"happy",self.neutral,limits=limits)

    def test_gripper_is_percentage_not_body_angle(self):
        motion = compile_motion(self.catalog,"surprised",self.neutral,"strong",move_gripper=True)
        self.assertEqual(motion["segments"][0]["to"]["gripper.pos"],18)
        pose = dict(self.neutral); pose["gripper.pos"] = 99
        with self.assertRaises(ValueError): compile_motion(self.catalog,"surprised",pose,move_gripper=True)

    def test_full_shoulder_lift_has_no_intermediate_stops(self):
        start = dict(self.neutral); start["shoulder_lift.pos"] = 45.4
        target = dict(start); target["shoulder_lift.pos"] = -30
        limits = {key: (-105, 105) for key in JOINTS}; limits["gripper.pos"] = (0, 100)
        motion = compile_pose_motion(start, target, limits)
        self.assertEqual(len(motion["segments"]), 1)
        previous, _ = sample_motion(motion, 0)
        last_velocity = 0
        for frame in range(1, math.ceil(motion["duration_s"] * 120) + 1):
            pose, _ = sample_motion(motion, frame / 120)
            velocity = (pose["shoulder_lift.pos"] - previous["shoulder_lift.pos"]) * 120
            self.assertLessEqual(velocity, 0)
            self.assertLessEqual(abs(velocity), VELOCITY["shoulder_lift.pos"] + .02)
            self.assertLessEqual(abs(velocity - last_velocity) * 120, ACCELERATION["shoulder_lift.pos"] + .1)
            for key in JOINTS:
                if key != "shoulder_lift.pos": self.assertEqual(pose[key], start[key])
            if .01 < frame / 120 < motion["duration_s"] - .01:
                self.assertLess(velocity, 0)
            previous, last_velocity = pose, velocity
        final, _ = sample_motion(motion, motion["duration_s"])
        for key in JOINTS: self.assertAlmostEqual(final[key], target[key], places=10)

    def test_unconfirmed_table_pose_cannot_play(self):
        class Bus:
            def sync_read(inner,name): return {key.removesuffix('.pos'):value for key,value in self.neutral.items()}
        class Arm:
            bus = Bus()
            def send_action(inner,action): raise AssertionError("No hardware writes expected")
        limits = {key:(-180,180) for key in JOINTS}; limits["gripper.pos"]=(0,100)
        session = Session(Arm(),limits,self.neutral)
        with self.assertRaisesRegex(RuntimeError,"未确认悬空"):
            session.accept({"command":"play","expression":"happy"})

    def test_current_goal_is_latched_before_torque_enable(self):
        from types import SimpleNamespace
        calls = []
        class Bus:
            is_calibrated = True
            motors = {key.removesuffix('.pos'):None for key in JOINTS}
            calibration = {name:SimpleNamespace(range_min=0,range_max=4095) for name in motors}
            def sync_read(inner,name,normalize=True):
                if name == "Operating_Mode": return {k:0 for k in inner.motors}
                if name == "Torque_Enable": return {k:1 for k in inner.motors}
                if not normalize: return {k:2000 for k in inner.motors}
                return {k:(10 if k=="gripper" else 0) for k in inner.motors}
            def sync_write(inner,name,value,normalize=True): calls.append(("goal",normalize,value))
            def enable_torque(inner): calls.append(("enable",))
        acquire_without_reconfigure(Bus())
        self.assertEqual(calls[0][0:2],("goal",False))
        self.assertEqual(calls[1],("enable",))

    def test_measured_margin_is_not_an_expanded_command_limit(self):
        limits = {key: (-105, 105) for key in JOINTS}; limits["gripper.pos"] = (0, 100)
        original = dict(limits)
        observed = dict(self.neutral); observed["shoulder_lift.pos"] = -105.25
        target = planning_pose(observed, limits)
        self.assertEqual(target["shoulder_lift.pos"], -105)
        self.assertEqual(observed["shoulder_lift.pos"], -105.25)
        self.assertEqual(limits, original)
        with self.assertRaises(ValueError): check_pose(observed, limits)
        observed["shoulder_lift.pos"] = -107.01
        with self.assertRaises(ValueError): planning_pose(observed, limits)
        observed["shoulder_lift.pos"] = -105.25
        observed["gripper.pos"] = 100.01
        with self.assertRaises(ValueError): planning_pose(observed, limits)

    def test_startup_latches_actual_raw_pose_inside_calibration_outside_command_margin(self):
        from types import SimpleNamespace
        calls = []
        class Bus:
            is_calibrated = True
            motors = {key.removesuffix('.pos'): None for key in JOINTS}
            calibration = {name: SimpleNamespace(range_min=0, range_max=4095) for name in motors}
            def sync_read(inner, name, normalize=True):
                if name == "Operating_Mode": return {key: 0 for key in inner.motors}
                if name == "Torque_Enable": return {key: 1 for key in inner.motors}
                if not normalize: return {key: (4088 if key == "shoulder_lift" else 2000) for key in inner.motors}
                return {key: (179.3846153846154 if key == "shoulder_lift" else 10 if key == "gripper" else 0) for key in inner.motors}
            def sync_write(inner, name, value, normalize=True): calls.append((name, normalize, dict(value)))
            def enable_torque(inner): calls.append(("enable",))
        bus = Bus()
        observed, limits = acquire_without_reconfigure(bus)
        self.assertEqual(limits, hardware_limits(bus))
        self.assertGreater(observed["shoulder_lift.pos"], limits["shoulder_lift.pos"][1])
        self.assertEqual(calls[0][0:2], ("Goal_Position", False))
        self.assertEqual(calls[0][2]["shoulder_lift"], 4088)
        self.assertEqual(calls[1], ("enable",))
        self.assertEqual(len(calls), 2)

    def test_persistent_session_runs_all_versions_without_reconnecting(self):
        class Bus:
            position = dict(self.neutral)
            def sync_read(inner,name): return {key.removesuffix('.pos'):value for key,value in inner.position.items()}
        class Arm:
            bus = Bus()
            writes = 0
            def send_action(inner,action):
                inner.bus.position = dict(action)
                inner.writes += 1
                return dict(action)
        arm = Arm()
        limits = {key:(-180,180) for key in JOINTS}; limits["gripper.pos"]=(0,100)
        session = Session(arm,limits,self.neutral)
        session.neutral = dict(self.neutral)
        for item in self.catalog["expressions"]:
            for level in self.catalog["levels"]:
                session.accept({"command":"play","expression":item["id"],"level":level})
                start, duration = session.started, session.motion["duration_s"]
                for frame in range(math.ceil(duration*60)+1):
                    session.step(start+min(frame/60,duration))
                session.step(start+duration+0.001)
                self.assertEqual(session.mode,"hold")
                for key in JOINTS:
                    self.assertAlmostEqual(arm.bus.position[key],self.neutral[key],places=5)
        self.assertGreater(arm.writes,75)


if __name__ == "__main__": unittest.main()
