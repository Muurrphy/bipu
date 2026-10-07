# Hardware notes

Recorded on a SO-ARM101 leader/follower pair with Feetech servos, using LeRobot 0.6.0 and Python 3.12. The white follower performed the motion; the black leader was manipulated by hand. The five body joints use calibrated degrees; the gripper uses opening percent.

The follower starts by checking cached calibration, operating mode, all six servo responses and calibrated ranges. It latches measured raw positions before enabling torque, avoiding a jump to an old goal. It does not call servo configure or automatically recalibrate. The leader must already be calibrated and torque-free.

Each arm has its own calibration and geometry. These trajectories are examples rather than universal safe poses. Use your own base mounting, clearance and supported startup/shutdown. The scripts refuse invalid poses and report clamping rather than silently changing calibration.

No hardware was powered or moved while preparing this public release. The production recordings were verified earlier on the author's arm; that verification does not validate a different setup.
