# Motion data

Every JSONL row contains `frame`, `t`, `action` and, when available, `observed`. `action` contains exactly `shoulder_pan.pos`, `shoulder_lift.pos`, `elbow_flex.pos`, `wrist_flex.pos`, `wrist_roll.pos`, `gripper.pos`.

Times are strictly increasing and relative to the selected clip. Body positions are calibrated degrees, not raw servo ticks or a portable world coordinate system. Gripper opening is percent, not degrees. Use your own matching calibration and validate joint limits before replay.

The published rows retain the confirmed targets and timing. Local computer paths, leader samples, wall-clock timestamps and raw-practice context are omitted. The manifest checksum refers to this public normalized representation; the original private archive has separate checksums.

The happy performance includes two deliberately removed intervals and generated transitions. Its `observed` values at edited joins are historical measurements rather than measurements of the generated transition. See the authoring notes; never treat the target/observed difference there as a measured controller error.

## CSV export

`expressive-arm export curious --output curious.csv` writes the columns below:

```text
t,shoulder_pan.pos,shoulder_lift.pos,elbow_flex.pos,wrist_flex.pos,wrist_roll.pos,gripper.pos
```

`t` is seconds. The five body columns are calibrated degrees; the gripper column is opening percent. All original target values and sample times are retained. `observed` values are omitted; CSV is a target trajectory, not a fresh hardware measurement.

## Sample timing

The controller aims for 60 Hz, but recordings have variable sample intervals. Use `t`, not a presumed fixed frame rate, for playback or resampling. `inspect` reports the largest gap. The shipped clips retain `tracking: direct` metadata needed by the recording controller's replay path. That path preserves recorded timing without a general velocity/acceleration limiter; a hardware adapter must check its own constraints.
