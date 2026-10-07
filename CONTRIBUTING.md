# Contributing

Contributions are welcome for offline tools, new motion clips, documentation and independently tested robot adapters. This project is maintained on a best-effort basis; there is no promised response time or hardware certification.

## Questions and proposals

Use [Discussions](https://github.com/Muurrphy/expressive-arm/discussions) for usage questions and demonstrations. Use an issue for a reproducible bug or a specific change proposal. Discuss a substantial hardware port before committing to a large implementation.

## Development

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
(cd tools/recording && python -m unittest test_motion_library test_human_workflow -v)
python examples/read_motion.py curious --output curious-plan.json
```

Offline development does not require LeRobot or a robot. Hardware dependencies are separate in `tools/recording/requirements-hardware.txt`. Do not make tests connect to serial ports or assume a contributor's calibration.

Keep changes focused. Describe the behavior changed and how it was checked. CI tests Python 3.10, 3.12 and 3.13, builds the wheel and source distribution, and checks that both include all eight motions.

## Submit a motion

- Submit only code, data and media you own or have permission to license. Original code and motion data contributions are accepted under MIT.
- Use the documented [JSONL format](docs/data-format.md) with strictly increasing times. Supply a checksum, frame count, duration, intended label and hardware description.
- Exclude the separate preparation/parking steps unless those are explicitly part of the clip. Retain intentional pauses.
- Explain any edited joins or retiming. Do not label generated targets as fresh measured observations.
- Include evidence of replay on your robot. Media has its own license: state it explicitly; do not assume the repository's MIT license covers a submitted video.
- Exclude calibration files, device serial numbers, personal paths, conversation logs and credentials.

## Submit a hardware adapter

Follow the [porting guide](docs/porting.md). Describe the joint/unit conversion, limits, preparation and stop/hold behavior. Provide offline tests and a hardware test report. Clearly separate tested support from an untested proposal. Unvalidated adapters should not become the default controller.

## 中文摘要

欢迎提交离线工具改进、新动作或已验证的硬件适配。使用问题和演示放在 Discussions，可复现的错误放在 Issues。新增动作需说明硬件、数据格式和回放验证情况，保留动作内部停顿，并注明编辑过渡。提交者需拥有相应授权，程序和动作数据按 MIT 贡献；影像需单独说明许可。不要提交个人校准文件、设备序列号、私人路径或对话日志。其他型号应先按适配指南完成验证。
