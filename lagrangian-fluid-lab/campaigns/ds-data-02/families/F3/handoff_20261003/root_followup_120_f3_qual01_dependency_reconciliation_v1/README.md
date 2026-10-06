# F3 fresh120 QUAL01 dependency reconciliation

This sidecar records the distinction between historical queue registration and
actual downstream use for
`F3_DUAL_AXIS_PHASE_PARENT_SOLVER_QUAL_01`. It does not modify fresh119, the
failed receipt, the shared ledger, or the raw output directory, and it does not
delete files or launch a task.

The execution queue and the two legacy qualification request JSON files contain
the failed attempt ID, but their input lists point to the successful
`F3_DUAL_AXIS_PHASE_PARENT_GENCASE_02` XML/BI4/receipt inputs. They do not point
to the failed QUAL01 solver output. Root's bounded 20,785-JSON live/accepted
closure likewise reported no QUAL01 frame dependency. This is recorded as
metadata evidence, not as permission for this agent to delete anything.

The Root965 bounded cleanup plan may remove only the 1,786 intermediate frame
files `Part_0001.bi4` through `Part_1786.bi4` after Root repeats its lock,
lease, process, and dependency checks. It keeps `Part_0000.bi4`,
`Part_1787.bi4`, all non-frame output files, `stdout.log`, `Run.out`,
`controller-cancellation.json`, and `execution-receipt.json`. The sidecar
records the pre-cleanup stat totals and the planned byte delta; no deletion was
performed here.

PID 4038392's broad `rg` command was not started by this agent. This agent has
not opened or hashed BI4/H5/CSV/DAT/VTK payloads. Future metadata search tools
must use an explicit JSON/XML/log/Python/path allowlist and never search raw
scientific extensions.
