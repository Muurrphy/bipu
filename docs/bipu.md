# Bipu runtime

[中文](bipu.zh-CN.md)

Bipu is a small nonverbal robot pet built around the existing eight human-choreographed motions. The idea is simple: someone outside the frame sends a message or puts a toy into its little world; Bipu responds with movement and an electronic call.

This development version adds two runnable modes. It does not replace or modify the recorded joint targets.

## Run locally

Python 3.10+. No extra dependencies for preview, local rules, HTTP, Jev or Telegram.

```sh
python -m pip install .
bipu serve --open
```

The page is at `http://127.0.0.1:8765`. Startup is paused. Click **开启宠物模式** to start, **停止** to cancel, and **退出程序** to exit. Ctrl+C or closing the foreground launch terminal also stops the service. Nothing installs itself as a background service. Closing only the browser tab does not stop the runtime.

Preview uses the real policy and queue with simulated execution time. Optional historical videos illustrate selected motions; they are not live camera views or frame-synchronized trajectory recordings. Without local media files, decisions still run silently. A fresh browser needs one click to enable audio. Browser audio requires an open foreground control page; use `--audio system` for local `afplay` / `aplay` instead. Do not open multiple audible browser panels.

## Pet mode

Default local rules recognize a small set of Chinese/English phrases. They are deterministic keyword classification, not language understanding. “还不错” selects happy; repeated scolding progresses from startled to angry; reassurance gradually softens the state. A user saying they are sad selects the existing disappointed motion; there is no new comfort behavior.

State includes energy, irritation, sleep, last contact and recent activity. It persists locally across restarts; startup is always paused. During idle periods, a decision runs every 45–90 seconds after the prior action finishes. Waiting is more likely than movement. At about four minutes without a message, or low energy, Bipu sleeps once and then remains quiet until contacted. These are configurable software rules, not a claim about physical fatigue or emotional understanding. There is no presence detection.

Messages queue while a clip is playing. The queue holds at most 16; messages older than 45 seconds are discarded. Each motion finishes before the next starts. Stop cancels pending messages, sound and playback; it does not trigger a resting motion.

Playful uses the recorded block arrangement. A message about toys cannot mark the workspace ready. The operator must tick the props checkbox; one play consumes that readiness. Reset the blocks and confirm again before another play. Bipu does not detect a successful stack.

## Choreography mode

Stop pet mode, then use the editor to add motions and sounds, import/export JSON, and play the score. The whole score is validated before execution. Eight known motions only; finite delays; sounds in the matching emotion group, signature group or backup group; no overlapping audio cues or audio extending beyond the clip. Each score permits one block-play clip, then requires the operator to reset the props.

```json
{"version":1,"steps":[
  {"motion":"curious","wait_before":0,"sounds":[]},
  {"motion":"happy","wait_before":3,"sounds":[]}
]}
```

`wait_before` is the gap before preparing a clip. Sound cue `at` is seconds after its replay starts. Each complete recorded clip is preserved. Hardware preparation time is additional. This is a clip sequencer, not an audio-alignment or multi-robot orchestration tool; existing filming tools remain available.

```sh
bipu --config config.local.json validate-score examples/bipu-score.json
```

## Local files and sound pools

The default configuration lives at `~/.config/bipu/config.json`. Pass `--config` before the subcommand to use another location. Copy `examples/bipu-config.json` and set your local paths. Runtime logs contain messages; keep them private. The session token file and configuration created by the CLI use owner-only permissions. Do not commit tokens, calibration, runtime folders or personal media.

`sound_root` points to a directory you control. The bundled sound index contains 27 selected call references and 12 optional backups, with SHA-256 checksums, emotion groups and durations. Audio files and demonstration videos are not bundled or relicensed by this package; see [media licensing](media-license.md). Missing audio means silent operation. The creator's local installation already has all 39 files.

To use your own audio, set `sound_manifest` to a JSON array:

