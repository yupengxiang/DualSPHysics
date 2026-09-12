# F3 process-local GPU runtime recovery

On 2026-09-12 the system's unattended package upgrade installed NVIDIA user-space
595.91.07 while the loaded kernel module remained 595.71.05. Ordinary
`nvidia-smi` failed with a driver/library mismatch. No system packages, services,
kernel modules or other users' processes were changed by this task.

The matching Ubuntu amd64 compute and utility packages were retrieved from the
Canonical Launchpad build 32828215. Their complete sizes and SHA-256 digests were
verified against the build's `.changes` file before extraction. An interrupted
compute-package download was completed by byte ranges; the assembled package
passed the complete-file digest. Package metadata, URLs and extracted library
hashes are in `campaigns/l1-resume/continuation/F3-GPU-RUNTIME-RECOVERY.json`.

The extracted tree is:

`/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/data/f3-gpu-runtime/595.71.05`

For this task's process only, prepend its `usr/bin` to `PATH` and set
`LD_LIBRARY_PATH` to its `usr/lib/x86_64-linux-gnu`. The existing solver launcher
also prepends its vendor library directory. Check the recorded library hashes
and loaded kernel version before reusing this environment. This workaround is
specific to the recorded matching kernel; a subsequent system change requires
fresh validation.

The recovered `nvidia-smi` successfully enumerated all eight recorded GPUs with
their unchanged UUIDs. The solver subsequently initialized on GPU4 using the
normal UUID, memory, timeout, one-solver and attempt-count guards. GPU0–3 remain
protected. The task does not fall back to an unguarded GPU or change the CPU/GPU
resource limits.

The current native no-penetration worker's process IDs, command and terminal
timestamps are written to `F3-NATIVE-NOPEN-WORKER-LIFECYCLE.json`. Its wrapper
waits through normalization/audit and then closes the CPU activity window and
refreshes the ledger. Subsequent real work must open a new activity window.
Worker liveness must still be verified from its actual process/session.
