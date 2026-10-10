# Bipu

An SO-101 robot pet powered by [Jev](https://docs.typesafe.ai/introduction/quickstart). Send messages through Telegram or the local interface; Bipu responds with recorded movement and electronic calls. It also has a choreography mode for arranging motions and sounds.

[中文 README](README.zh-CN.md) · [Watch Bipu](https://muurrphy.github.io/desktop-robot-murphy-demo/expressions/?mode=pet) · [Download 0.3 beta](https://github.com/Muurrphy/bipu/releases/tag/v0.3.0b1)

[![Offline checks](https://github.com/Muurrphy/bipu/actions/workflows/tests.yml/badge.svg)](https://github.com/Muurrphy/bipu/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/code%20%26%20motion%20data-MIT-blue.svg)](LICENSE)

I found Apple's [ELEGNT lamp robot](https://machinelearning.apple.com/research/elegnt-expressive-functional-movement) really cute. I had an SO-101 at home and wanted to try making a little toy of my own. Bipu grew from eight recorded expressions into a pet that can react to messages. I hope it adds a little fun to playing with robot arms.

## Two ways to use Bipu

| | Pet mode | Choreography mode |
| --- | --- | --- |
| Input | Telegram or local messages, plus time since the last interaction | A timeline of recorded motions and chosen sounds |
| Behavior | Jev interprets the message within local rules and selects an allowed response; Bipu can also wait or become sleepy | Play a repeatable sequence for a film, installation or your own application |
| Demonstration | [Bipu's small world](https://muurrphy.github.io/desktop-robot-murphy-demo/expressions/?mode=pet) | [The octopus scene](https://muurrphy.github.io/desktop-robot-murphy-demo/expressions/?mode=choreography) |

The pet film was edited from recorded performances with a composed message-and-sound sequence. The octopus scene is a scripted multi-device performance. A real private Telegram message has separately been verified through Jev to a motion and call in local preview. The eight individual motions have been replayed on the author's SO-101; physical transitions for autonomous pet mode still need review.

## Try it on your computer

```sh
git clone https://github.com/Muurrphy/bipu.git
cd bipu
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
bipu serve --open
```

Starts paused in preview mode. The default local rules work without an API key. To use Jev, configure a TypeSafe key locally; Telegram additionally needs your own bot token and private chat allowlist. No serial connection opens at startup.

[Runtime setup and behavior](docs/bipu.md) · [中文使用说明](docs/bipu.zh-CN.md) · [Example score](examples/bipu-score.json)

The package includes eight motion trajectories and a grouped sound index. Audio files and personal films are not bundled; point it to your own licensed assets or use silent preview. The Python package and original `expressive-arm` command retain their names for compatibility; the pet command is `bipu`.

![Eight expressions performed on a SO-101](docs/eight-expressions.jpg)

## What you can use it for

- **SO-101 interaction prototypes:** add a motion response to an event in your own application, after checking the motion on your calibrated setup.
- **Motion authoring:** record with a leader arm, select a take, preview joint trajectories, and replay a clip on a follower.
- **Other robot arms or animation:** export timestamped joint targets to CSV and adapt the choreography to your own model. Different kinematics require retargeting.
- **Teaching and HRI experiments:** use a small, inspectable motion library as a starting point for movement design or a future perception study.

## Motion library

| ID | Chinese label | Trajectory duration | Frames | Demonstration |
| --- | --- | ---: | ---: | --- |
| `sleepy` | 困倦 | 31.37 s | 1,618 | [Video](https://muurrphy.github.io/desktop-robot-murphy-demo/expressions/media/sleepy.mp4) |
| `disappointed` | 失落 | 12.00 s | 630 | [Video](https://muurrphy.github.io/desktop-robot-murphy-demo/expressions/media/disappointed.mp4) |
| `hesitant` | 犹豫 | 15.52 s | 805 | [Video](https://muurrphy.github.io/desktop-robot-murphy-demo/expressions/media/hesitant.mp4) |
| `happy` | 开心 | 11.69 s | 620 | [Video](https://muurrphy.github.io/desktop-robot-murphy-demo/expressions/media/happy.mp4) |
| `startled` | 震惊 | 10.83 s | 566 | [Video](https://muurrphy.github.io/desktop-robot-murphy-demo/expressions/media/startled.mp4) |
| `curious` | 好奇 | 16.63 s | 780 | [Video](https://muurrphy.github.io/desktop-robot-murphy-demo/expressions/media/curious.mp4) |
| `playful` | 玩耍 | 41.85 s | 2,010 | [Video](https://muurrphy.github.io/desktop-robot-murphy-demo/expressions/media/playful.mp4) |
| `angry` | 生气 | 23.04 s | 1,199 | [Video](https://muurrphy.github.io/desktop-robot-murphy-demo/expressions/media/angry.mp4) |

The durations above describe motion data. Edited films have different durations and are not frame-synchronized datasets. Emotion labels describe the intended expression; no audience recognition study has been conducted. The playful clip uses blocks at fixed locations and has no object detection or autonomous success/failure logic.

## Quick start: no robot required

Python 3.10 or later. The offline package has no runtime dependencies and does not access serial ports.

```sh
git clone https://github.com/Muurrphy/bipu.git
cd bipu
python -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
expressive-arm list
expressive-arm validate
expressive-arm inspect curious
expressive-arm plot curious --output curious.svg
expressive-arm export curious --output curious.csv
expressive-arm crop curious --start 2 --end 8 --output curious-cut.jsonl
```

The [release](https://github.com/Muurrphy/bipu/releases/tag/v0.3.0b1) also provides a wheel, source distribution, full repository ZIP, and SHA-256 checksums. To use a downloaded wheel: `python -m pip install ./expressive_arm-0.3.0b1-py3-none-any.whl`. This package has not been published to PyPI.

In Python:

```python
from expressive_arm.trajectory import load

rows = load("curious")  # verifies checksum and schema
first_time = rows[0]["t"]
first_target = rows[0]["action"]
```

See [the offline integration example](examples/read_motion.py) and [data format](docs/data-format.md). Five joint channels are calibrated degrees; `gripper.pos` is opening percent (0–100). These are joint targets, not Cartesian poses.

## Hardware compatibility

| Setup | Status | Path |
| --- | --- | --- |
| SO-101 leader/follower, Feetech servos | Tested on the author's hardware | [Recording and replay](docs/recording.md) |
| Other SO-101 builds or calibration | Needs local validation | Check frames, signs, ranges, starting pose and clearance |
| SO-100 or other brands | No hardware validation or driver supplied | [Porting guide](docs/porting.md) |
| Offline tools | Linux CI: Python 3.10 / 3.12 / 3.13; local macOS checks | CLI and Python API |

Hardware tools are in `tools/recording`, separate from the offline package. Tested hardware environment: macOS, Python 3.12, LeRobot 0.6.0. The tools use one persistent follower connection, direct following of absolute calibrated leader angles, continuous recording, and explicit prepare/replay/hold commands. They require your own cached calibration IDs and ports. Windows hardware control is not supported.

Start with the [hardware notes](docs/hardware.md), then the [recording guide](docs/recording.md). The SO-101-specific preparation path and shutdown behavior must be reviewed for your setup. Finishing a take or closing the controller **does not disable motor torque**. A new arm is not validated by passing offline checks.

## Contributing and support

[CONTRIBUTING.md](CONTRIBUTING.md) explains development, motion submissions, and hardware ports. Use [Discussions](https://github.com/Muurrphy/bipu/discussions) for usage questions and demonstrations; use [Issues](https://github.com/Muurrphy/bipu/issues) for reproducible bugs or concrete proposals. Contributions to other arm models should include an adapter, configuration, and a test report.

For the upstream SO-101 / LeRobot community, see the [official hardware repository](https://github.com/TheRobotStudio/SO-ARM100) and its [LeRobot Discord link](https://discord.gg/ggrqhPTsMe). Bipu is an independent project, not an official LeRobot component.

## License, attribution and scope

Code, documentation text and motion JSON/JSONL data are [MIT licensed](LICENSE). You can modify and redistribute them, including for commercial use, while retaining the license notice. The repository's photographs and linked demonstration films are copyrighted by Meichen Liu and are **not** covered by MIT; see [media licensing](docs/media-license.md).

Use [CITATION.cff](CITATION.cff) when citing this release. Research inspiration is listed in [references](docs/references.md). The library contains eight recorded motion trajectories for playback and adaptation. See [authoring and validation notes](docs/method.md) and [CHANGELOG.md](CHANGELOG.md).
