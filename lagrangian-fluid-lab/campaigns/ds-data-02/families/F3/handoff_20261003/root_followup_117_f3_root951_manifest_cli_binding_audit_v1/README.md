# fresh117 Root951 metadata-only manifest binding audit

fresh117 is an F3-scoped, source-only audit of the Root951 37-request
registration. It reads only JSON/source/log metadata from the integration
handoff and the exact controller process metadata. It does not open, hash,
copy, or stage H5, BI4, CSV, DAT, VTK, XMF, or other scientific payloads and
does not start, stop, or modify a scientific job, ledger, registry, or shared
controller.

The audit checks:

- all 37 Root951 requests and 37 enabled wrappers pair by physical case,
  family, case, and attempt;
- the adopted fresh116 worker and schema are bound in every wrapper, and the
  renderer argv template passes the original absolute manifest path through
  `--manifest {manifest}`;
- request and wrapper input maps are closed, with Root142, runtime, strict
  dispatch, fair admission, resource-window, worker, renderer, and ledger
  lock metadata present;
- the Root951 budget/ownership fields are identical across the batch: Home
  floor 500 GiB, Home publication cap 3 GiB, NVMe floor 100 GiB, NVMe stage
  cap 24 GiB, CPU24, environment threads 2, wall 14400 seconds, renderer cap
  2, and reservation/current-attempt equality;
- accepted checkpoint 123 contains 199 decisions and none of the 37 physical
  IDs are present;
- Root945's actual dict-representation CLI failure remains evidence only,
  with grounded repair 1 and class limit 2; no case credit is inferred.

At the audit snapshot the Root951 controller is alive (PID and start ticks
are recorded in the report). Its first case is admitted and still `running`:
the exact worker and ParaView descendant PIDs are recorded, and the live
ParaView argv contains the registered absolute `--manifest` path rather than
a dictionary representation. The receipt has no completed result, so this
package assigns no visual credit and does not infer a successful render. The
remaining requests stay under the Root951 first-success-then-parallel-two
controller policy; later scheduling changes do not alter this metadata-only
snapshot.

Validation:

```text
python3 scripts/validate_fresh117.py --write-report
python3 scripts/validate_fresh117.py
```
