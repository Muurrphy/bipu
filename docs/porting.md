# Adapting motion to another arm

## What transfers

You can reuse the motion data under MIT and use the demonstrations as a visual reference. The available channels describe the source SO-101's joint targets and timing. No driver for another arm, robot description model, Cartesian end-effector trajectory, or collision model is included.

Export a clip without touching hardware:

```sh
expressive-arm inspect curious
expressive-arm export curious --output curious.csv
expressive-arm plot curious --output curious.svg
```

CSV columns preserve the original targets and seconds; the first five position columns are degrees, and the gripper column is percent. The Python API returns the same targets. See [data format](data-format.md).

## Another SO-101

Even an arm of the same model can have different calibration, mounting, tools, and effective limits. Compare the complete clip against your limits. Check the start and end poses and clearance throughout the motion. The supplied controller uses `use_degrees=True`; a driver using normalized -100..100 body positions needs an explicit conversion based on its calibration, not a renamed dictionary.

Leader/follower IDs refer to your own cached calibration. Do not copy another user's calibration file. A clipped target changes the expression; report clamping and adjust or record the motion again rather than treating a clamped replay as equivalent.

## SO-100 or another brand

1. Document your robot's joint order, units, zero positions, rotation signs, limits, tool geometry, control frequency and stop/hold behavior.
2. Decide whether joint-space remapping is appropriate. A similar arm may permit an explicitly validated sign/offset conversion. Different link geometry or degrees of freedom generally requires a newly recorded performance or kinematic retargeting.
3. Preview the adapted trajectory in your own model. Check full-path joint limits, self-collision, table clearance, and velocity/acceleration requirements. Matching six column names does not reproduce a spatial pose.
4. Use the manufacturer's supported driver. Add an explicit preparation phase from the actual current pose. Preserve the clip's internal timing unless documenting an intentional edit.
5. Validate on your setup and include a report when contributing an adapter. Include the model, firmware, SDK version, calibration conventions, test environment, known limitations and a short replay video.

The SO-101 controller's preparation assumes its shoulder-lift sign and geometry. Do not reuse that path on another model. Its direct replay preserves recorded timing and has no general collision avoidance or independent velocity/acceleration limiter; those checks belong in the target robot's adapter and controller.

## Application events

An application may select a clip when a button is pressed, a dialogue turn completes, or another explicit event occurs. Selection logic belongs to that application. Playback needs states such as preparing, playing, holding and faulted; queue a new expression only after the current motion completes, or use an explicit supported interruption.

The offline API intentionally stops at data access. The [example](../examples/read_motion.py) exports a time/target plan and performs no scheduling or hardware calls. Calling `send_action` once for every row without a clock would play a trajectory at the wrong speed.

These eight clips do not infer a person's emotions and do not create a manipulation policy. A playful block sequence does not adapt to a block that lands somewhere else.
