"""Persistent human choreography: record, hold, prepare, replay without restart.

Only serve owns the follower port. Each take is append-only and fsynced every
second. finish closes a recording, not the robot connection or motor torque.
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import subprocess
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

from controller import BODY_JOINTS, Session, atomic_json, planning_pose, pose_from_bus, serve
from motion_library import JOINTS, ROOT, check_pose, compile_pose_motion
from human_repertoire import find_recording_expression

RUNTIME = ROOT / "human_runtime"
TAKES = ROOT / "人工编舞" / "完整录制"


class DirectTracker:
    """Pass through the human target each frame, keeping calibrated limits."""
    def __init__(self, pose, limits):
        self.pose, self.limits = dict(pose), limits

    def update(self, target, dt):
        bounded = {key: min(self.limits[key][1], max(self.limits[key][0], target[key])) for key in JOINTS}
        clamped = [key for key in JOINTS if bounded[key] != target[key]]
        self.pose = bounded
        return dict(bounded), clamped


class TrackingFilter:
    """Damped position following with bounded velocity and acceleration."""
    def __init__(self, pose, limits):
        self.pose, self.limits = dict(pose), limits
        self.velocity = {key: 0.0 for key in JOINTS}

    def update(self, target, dt):
        dt = max(.001, min(.05, dt))
        clamped = []
        for key in JOINTS:
            goal = min(self.limits[key][1], max(self.limits[key][0], target[key]))
            if goal != target[key]: clamped.append(key)
            vmax, amax = (80.0, 240.0) if key == "gripper.pos" else (40.0, 120.0)
            acceleration = 16**2 * (goal - self.pose[key]) - 32 * self.velocity[key]
            acceleration = max(-amax, min(amax, acceleration))
            velocity = max(-vmax, min(vmax, self.velocity[key] + acceleration * dt))
            position = self.pose[key] + velocity * dt
            bounded = min(self.limits[key][1], max(self.limits[key][0], position))
            self.velocity[key] = velocity if bounded == position else 0.0
            self.pose[key] = bounded
        return dict(self.pose), clamped


def load_clip(path: Path):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if len(rows) < 2: raise ValueError("动作片段不足两帧")
    times = [float(row["t"]) for row in rows]
    if any(not math.isfinite(t) for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("片段时间必须有限且严格递增")
    for row in rows: check_pose(row["action"])
    return rows, times


class HumanSession(Session):
    def __init__(self, arm, limits, pose, runtime=RUNTIME):
        super().__init__(arm, limits, pose, runtime)
        self.master = None
        self.stream = None
        self.take_path = None
        self.frames = 0
        self.record_started = 0.0
        self.last_sync = 0.0
        self.last_tick = time.perf_counter()
        self.offset = {}
        self.filter = None
        self.clip_rows = self.clip_times = None
        self.prepare_targets = []
        self.limit_clamped = []
        self.expression = None
        self.tracking = "direct"
        self.mapping = "absolute"
        self.clip_direct = False

    def connect_master(self, port, device_id):
        if self.master is not None: return
        if not port or not device_id:
            raise ValueError("Leader port and cached calibration ID are required")
        occupied = subprocess.run([shutil.which("lsof") or "/usr/sbin/lsof", "-t", port], capture_output=True, text=True)
        if occupied.stdout.strip(): raise RuntimeError("黑色主臂串口已被其他进程占用")
        from lerobot.teleoperators.so_leader.config_so_leader import SO101LeaderConfig
        from lerobot.teleoperators.so_leader.so_leader import SO101Leader
        master = SO101Leader(SO101LeaderConfig(port=port, id=device_id, use_degrees=True))
        try:
            master.bus.connect()
            if not master.bus.is_calibrated: raise RuntimeError("主臂校准与缓存不一致；不自动校准")
            if any(value != 0 for value in master.bus.sync_read("Torque_Enable", normalize=False).values()):
                raise RuntimeError("主臂仍有力矩；不自动更改主臂配置")
            check_pose(master.get_action())
            self.master = master
        except BaseException:
            if master.bus.is_connected: master.bus.disconnect(disable_torque=False)
            raise

    def close_recording(self, reason):
        if self.stream is None: return
        self.stream.flush(); os.fsync(self.stream.fileno()); self.stream.close(); self.stream = None
        metadata = json.loads(self.take_path.with_suffix(".meta.json").read_text(encoding="utf-8"))
        metadata.update({"status": "recorded_raw", "stop_reason": reason, "frames": self.frames,
                         "duration_s": time.perf_counter() - self.record_started,
                         "finished_at": datetime.now().isoformat()})
        atomic_json(self.take_path.with_suffix(".meta.json"), metadata)

    def hold(self, reason="保持当前位置；录制已结束"):
        try:
            super().hold(reason)
        finally:
            self.prepare_targets = []
            self.close_recording(reason)

    def accept(self, command):
        kind = command["command"]
        if kind in ("hold", "close"):
            return super().accept(command)
        if self.faulted: raise RuntimeError("故障保持状态；拒绝新动作")
        if kind == "finish":
            self.hold("本条录制结束；保持力矩")
            return
        if kind == "mark":
            if self.stream is None: raise RuntimeError("当前没有录制")
            event = {"t": time.perf_counter()-self.record_started, "label": command["label"]}
            with self.take_path.with_suffix(".events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False)+"\n")
            return
        if self.mode != "hold": raise RuntimeError("当前动作尚未结束，先 finish 或 hold")
        observed = pose_from_bus(self.arm.bus)
        planning_start = planning_pose(observed, self.limits)
        if kind == "align":
            self.connect_master(command.get("leader_port"),
                                command.get("leader_id"))
            raw = check_pose(self.master.get_action())
            target = {key: min(self.limits[key][1], max(self.limits[key][0], raw[key])) for key in JOINTS}
            self.prepare_targets = []
            self.motion = compile_pose_motion(planning_start, target, self.limits, "平滑对齐黑白臂角度", minimum_s=2.0)
            self.started = time.perf_counter(); self.last_sent = dict(planning_start)
            self.mode, self.phase = "motion", "平滑对齐黑白臂角度；请保持黑臂不动"
            return
        if kind == "start":
            item = find_recording_expression(command["expression"])
            tracking = command.get("tracking", "direct")
            if tracking not in ("direct", "smooth"):
                raise ValueError("跟随方式必须为 direct 或 smooth")
            mapping = command.get("mapping", "absolute")
            if mapping not in ("absolute", "relative"):
                raise ValueError("映射方式必须为 absolute 或 relative")
            self.connect_master(command.get("leader_port"),
                                command.get("leader_id"))
            raw = check_pose(self.master.get_action())
            target = {key: min(self.limits[key][1], max(self.limits[key][0], raw[key])) for key in JOINTS}
            if mapping == "absolute" and any(abs(observed[key]-target[key]) > 3 for key in JOINTS):
                raise RuntimeError("黑白姿态尚未对齐；请保持黑臂不动，先执行 align，再开始录制")
            # Normal teleop matches the old direct-angle controller. Never
            # silently turn an initial mismatch into a permanent joint offset.
            self.mapping = mapping
            self.offset = ({key: observed[key]-raw[key] for key in JOINTS}
                           if mapping == "relative" else {key: 0.0 for key in JOINTS})
            self.tracking = tracking
            self.filter = (DirectTracker if tracking == "direct" else TrackingFilter)(observed, self.limits)
            TAKES.mkdir(parents=True, exist_ok=True)
            self.take_path = TAKES / f"{item['id']}_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}.jsonl"
            self.stream = self.take_path.open("x", encoding="utf-8", buffering=1)
            self.frames = 0; self.record_started = self.last_sync = self.last_tick = time.perf_counter()
            self.expression = item["id"]
            atomic_json(self.take_path.with_suffix(".meta.json"), {
                "expression": item["id"], "name": item["name"], "status": "recording",
                "started_at": datetime.now().isoformat(),
                "mapping": "absolute_calibrated_degrees" if mapping == "absolute" else "relative_to_take_start",
                "tracking": self.tracking,
                "software_velocity_limit": None if self.tracking == "direct" else {"body_deg_s": 40, "gripper_percent_s": 80},
                "units": {"body": "degrees", "gripper": "percent_0_100"},
                "follower_start": observed, "leader_start": raw, "offset": self.offset,
                "action_source": "actual commanded follower position; observed and raw leader also recorded"})
            atomic_json(self.runtime / "latest_take.json", {"path": str(self.take_path), "expression": self.expression})
            self.mode, self.phase = "teleop", "人工编舞录制中"
            print(f"HUMAN_RECORDING {item['name']} {self.take_path}", flush=True)
            return
        if kind in ("prepare", "replay"):
            self.clip_rows, self.clip_times = load_clip(Path(command["file"]))
            # Replay direct human commands with their original timing. The old
            # smoothing velocity cap does not apply to these recorded frames.
            self.clip_direct = all(row.get("tracking") == "direct" for row in self.clip_rows)
            for row in self.clip_rows: check_pose(row["action"], self.limits)
            for previous, current in zip(self.clip_rows, self.clip_rows[1:]):
                dt = current["t"]-previous["t"]
                if dt > .25: raise RuntimeError("片段包含长时间缺帧；不直接回放")
                for key in JOINTS:
                    maximum = 80 if key == "gripper.pos" else 40
                    if not self.clip_direct and abs(current["action"][key]-previous["action"][key]) > maximum*dt+.01:
                        raise RuntimeError("片段超出本轮人工遥操的速度范围；不直接回放")
            first = self.clip_rows[0]["action"]
            if kind == "prepare":
                raised = dict(planning_start)
                raised["shoulder_lift.pos"] = min(planning_start["shoulder_lift.pos"], first["shoulder_lift.pos"])
                self.prepare_targets = [dict(first)]
                self.motion = compile_pose_motion(planning_start, raised, self.limits, "先抬肩至片段起始高度")
                self.mode, self.phase = "motion", "先抬肩至片段起始高度"
            else:
                if any(abs(observed[key]-first[key]) > 5 for key in JOINTS):
                    raise RuntimeError("尚未处于候选片段起始位；先 prepare，不直接从落桌位播放")
                self.mode, self.phase = "replay", "回放待确认的人工片段"
            self.started = time.perf_counter(); self.last_sent = dict(planning_start)
            return
        raise ValueError("未知人工编舞命令："+kind)

    def step(self, now):
        if self.mode == "motion":
            super().step(now)
            if self.mode == "hold" and self.prepare_targets:
                target = self.prepare_targets.pop(0)
                observed = planning_pose(pose_from_bus(self.arm.bus), self.limits)
                self.motion = compile_pose_motion(observed, target, self.limits, "平滑进入候选动作起始位")
                self.last_sent = dict(observed); self.started = now; self.mode = "motion"
            return
        if self.mode == "teleop":
            raw = check_pose(self.master.get_action())
            target = {key: raw[key]+self.offset[key] for key in JOINTS}
            action, self.limit_clamped = self.filter.update(target, now-self.last_tick)
            self.arm.send_action(action)
            observed = pose_from_bus(self.arm.bus)
            self.pose = observed; self.last_sent = action; self.last_tick = now
            self.stream.write(json.dumps({"frame": self.frames, "t": now-self.record_started,
                "action": action, "observed": observed, "leader": raw,
                "tracking": self.tracking,
                "limit_clamped": self.limit_clamped}, ensure_ascii=False, separators=(",", ":"))+"\n")
            self.frames += 1
            if now-self.last_sync >= 1:
                self.stream.flush(); os.fsync(self.stream.fileno()); self.last_sync = now
            return
        if self.mode == "replay":
            timestamp = self.clip_times[0]+now-self.started
            right = bisect.bisect_left(self.clip_times, timestamp)
            finished = right >= len(self.clip_times)
            if finished:
                action = dict(self.clip_rows[-1]["action"])
            elif right == 0:
                action = dict(self.clip_rows[0]["action"])
            else:
                left = right-1
                alpha = (timestamp-self.clip_times[left])/(self.clip_times[right]-self.clip_times[left])
                action = {key: self.clip_rows[left]["action"][key]+alpha*(self.clip_rows[right]["action"][key]-self.clip_rows[left]["action"][key]) for key in JOINTS}
            if not self.clip_direct and any(abs(action[key]-self.last_sent[key]) > 2 for key in BODY_JOINTS):
                raise RuntimeError("回放目标跳变，停止新增运动")
            self.arm.send_action(action); self.last_sent = dict(action)
            if finished:
                self.mode, self.phase = "hold", "人工片段回放完成；保持力矩"

    def snapshot(self):
        value = super().snapshot()
        value.update({"session_kind": "human_choreography", "recording": self.stream is not None,
            "expression": self.expression, "take_path": str(self.take_path) if self.take_path else None,
            "tracking": self.tracking,
            "mapping": self.mapping,
            "frames": self.frames, "limit_clamped": self.limit_clamped})
        return value


def send_command(command):
    state = json.loads((RUNTIME / "state.json").read_text(encoding="utf-8"))
    if time.time()-state["heartbeat"] > 3 or state["mode"] in ("closed_torque_retained", "startup_failed"):
        raise RuntimeError("人工遥操会话未启动")
    os.kill(state["pid"], 0)
    identity = f"{time.time_ns()}_{uuid.uuid4().hex[:8]}"
    command["created_at"] = time.time()
    atomic_json(RUNTIME / "inbox" / (identity+".json"), command)
    return identity


def main():
    parser = argparse.ArgumentParser(description="Persistent human recording and replay")
    sub = parser.add_subparsers(dest="command", required=True)
    server = sub.add_parser("serve")
    server.add_argument("--port", required=True)
    server.add_argument("--id", required=True)
    server.add_argument("--fps", type=float, default=60)
    start = sub.add_parser("start"); start.add_argument("expression")
    start.add_argument("--tracking", choices=("direct", "smooth"), default="direct")
    start.add_argument("--mapping", choices=("absolute", "relative"), default="absolute")
    start.add_argument("--leader-port", required=True)
    start.add_argument("--leader-id", required=True)
    align = sub.add_parser("align")
    align.add_argument("--leader-port", required=True)
    align.add_argument("--leader-id", required=True)
    sub.add_parser("finish"); sub.add_parser("hold"); sub.add_parser("status")
    mark = sub.add_parser("mark"); mark.add_argument("label")
    for name in ("prepare", "replay"):
        command = sub.add_parser(name); command.add_argument("file", type=Path)
    close = sub.add_parser("close"); close.add_argument("--support-confirmation", required=True)
    args = parser.parse_args()
    if args.command == "serve": serve(args.port, args.id, args.fps, HumanSession, RUNTIME)
    elif args.command == "status": print((RUNTIME / "state.json").read_text(encoding="utf-8"))
    else:
        command = vars(args)
        if "file" in command: command["file"] = str(command["file"].resolve())
        print("QUEUED "+send_command(command))


if __name__ == "__main__": main()
