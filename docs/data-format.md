# Motion data

Every JSONL row contains `frame`, `t`, `action` and, when available, `observed`. `action` contains exactly `shoulder_pan.pos`, `shoulder_lift.pos`, `elbow_flex.pos`, `wrist_flex.pos`, `wrist_roll.pos`, `gripper.pos`.

Times are strictly increasing and relative to the selected clip. Body positions are calibrated degrees, not raw servo ticks or a portable world coordinate system. Gripper opening is percent, not degrees. Use your own matching calibration and validate joint limits before replay.

The published rows retain the confirmed targets and timing. Local computer paths, leader samples, wall-clock timestamps and raw-practice context are omitted. The manifest checksum refers to this public normalized representation; the original private archive has separate checksums.

The happy performance includes two deliberately removed intervals and generated transitions. Its `observed` values at edited joins are historical measurements rather than measurements of the generated transition. See the authoring notes; never treat the target/observed difference there as a measured controller error.
