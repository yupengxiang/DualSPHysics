# F2 RX053 ROT105 semantic correction (fresh163)

fresh163 is an immutable semantic successor to fresh162 (`d36c69b50c2e11ba6c721a7e310cc306c0aa1ae8`). It preserves the original 26-PNG personal visual review and published render references; no image was re-viewed and no producer/science output was changed.

The correction derives producer limits from the actual Root1064 typed conversion report `52ffafc0bd4a0412f35d03d285719e4ec9b8a68a96138667b6acdbc9cc0897e3`, specifically `lifecycle.frame_summary`: 236 frames with missing particles, 1051 particle-frame omission events, maximum 7 in one frame, final 7, first missing frame 165/type 3. The corrected decision and visual blocks are checked against the unchanged fresh162 chain block.

No H5/BI4/CSV/DAT/VTK payload was opened or hashed, no job was started, and no global count was changed. Scope roles and numerical/Q-N/Q-E limitations remain unchanged.

Run:

```text
python3 scripts/validate_fresh163.py
```
