# Bipu

基于 [Jev](https://docs.typesafe.ai/introduction/quickstart) 的机械小宠物，用动作和电子短叫回应消息。

[English README](README.md) · [看 Bipu](https://muurrphy.github.io/desktop-robot-murphy-demo/expressions/?mode=pet) · [下载 0.3 测试版](https://github.com/Muurrphy/bipu/releases/tag/v0.3.0b1)

我觉得苹果的 [ELEGNT 台灯机器人](https://machinelearning.apple.com/research/elegnt-expressive-functional-movement)很可爱，家里刚好有一台 SO-101，也想试着做个小玩具。Bipu 从八条动作慢慢有了根据消息作反应的宠物模式，希望能给玩机械臂的人添一点乐趣。

画外的人往它的小世界里放东西，也给它发消息。比如“给你两块积木，自己玩一会儿”，它用动作和短叫回应，不说人话。

## 两种玩法

| | 宠物模式 | 编排模式 |
| --- | --- | --- |
| 输入 | Telegram 或本地消息，以及多久没互动 | 录好的动作与声音时间线 |
| 行为 | Jev 结合消息和近期状态，从规则允许的动作与叫声中选择；空闲时也可等待或入睡 | 按固定时间线播放，方便拍视频或接到自己的应用 |
| 视频 | [Bipu 的小世界](https://muurrphy.github.io/desktop-robot-murphy-demo/expressions/?mode=pet) | [章鱼场景联动](https://muurrphy.github.io/desktop-robot-murphy-demo/expressions/?mode=choreography) |

宠物短片用已有实拍加聊天框和叫声编排，章鱼片按预设时间线联动。真实 Telegram 私聊经过 Jev 选择动作和声音的链路已在本地预览验证。八条单独动作曾在我的 SO-101 上回放，宠物模式的实机动作衔接还需要现场验证。

## 先在电脑上试

```sh
git clone https://github.com/Muurrphy/bipu.git
cd bipu
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
bipu serve --open
```

启动后默认暂停并使用预览。没有密钥时可先用本地规则，使用 Jev 需在本机配置 TypeSafe key，接 Telegram 还需自己的 bot token 和私人账号允许列表。启动不会连接串口。

[完整使用说明](docs/bipu.zh-CN.md) · [English runtime docs](docs/bipu.md) · [编排示例](examples/bipu-score.json)

安装包包含八条轨迹和分组声音索引，音频与个人视频不在安装包内，可接自己的合法素材或先静音预览。Python 包和原有 `expressive-arm` 命令保留名称以兼容旧用法，宠物入口是 `bipu`。

![SO-101 的八种表达](docs/eight-expressions.jpg)

## 可以用来做什么

- **SO-101 交互原型：** 在自己的应用事件发生时播放动作。接入之前，需要先在自己的校准和现场条件下验证。
- **制作新动作：** 通过 Leader 录制轨迹，选择片段，查看关节曲线，再用 Follower 回放。
- **改编到其他机械臂或动画：** 导出带时间戳的 CSV，作为动作设计参考。不同结构需要重新映射，不能直接套用关节角度。
- **教学和人机交互实验：** 用八条可检查的轨迹学习运动表达，也可在此基础上设计观众识别实验。

## 八条动作

| ID | 名称 | 轨迹时长 | 帧数 |
| --- | --- | ---: | ---: |
| `sleepy` | 困倦 | 31.37 秒 | 1,618 |
| `disappointed` | 失落 | 12.00 秒 | 630 |
| `hesitant` | 犹豫 | 15.52 秒 | 805 |
| `happy` | 开心 | 11.69 秒 | 620 |
| `startled` | 震惊 | 10.83 秒 | 566 |
| `curious` | 好奇 | 16.63 秒 | 780 |
| `playful` | 玩耍 | 41.85 秒 | 2,010 |
| `angry` | 生气 | 23.04 秒 | 1,199 |

表中的时长属于轨迹文件。实拍视频经过剪辑，与轨迹不是逐帧同步的数据集。名称代表设计意图，目前没有进行观众识别测试。玩耍动作依赖固定的积木位置，程序没有物体检测，也不会自主判断搭放是否成功。

## 不连接机械臂也能使用

需要 Python 3.10 或更新版本。离线包没有运行时依赖，不会打开串口。

```sh
git clone https://github.com/Muurrphy/bipu.git
cd bipu
python -m venv .venv
# macOS / Linux：
source .venv/bin/activate
# Windows PowerShell：.venv\Scripts\Activate.ps1
python -m pip install .
expressive-arm list
expressive-arm validate
expressive-arm inspect curious
expressive-arm plot curious --output curious.svg
expressive-arm export curious --output curious.csv
expressive-arm crop curious --start 2 --end 8 --output curious-cut.jsonl
```

[版本发布页](https://github.com/Muurrphy/bipu/releases/tag/v0.3.0b1)提供 wheel 安装包、源码包、完整仓库 ZIP 和 SHA-256 校验文件。下载 wheel 后可运行 `python -m pip install ./expressive_arm-0.3.0b1-py3-none-any.whl`。目前没有发布到 PyPI。

Python 示例：

```python
from expressive_arm.trajectory import load

rows = load("curious")
first_time = rows[0]["t"]
first_target = rows[0]["action"]
```

五个身体关节使用校准后的角度，`gripper.pos` 使用 0–100 的开合百分比。文件中的值是关节目标，不是空间坐标。参见 [数据格式](docs/data-format.md)和 [离线接入示例](examples/read_motion.py)。

## 硬件适配范围

| 使用环境 | 验证情况 | 使用方式 |
| --- | --- | --- |
| SO-101 Leader / Follower，Feetech 舵机 | 在作者的设备上验证过 | [录制与回放指南](docs/recording.md) |
| 其他 SO-101 或不同校准 | 需要本地验证 | 核对零点、方向、行程和起始姿态 |
| SO-100 或其他品牌 | 未验证，不附带驱动 | [适配指南](docs/porting.md) |
| 离线工具 | Linux CI 检查 Python 3.10 / 3.12 / 3.13；本地 macOS 检查 | 命令行或 Python 接口 |

硬件程序位于 `tools/recording`，与离线安装包分开。实机验证环境是 macOS、Python 3.12 和 LeRobot 0.6.0。默认按 Leader 的绝对校准角度直接跟随；程序保持同一条 Follower 连接，并提供持续录制、平滑准备、回放和保持姿态的命令。使用者必须提供自己的串口和已存档校准 ID。硬件工具不支持 Windows。

先阅读 [硬件说明](docs/hardware.md)，再阅读 [录制指南](docs/recording.md)。准备动作和关机流程需要按自己的设备检查。**结束录制或关闭控制程序不会卸掉力矩。** 离线校验通过不代表新设备已完成实机验证。

## 贡献与交流

开发和提交动作的方法见 [CONTRIBUTING.md](CONTRIBUTING.md)。使用问题和演示可放在 [Discussions](https://github.com/Muurrphy/bipu/discussions)，可复现的错误或具体改进建议请提交 [Issue](https://github.com/Muurrphy/bipu/issues)。其他型号的适配应附上驱动接入代码、配置和测试记录。

SO-101 的上游社区入口见 [官方硬件仓库](https://github.com/TheRobotStudio/SO-ARM100)及其提供的 [LeRobot Discord](https://discord.gg/ggrqhPTsMe)。本项目独立维护，不是 LeRobot 的官方组件。

## 许可与引用

程序、文档文字和 JSON / JSONL 动作数据采用 [MIT 许可](LICENSE)。可以修改、再发布或用于商业项目，需保留许可声明。仓库中的照片及链接中的实拍视频由刘美辰保留版权，**不属于 MIT 许可范围**，具体见 [影像许可说明](docs/media-license.md)。

引用方式见 [CITATION.cff](CITATION.cff)，研究参考见 [references.md](docs/references.md)。这里提供八条录制好的动作轨迹，供回放或改编。[动作制作与验证说明](docs/method.md)和 [更新记录](CHANGELOG.md)提供进一步信息。
