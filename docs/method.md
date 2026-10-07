# Authoring and validation

Motion data was recorded from a SO-101 leader/follower setup. Each selected clip was replayed and confirmed on the author's follower. The public library contains eight selected clips; earlier generated templates remain in the separate recording tools for comparison and are not part of the eight-clip library.

## Workflow

1. Continuously record leader-following targets and follower measurements.
2. Select explicit time bounds. Keep intentional pauses within a clip; exclude idle time outside it and the separate parking motion.
3. Prepare the follower to the clip's starting pose, replay, and check the selection.
4. Archive the accepted trajectory and film the demonstration separately.

The happy clip has two removed intervals joined by generated transitions. Its historical `observed` samples at those joins are not measurements of the generated transition. The motion JSONL files and edited films are not a synchronized training dataset.

## Control choices

Default tracking is direct, with absolute calibrated-angle mapping. A damped filter produced noticeable following delay during authoring; relative mapping preserved an unwanted initial joint offset. These alternatives remain explicit options, not defaults. Preparation uses a continuous quintic trajectory rather than a series of small stops.

The tools read cached calibration and servo configuration without automatically rewriting them. Command ranges are checked. Measured positions can differ slightly from commanded targets near a limit; the controller distinguishes its inward command margin from the calibration range. Different arm builds still require their own validation.

## Evidence and limits

The included clips were demonstrated on one SO-101 setup. Offline tests cover data integrity and controller behavior with fake hardware; they do not prove physical performance on another arm. The linked films are daytime fixed-camera demonstrations.

No blind audience recognition study has been run. A future study could randomize unlabeled clips, collect free descriptions and label choices, and report confusion between expressions. The eight labels currently indicate intended expression, not measured recognition accuracy.
