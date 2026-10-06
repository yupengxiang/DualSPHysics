# F6 fresh172 — DZXY S1375/YAWP18 Root951 queue audit

This F6-only sidecar freezes a metadata observation of the last Root951 F6
request. It does not launch, stop, restart, or modify the controller, request,
receipt, source bytes, or shared ledger.

The target is `outer_requests[35]` in Root951's actual `controller-config.json`:
`F6_STAGE1_ANGULAR_RELEASE_DZXY_S1375_YAWP18_DP025`. At the observation time
the request was enabled (`disabled=false`, `launch=true`,
`execution_allowed=true`, `launch_allowed=true`) and had an exact absolute
manifest path. Its 45 input paths and 45 input digests had equal key sets; all
44 non-science input paths existed. The single science trajectory path was
only `stat` inspected and was not opened or hashed.

The request had no attempt directory, receipt, renderer output, or result row.
Root951 had 36 result rows, `pending_not_submitted=0`, and the target was the
only missing row among the 37 outer requests. PID 4004579 was still alive with
start ticks `207142232`. The target therefore remained inside the same
controller's fair-dispatch future; its absence from the result table is not a
scientific failure.

`batch-controller.py:6` calls `dispatch(qp)` without `serial_conversion=True`,
so `fair_CPU_dispatch.py:19` uses the renderer-registration lock and
`fair_CPU_dispatch.py:33-34` applies both CPU/headroom and renderer-cap tests.
At the frozen observation there were two 24-thread reservations:

- `F3/...root1100`, 24 threads, 2 GiB;
- `F5/...root1183`, 24 threads, 2 GiB.

The target requests 24 threads and 3 GiB. Thus CPU fit was false
(`48 + 24 + 2 > 64`) and renderer-cap fit was false (`2 < 2`), while Home
fit was true (about 790.97 GiB free; 500 GiB floor). The concrete wait reason
was shared render capacity, with the CPU headroom check also false. No input,
manifest, strict guard, or qualification defect was found.

The safe recovery is to leave this same request and controller future intact
until at least one current 24-thread renderer reservation is released. The
existing fair dispatcher will then re-evaluate both predicates atomically and
invoke the unchanged Root142 launch path. A duplicate attempt, modified
request, manual signal, or restart would break the preserved no-retry guard.

The target was not visually reviewed because no completed/0 published product
existed at the frozen observation. `case_credit` remains 0.

Validate the frozen metadata sidecar with:

```sh
python3 scripts/validate_fresh172.py
```
