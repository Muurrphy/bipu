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

## Record a new label

The recording controller accepts labels from `human_repertoire.json`, independently of the eight published clips. To add a new label, append an object with a unique `id`, `name`, and optional `aliases` to that file's `expressions` array. Then use the ID with `start`. This changes your local recording catalog, not the published motion library.

To select a candidate from a full take:

```sh
python take_tools.py inspect YOUR_TAKE.jsonl --tail 90
python take_tools.py cut YOUR_TAKE.jsonl YOUR_LABEL --start 120 --end 140 --park-start 145
```

The times are illustrative seconds in your full recording. Choose actual boundaries from your own take. The `cut` command returns a candidate path; prepare and replay that path, then archive it with `python take_tools.py archive YOUR_CANDIDATE.jsonl --confirmed` only after checking the selection. For a contribution, use the public data schema and the submission requirements in [CONTRIBUTING.md](../CONTRIBUTING.md).

## Stop and close

`finish` ends a take and holds the follower. `hold` stops new motion commands and closes any active recording. `close --support-confirmation "supported"` ends this controller while deliberately retaining follower torque. There is no portable parking/torque-off command in this release. Use a supported pose and a shutdown/unload procedure appropriate to your hardware and driver; do not rely on killing a process to remove torque.
