"""One persistent controller for computer-operated SO-101 expressions.

Only this process owns the serial port. CLI commands are atomic local files,
not additional motor connections. No configure(), calibration write,
disable_torque(), or automatic parking is performed. SIGINT/SIGTERM mean HOLD.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import signal
import subprocess
import shutil
import time
import uuid
from pathlib import Path

from motion_library import JOINTS, ROOT, VELOCITY, check_pose, compile_motion, compile_pose_motion, read_catalog, sample_motion

RUNTIME = ROOT / "runtime"
BODY_JOINTS = tuple(key for key in JOINTS if key != "gripper.pos")
BODY_LIMIT_MARGIN_DEG = 2.0


def atomic_json(path: Path, data: dict) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    os.replace(temp,path)


def pose_from_bus(bus) -> dict:
    return check_pose({name+".pos":float(value) for name,value in bus.sync_read("Present_Position").items()})


def hardware_limits(bus) -> dict:
    limits = {}
    for name, calibration in bus.calibration.items():
        if name == "gripper":
            limits[name+".pos"] = (0.0,100.0)
        else:
            half = (calibration.range_max-calibration.range_min)/2
            # Local STS3215 implementation uses resolution-1 == 4095.
            limits[name+".pos"] = (-half*360/4095+BODY_LIMIT_MARGIN_DEG,
                                   half*360/4095-BODY_LIMIT_MARGIN_DEG)
    return limits


def planning_pose(observed: dict, limits: dict) -> dict:
    """Validate a measurement against calibration; bound only the next goal.

    Servo tracking error can put the measured angle just outside the inward
    command margin. That is not a command to move beyond the target limits.
    Preserve the actual measurement in logs, and keep every planned goal inside
    the unchanged command limits. Measurements beyond calibration still fail.
    """
    measured = check_pose(observed)
    physical_limits = {key: (lo-BODY_LIMIT_MARGIN_DEG, hi+BODY_LIMIT_MARGIN_DEG)
                       if key in BODY_JOINTS else (lo, hi)
                       for key, (lo, hi) in limits.items()}
    check_pose(measured, physical_limits)
    return check_pose({key: min(limits[key][1], max(limits[key][0], value))
                       for key, value in measured.items()}, limits)


def acquire_without_reconfigure(bus) -> tuple[dict,dict]:
    """Reads/checks first; latch present raw positions before enabling torque."""
    if not bus.is_calibrated:
        raise RuntimeError("实机校准与缓存不一致；拒绝自动校准或改写舵机")
    modes = bus.sync_read("Operating_Mode",normalize=False)
    if any(value != 0 for value in modes.values()):
        raise RuntimeError("有舵机不在位置模式；拒绝自动重配置")
    raw = bus.sync_read("Present_Position",normalize=False)
    if set(raw) != set(bus.motors):
        raise RuntimeError("六个舵机没有全部回应")
    for name,value in raw.items():
        calibration = bus.calibration[name]
        if not calibration.range_min <= value <= calibration.range_max:
            raise RuntimeError(f"当前原始位置超出校准范围：{name}={value}")
    pose = pose_from_bus(bus)
    limits = hardware_limits(bus)
    planning_pose(pose,limits)
    # Exact raw goal prevents a jump to an old stored goal when torque comes on.
    bus.sync_write("Goal_Position",raw,normalize=False)
    bus.enable_torque()
    torque = bus.sync_read("Torque_Enable",normalize=False)
    if any(value != 1 for value in torque.values()):
        raise RuntimeError("部分舵机未进入保持力矩状态；不发送运动轨迹")
    return pose,limits


class Session:
    def __init__(self, arm, limits: dict, pose: dict, runtime: Path = RUNTIME):
        self.arm, self.limits, self.pose, self.runtime = arm,limits,dict(pose),runtime
        self.catalog = read_catalog()
        self.mode, self.phase = "hold","保持当前位置"
        self.neutral = None
        self.empty_gripper = False
        self.motion = None
        self.started = 0.0
        self.last_sent = dict(pose)
        self.last_error = None
        self.faulted = False
        self.signal_hold = False
        self.last_command = None
        self.last_command_result = None
        self.running = True

    def hold(self, reason: str = "保持当前位置") -> None:
        # Stop generating trajectory frames even if the subsequent read fails.
        self.mode, self.phase, self.motion = "hold",reason,None
        observed = pose_from_bus(self.arm.bus)
        target = planning_pose(observed,self.limits)
        self.arm.send_action(target)
        self.pose, self.last_sent = dict(observed),dict(target)

    def accept(self, command: dict) -> None:
        kind = command["command"]
        if kind == "hold":
            self.hold()
            return
        if self.faulted:
            raise RuntimeError("会话处于故障保持状态；只接受 hold，请先检查实物和错误记录")
        if self.mode != "hold":
            raise RuntimeError("动作尚未结束；先 hold，不叠加新动作")
        observed = planning_pose(pose_from_bus(self.arm.bus),self.limits)
        if kind == "neutral":
            if command.get("airborne_confirmed") is not True:
                raise RuntimeError("必须现场确认悬空起始位及周围动作空间")
            self.neutral = dict(observed)
            self.empty_gripper = command.get("empty_gripper") is True
            self.phase = "悬空起始位已由操作者确认"
            atomic_json(self.runtime/"neutral.json",self.neutral)
            return
        if kind == "play":
            if self.neutral is None:
                raise RuntimeError("未确认悬空起始位；当前可能是桌面休息位，拒绝播放")
            if max(abs(observed[k]-self.neutral[k]) for k in BODY_JOINTS) > 4:
                raise RuntimeError("当前位置偏离起始位超过 4°；不自动移动回起始位")
            move_gripper = command.get("with_gripper",False)
            if move_gripper and not self.empty_gripper:
                raise RuntimeError("未确认夹爪空载；拒绝开合夹爪")
            anchor = dict(self.neutral)
            if not move_gripper:
                anchor["gripper.pos"] = observed["gripper.pos"]
            self.motion = compile_motion(self.catalog,command["expression"],anchor,
                                         command.get("level","light"),command.get("tempo",1.0),
                                         move_gripper,self.limits)
            # Resolve the small measured start error smoothly, rather than snap.
            self.motion["segments"][0]["from"] = dict(observed)
            first = self.motion["segments"][0]
            minimum = max(1.875*abs(first["to"][k]-observed[k])/VELOCITY[k] for k in JOINTS)
            from motion_library import ACCELERATION
            minimum = max(minimum,*(math.sqrt((10/math.sqrt(3))*abs(first["to"][k]-observed[k])/ACCELERATION[k]) for k in JOINTS))
            extra = max(0.0,minimum-first["move_s"])
            first["move_s"] += extra
            for segment in self.motion["segments"][1:]: segment["start"] += extra
            self.motion["duration_s"] += extra
        elif kind == "lift":
            if command.get("clearance_confirmed") is not True:
                raise RuntimeError("整段抬肩需要已确认抬起方向的完整路径")
            target = dict(observed)
            target["shoulder_lift.pos"] = float(command["target"])
            difference = target["shoulder_lift.pos"] - observed["shoulder_lift.pos"]
            # This device's verified shoulder convention: negative is up.
            if not math.isfinite(difference) or not -90 <= difference <= 0:
                raise RuntimeError("整段抬肩只接受向上且不超过 90° 的目标")
            self.motion = compile_pose_motion(observed, target, self.limits)
            self.neutral = None
        elif kind == "nudge":
            if command.get("clearance_confirmed") is not True:
                raise RuntimeError("小步移动仍需现场确认这一段路径已清空")
            joint = command["joint"]
            delta = float(command["delta"])
            if joint not in BODY_JOINTS or not math.isfinite(delta) or abs(delta) > 8:
                raise RuntimeError("只允许五个运动关节，每次小步不超过 8°")
            target = dict(observed); target[joint] += delta
            check_pose(target,self.limits)
            from motion_library import ACCELERATION
            duration = max(2.0,1.875*abs(delta)/VELOCITY[joint],math.sqrt((10/math.sqrt(3))*abs(delta)/ACCELERATION[joint]))
            self.motion = {"id":"nudge","name":"小步移动","neutral":target,"duration_s":duration,
                           "segments":[{"label":"单关节小步移动","start":0.0,"move_s":duration,"hold_s":0.0,"from":observed,"to":target}]}
            # Any reposition invalidates the previous airborne anchor.
            self.neutral = None
        elif kind == "close":
            if command.get("support_confirmation") != "我已托住白色臂，可以泄力。":
                raise RuntimeError("关闭会话前须按项目规范确认白色臂已被承托")
            self.hold("会话结束；仍保留力矩")
            self.running = False
            return
        else:
            raise ValueError(f"Unknown command: {kind}")
        self.last_sent = dict(observed)
        self.mode = "motion"
        self.started = time.perf_counter()
        self.phase = self.motion["segments"][0]["label"]

    def step(self, now: float) -> None:
        if self.mode != "motion":
            return
        if now-self.started > self.motion["duration_s"]+0.25:
            # A stalled loop must not jump across missed trajectory samples.
            self.hold("动作计时中断；保持当前位置")
            return
        action,label = sample_motion(self.motion,now-self.started)
        check_pose(action,self.limits)
        if any(abs(action[k]-self.last_sent[k]) > 1.0 for k in BODY_JOINTS):
            raise RuntimeError("控制循环延迟造成目标跳变；拒绝继续")
        self.arm.send_action(action)
        self.last_sent, self.pose, self.phase = dict(action),dict(action),label
        if now-self.started >= self.motion["duration_s"]:
            self.mode, self.phase, self.motion = "hold","动作结束；保持力矩",None

    def snapshot(self) -> dict:
        return {"pid":os.getpid(),"heartbeat":time.time(),"controller_protocol":2,"mode":self.mode,"phase":self.phase,
                "pose":self.pose,"limits":self.limits,"neutral_confirmed":self.neutral is not None,
                "empty_gripper_confirmed":self.empty_gripper,"faulted":self.faulted,
                "last_error":self.last_error,"last_command":self.last_command,
                "last_command_result":self.last_command_result,"disable_torque_on_disconnect":False}


def serve(port: str, device_id: str, fps: float, session_factory=Session, runtime: Path = RUNTIME) -> None:
    if not math.isfinite(fps) or not 10 <= fps <= 60:
        raise ValueError("FPS must be in 10..60")
    runtime.mkdir(parents=True,exist_ok=True)
    inbox = runtime/"inbox"; inbox.mkdir(exist_ok=True)
    done = runtime/"processed"; done.mkdir(exist_ok=True)
    lock = (runtime/"serial.lock").open("w")
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    # Discard queued commands from a previous process: never execute stale moves.
    for path in inbox.glob("*.json"):
        os.replace(path,done/("stale_"+path.name))
    occupied = subprocess.run([shutil.which("lsof") or "/usr/sbin/lsof","-t",port],capture_output=True,text=True)
    if occupied.stdout.strip():
        raise RuntimeError(f"串口已被其他进程占用：{occupied.stdout.strip()}")
    # Hardware imports intentionally stay out of offline export and tests.
    from lerobot.robots.so_follower.config_so_follower import SO101FollowerConfig
    from lerobot.robots.so_follower.so_follower import SO101Follower
    arm = SO101Follower(SO101FollowerConfig(port=port,id=device_id,use_degrees=True,
                                           disable_torque_on_disconnect=False))
    session = None
    try:
        arm.bus.connect()
        pose,limits = acquire_without_reconfigure(arm.bus)
        session = session_factory(arm,limits,pose,runtime=runtime)
        def signal_handler(signum,frame):
            session.signal_hold = True
        signal.signal(signal.SIGINT,signal_handler)
        signal.signal(signal.SIGTERM,signal_handler)
        atomic_json(runtime/"state.json",session.snapshot())
        print("COMPUTER_CONTROL_READY HOLDING_CURRENT_POSE TORQUE_HELD",flush=True)
        print(json.dumps(session.snapshot(),ensure_ascii=False),flush=True)
        next_state = 0.0
        previous_tick = time.perf_counter()
        while session.running:
            tick = time.perf_counter()
            try:
                if session.signal_hold:
                    session.signal_hold = False
                    session.hold("收到中断；保持当前位置，未卸力")
                if session.mode in ("motion","teleop","replay") and tick-previous_tick > 0.15:
                    session.hold("控制循环延迟；保持当前位置")
                for path in sorted(inbox.glob("*.json")):
                    try:
                        command = json.loads(path.read_text(encoding="utf-8"))
                        session.last_command = path.stem
                        if time.time()-command.get("created_at",0) > 10:
                            raise RuntimeError("命令已过期，拒绝执行")
                        session.accept(command)
                        # Setup while held can include a first leader connection
                        # or loading a clip. Start the watchdog clock afterwards;
                        # that setup delay is not a missed active control frame.
                        if command["command"] in ("start", "align", "prepare", "replay"):
                            tick = time.perf_counter()
                        session.last_command_result = "accepted"
                        print("COMMAND_ACCEPTED "+path.stem+" "+command["command"],flush=True)
                    except Exception as error:
                        session.last_command_result = "rejected"
                        session.last_error = str(error)
                        print("COMMAND_REJECTED "+str(error),flush=True)
                    finally:
                        os.replace(path,done/path.name)
                session.step(time.perf_counter())
                if tick >= next_state:
                    if not session.faulted:
                        session.pose = pose_from_bus(arm.bus)
                        torque = arm.bus.sync_read("Torque_Enable",normalize=False)
                        if any(value != 1 for value in torque.values()):
                            raise RuntimeError("检测到舵机失去力矩；停止新增动作，不自动重新加力")
                    atomic_json(runtime/"state.json",session.snapshot())
                    next_state = tick+0.5
            except Exception as error:
                session.last_error,session.faulted = str(error),True
                session.mode,session.motion,session.phase = "hold",None,"故障；停止新增动作，未卸力"
                if hasattr(session,"close_recording"):
                    session.close_recording("fault")
                # Existing servo goal and torque are left untouched. Never
                # issue more motor commands automatically after a bus fault.
                atomic_json(runtime/"state.json",session.snapshot())
                print("FAULT_TORQUE_NOT_RELEASED "+str(error),flush=True)
                time.sleep(0.5)
            previous_tick = tick
            time.sleep(max(0.0,1/fps-(time.perf_counter()-tick)))
    except Exception as error:
        if session is None:
            atomic_json(runtime/"state.json",{"pid":os.getpid(),"heartbeat":time.time(),"mode":"startup_failed","last_error":str(error)})
        raise
    finally:
        if session is not None and hasattr(session,"close_recording"):
            session.close_recording("session_close")
        if arm.bus.is_connected:
            arm.bus.disconnect(disable_torque=False)
        if session is not None:
            snapshot = session.snapshot(); snapshot["mode"] = "closed_torque_retained"
            atomic_json(runtime/"state.json",snapshot)
        lock.close()


def send_command(command: dict) -> str:
    state = json.loads((RUNTIME/"state.json").read_text(encoding="utf-8"))
    if state["mode"] in ("startup_failed","closed_torque_retained") or time.time()-state["heartbeat"] > 3:
        raise RuntimeError("没有正在运行的控制会话")
    os.kill(state["pid"],0)
    identity = f"{time.time_ns()}_{uuid.uuid4().hex[:8]}"
    command["created_at"] = time.time()
    atomic_json(RUNTIME/"inbox"/(identity+".json"),command)
    return identity


def main() -> None:
    parser = argparse.ArgumentParser(description="Persistent computer controller; no automatic torque release")
    sub = parser.add_subparsers(dest="command",required=True)
    server = sub.add_parser("serve")
    server.add_argument("--port",required=True)
    server.add_argument("--id",required=True)
    server.add_argument("--fps",type=float,default=60)
    sub.add_parser("status"); sub.add_parser("hold")
    neutral = sub.add_parser("neutral")
    neutral.add_argument("--airborne-confirmed",action="store_true",required=True)
    neutral.add_argument("--empty-gripper",action="store_true")
    play = sub.add_parser("play")
    play.add_argument("expression")
    play.add_argument("--level",choices=["light","medium","strong"],default="light")
    play.add_argument("--tempo",type=float,default=1.0)
    play.add_argument("--with-gripper",action="store_true")
    nudge = sub.add_parser("nudge")
    nudge.add_argument("joint",choices=BODY_JOINTS)
    nudge.add_argument("delta",type=float)
    nudge.add_argument("--clearance-confirmed",action="store_true",required=True)
    lift = sub.add_parser("lift")
    lift.add_argument("--target",type=float,required=True)
    lift.add_argument("--clearance-confirmed",action="store_true",required=True)
    close = sub.add_parser("close")
    close.add_argument("--support-confirmation",required=True)
    args = parser.parse_args()
    if args.command == "serve": serve(args.port,args.id,args.fps)
    elif args.command == "status": print((RUNTIME/"state.json").read_text(encoding="utf-8"))
    else: print("QUEUED "+send_command(vars(args)))


if __name__ == "__main__":
    main()
