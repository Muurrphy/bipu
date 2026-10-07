# Continuous recording and replay

The hardware scripts preserve the implementation used for the filmed work. They are standalone tools; install the pinned hardware dependencies separately:

```sh
cd tools/recording
python -m pip install -r requirements-hardware.txt
python human_controller.py serve --port /dev/YOUR_FOLLOWER --id YOUR_CACHED_FOLLOWER_ID
```

In another terminal, while the follower is reliably supported and the leader remains still:

```sh
python human_controller.py align --leader-port /dev/YOUR_LEADER --leader-id YOUR_CACHED_LEADER_ID
python human_controller.py start sleepy --leader-port /dev/YOUR_LEADER --leader-id YOUR_CACHED_LEADER_ID
# Explore, pause in the air between attempts, repeat, then:
python human_controller.py finish
python human_controller.py status
```

`serve` owns the follower serial port for the entire session. `finish` closes the recording and holds position. It does not shut down torque. `start` follows absolute calibrated angles directly by default; `--mapping relative` and `--tracking smooth` change that behavior explicitly.

Raw recordings are in `人工编舞/完整录制`; inspect `take_tools.py --help` to extract and archive a candidate. Public motion data is compatible with `prepare` and `replay`:

```sh
python human_controller.py prepare ../../src/expressive_arm/motions/sleepy.jsonl
python human_controller.py replay ../../src/expressive_arm/motions/sleepy.jsonl
python human_controller.py hold
```

Wait for `status` to report hold/completion before sending the next command. Replay ends in the final expression pose, without adding a parking motion. `close --support-confirmation "supported"` closes the session while retaining torque. A supported parking/unload sequence is a separate operator action; unplugging or closing a terminal is not that sequence.

This release does not execute the local, machine-specific filming or parking scripts. For a new arm, inspect all five calibrated angle ranges, gripper units and starting pose before any replay. macOS was the hardware-tested system; Linux serial access, lsof and device naming may require adaptation. Windows is not supported by the recording tools because they use Unix file locking.
