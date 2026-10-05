# F3 fresh075 owner/namespace-qualified typed-conversion recovery

fresh075 is the source-only correction to fresh074's process-owner proof.  The
actual conversion caller, ledger, and receipts are owned by UID/GID `1001:1001`
(`jade`), while the real host PID 1 is `systemd` owned by UID/GID `0:0`.
Those owners are distinct: the caller must be the recorded 1001:1001 owner and
the PID-1 status must independently match systemd/0:0.  The package never
claims that the caller is OS root.  Its CLI is disabled and it performs no
ledger mutation, solver launch, process signal, GPU reconciliation, or payload
read.

The reviewed Root184 binding carries an immutable `expected_host` tuple:
hostname `user-SYS-421GE-TNRT`, boot ID
`c2e65531-6320-430a-a872-6b048837d47d`, and self PID namespace
`pid:[4026531836]`.  Each fresh probe must match that tuple exactly; agreement
between two unknown samples is insufficient.  It also requires readable
`/proc/self/status` and `/proc/1/status` with one-level `NSpid` values,
`/proc/self/status` owner 1001:1001, PID-1 name `systemd` and owner 0:0, and
PID-1 `stat` with PID 1 and PPID 0.  `/proc/1/ns/pid` remains unnecessary
because the actual owner cannot read that link; `/proc/self/ns/pid` is read and
must equal the reviewed expected value.

Historical process start ticks remain explicit `null` with
`unknown_historical_start_ticks`; zero is never substituted.  The exact
launcher/child/group identity comes from the immutable runtime receipt and
`Popen(start_new_session=True)`.  Two fresh probes under the unchanged runtime
ledger lock must show `ENOENT` for every exact PID and a complete empty process
group.  Stale evidence, live or ambiguous PIDs, wrong owner/name, unexpected
host/boot/namespace, unknown OS exit, and non-target ledger changes refuse.
Successful Root application charges the full reserved CPU upper bound as
`interrupted_unfinalized`, preserves the original receipt sidecar, leaves child
returncode `null`, and is idempotent.  Native GPU reconciliation is prohibited.

The concrete disabled Root184 request is in
`requests/root184_owner_aware_reconciliation_binding.json`; its application
token and source hash must be reviewed again for fresh075.  The historical
P03 and AY0270 typed receipts remain `running` with returncode absent/null;
old launcher status 143 is a separate fact.  Root must independently recapture
the two qualified `/proc` samples immediately before any application.

Run the synthetic checks with:

```text
python3 -B tests/test_fresh075_owner_namespace_qualification.py
```

The package is F3-local and does not modify the shared index or resource
ledger.