```json
[{"id":"my_happy","label":"Short happy call","group":"happy",
  "file":"happy.wav","sha256":"SHA256_OF_FILE","duration_s":1.4,
  "default":true,"favorite":false}]
```

Files must remain under `sound_root`; contents are verified before playback. Groups are the eight motion IDs, `signature`, or `backup`. Pet mode picks among matching `default:true` calls plus silence, avoiding an immediate repeated call when alternatives exist. Local selection first chooses an emotion, then a call, so a larger sound pool does not make that emotion more frequent. Signature/backup calls are selectable in choreography. To opt a backup into pet mode, explicitly assign it to an emotion and set `default:true` in your custom manifest. Four heart-marked references remain H05, H11, H20 and H24.

## Optional Jev and Telegram

The current local build works without either credential. Provider and backend are always shown on the page. On the creator’s installation, a real allowlisted private Telegram message has passed through Jev to a motion and sound choice in local preview (2026-10-09). This does not imply physical robot validation.

```sh
bipu --config config.local.json configure
bipu --config config.local.json serve --provider jev --open
```

`configure` prompts privately for a TypeSafe key and optional Telegram bot token. Environment variables `TYPESAFE_API_KEY` / `TELEGRAM_BOT_TOKEN` override configured values. Jev uses the official [TypeSafe choice API](https://docs.typesafe.ai/introduction/quickstart), model `jev-latest`. It classifies a message then selects from the locally allowed motion/sound pairs. It cannot write joint angles, invent a trajectory, or mark props ready. Uncertain message interpretation, malformed responses, failed requests or rate limits cause waiting and a visible error, not a silent switch to local rules. The interpreter receives recent interaction context. For expressive variation among already permitted performances, the model’s validated probability distribution is sampled; low confidence between equally valid calls does not cancel a known emotion. This differs from semantic uncertainty about the message. Requests are limited locally to 12 per minute; only event text and software state are sent.

For Telegram, configure a token and explicit private chat IDs, then set `telegram_enabled:true`. The [getUpdates bridge](https://core.telegram.org/bots/api#getupdates) receives text from those private chats only, skips the existing backlog at startup, and rejects stale messages. `/stop` stops the runtime. It sends no chat replies and cannot enable hardware or mark props ready. Start pet mode locally first. Only one poller may use a bot at a time; an existing webhook must be removed by its operator before polling. No webhook is removed automatically.

## Existing SO-101 controller adapter

Default startup never opens serial or enables torque. Attaching to hardware is explicit:

```sh
bipu --config config.local.json serve --controller-runtime /path/to/human_runtime --audio system
```

First set up the existing [human recording controller](recording.md) with your own calibration. It must already be holding, with a fresh protocol-2 heartbeat. Configure `approved_transitions`, for example `["START->curious","curious->happy"]`, only after checking those transitions physically on your setup. `START` means the operator-established current pose, not a universal home pose. After stop or an external command, re-establish that pose before restart. Do not approve all pairs merely to silence errors.

Pet choices are filtered to reviewed outgoing transitions; if none fit, Bipu waits. Scores with an unreviewed transition are rejected before starting. The adapter locks out a second Bipu adapter, checks every recorded target against controller limits, sends the existing prepare/replay commands, waits for acknowledgements, and checks the final pose. It never changes calibration, adds a joint offset or rescales the trajectory. A failure cancels the queue and requests hold when appropriate. It is not an independent collision detector or hardware emergency stop. Other controller clients must stay idle. Stop holds torque; physical support and the existing shutdown procedure are required to release it.

This adapter has been tested against simulated controller states only in this development pass. Real hardware transitions and timing remain to be verified; no robot was moved while building the local system.

## Tests

```sh
python -m unittest discover -s tests -v
(cd tools/recording && python -m unittest test_motion_library test_human_workflow -v)
```

Coverage includes mood transitions, sleep, props consumption, cancellation during slow decisions/preparation, score validation, sound integrity, same-origin/token enforcement, Telegram filtering and controller rejection/timeouts. The original motion library tests continue to run.
