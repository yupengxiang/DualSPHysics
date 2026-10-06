# Fresh154 F3 registered render-handle audit

This is a metadata-only snapshot of the twelve registered F3 render handles 987, 1031, 1033, 1046, 1047, 1100, 1101, 1102, 1129, 1135, 1141, and 1194. No case was eligible for personal visual review at the observation time, so no contact sheet or keyframe was opened and no visual credit was granted.

All twelve controller PIDs matched their recorded start ticks. Eleven controllers were sleeping without children or output receipts. Handle 1100 had the only active child chain and its own execution receipt was still `running`; it had no published report. No controller was restarted or stopped.

The five early request records (987, 1031, 1033, 1046, 1047) say `expected_frames: 801` at the request level while their wrapper metadata says 836. The source records are retained unchanged and the discrepancy is reported for Root review.

Only JSON metadata and `/proc` process metadata were read. No H5, BI4, CSV, DAT, VTK, PNG, or other scientific payload was opened, read, copied, or hashed.
