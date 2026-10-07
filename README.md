# Expressive Arm

Eight expressions performed by a SO-ARM101 — through posture, orientation, timing and pauses.

[中文说明](README.zh-CN.md) · [Watch all eight films](https://muurrphy.github.io/desktop-robot-murphy-demo/expressions/) · [Portfolio](https://muurrphy.github.io/desktop-robot-murphy-demo/portfolio/)

![Eight expressions](docs/eight-expressions.jpg)

The motion was choreographed by Meichen Liu using a leader arm. AI assisted with continuous recording, troubleshooting, trimming and tooling. Each selected performance was replayed on the follower and confirmed before being archived. The project was inspired by Apple's ELEGNT lamp research.

| Expression | What the performance explores |
| --- | --- |
| Sleepy / 困倦 | Struggling to stay awake, briefly recovering, then curling into sleep |
| Disappointed / 失落 | Hesitating to speak, turning away and lowering the head |
| Hesitant / 犹豫 | Moving toward an action while remaining undecided |
| Happy / 开心 | Puppy-like head tilts, affirmative nods and a turning sway |
| Startled / 震惊 | One continuous performance with fear and surprise |
| Curious / 好奇 | Turning toward and exploring something unfamiliar |
| Playful / 玩耍 | Probing and stacking blocks, then inviting attention or asking for help |
| Angry / 生气 | Sulking and ending with the back turned toward the observer |

## Start without hardware

```sh
python -m pip install .
expressive-arm list
expressive-arm inspect sleepy
expressive-arm validate
expressive-arm plot curious --output curious.svg
expressive-arm crop curious --start 2 --end 8 --output curious-cut.jsonl
```

The package uses the Python standard library and never opens a serial port. The wheel includes all eight trajectories and their checksums. `t` is seconds relative to the selected performance; the five body joints use calibrated degrees and the gripper uses 0–100 percent. Film durations differ from motion durations because the edited films include pauses and camera lead-in/out.

## Record and replay on a real SO-101

The implementation used for these performances is in [tools/recording](tools/recording). It supports a single persistent follower connection, direct absolute-angle leader following, append-only recording, hold, smooth preparation and replay. Device ports and cached calibration IDs must be supplied by the operator. See [the recording guide](docs/recording.md) and [hardware notes](docs/hardware.md).

The recording tools were tested on macOS, Python 3.12 and LeRobot 0.6.0. Offline tools are tested in CI on Linux. Other operating systems and robot variants have not been validated.

## Method and scope

See [the making process](docs/method.md), [data format](docs/data-format.md) and [research references](docs/references.md). These are author-confirmed performances, not a validated universal emotion classifier. No audience recognition study has been run. The arm is not translating sign language; sign language was studied as a reference for visual communication.

## Development

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
cd tools/recording
python -m unittest test_motion_library test_human_workflow -v
```

Code and motion data: MIT. Demonstration films and photographs: © 2026 Meichen Liu, linked for viewing; they are not covered by the software license. Third-party dependencies retain their own licenses. No Apple code or Apple assets are included.

The recording tools also retain the early AI-generated reference catalog for offline comparison. Those 25 templates are not the eight confirmed performances in the package.
