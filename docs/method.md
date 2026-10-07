# How the performances were made

1. Explore with a leader arm while recording several minutes continuously. Early attempts can be rough.
2. Pause in the air between attempts. A pause need not be the neutral pose or a return to the table.
3. Select the last complete or penultimate performance. Remove leading/trailing idle time and the final parking motion while preserving intentional pauses.
4. Prepare smoothly, replay on the follower, and have the choreographer confirm the selection.
5. Archive the confirmed trajectory and its story, then film it. Film timing and motion timing are separate records.

Automatic motion designs produced uneven results in the real object. Human choreography gave better control over the degree and meaning of each gesture. The sleepy performance includes briefly recovering from drowsiness before gradually shrinking into sleep. The sad and angry performances retain their turns away from the observer. The happy performance removes a forward dive and the closing crouch because those did not fit its intended meaning.

Two control issues mattered. A damped tracking filter added a noticeable delay, so direct following became the default. An initial relative offset prevented the leader and follower from reaching the same shoulder pose, so absolute calibrated-angle mapping became the default. The tools retain relative/smooth modes as explicit options rather than silent defaults.

Briefly stopping after each tiny preparation step made motion feel staccato. Preparation instead uses one continuous quintic trajectory. Existing calibration and servo configuration are read and checked; the recording tools do not automatically rewrite them. Leader/follower range differences are still real hardware constraints.

The final films use daytime fixed framing. A Pocket 3 moving-camera session was abandoned because the available light was insufficient. Labels help present the performances; future recognition studies should also use versions without labels.
