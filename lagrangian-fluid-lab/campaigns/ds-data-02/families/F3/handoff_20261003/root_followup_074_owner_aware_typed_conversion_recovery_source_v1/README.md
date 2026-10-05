# F3 fresh074 owner-aware typed-conversion recovery

fresh074 is a source-only correction to fresh072.  The earlier contract
required `euid == 0`, which is not executable on this host: the actual ledger,
receipts, and caller are owned by `UID/GID 1001:1001` (`jade`).  fresh074 uses
that exact owner and never labels it OS root.  The CLI remains disabled and
this package performs no ledger mutation, solver launch, process signal, or
GPU/native reconciliation.

Before an integration caller can probe the ledger, `validate_owner_binding`
requires the exact owner UID/GID, a same-owner regular single-link ledger and
source receipt, and the selected ledger path under the supplied data root.  It
checks the owner with stable `fstat` identity/size/time metadata before the
in-lock operation and again in each fresh probe.  A foreign owner, symlink,
non-regular file, changed file, or mismatched path refuses.

The namespace proof is usable by the actual owner.  It reads `/proc/self/status`
and `/proc/1/status`, requires one-level `NSpid` values (`self == os.getpid()`
and `PID 1 == 1`), matching owner UIDs/GIDs, and reads `/proc/1/stat` with
`PID 1` and `PPID 0`.  It records `/proc/self/ns/pid` for the observed
namespace.  It does not require `/proc/1/ns/pid`, which is ACL-inaccessible to
the real owner, and it never fabricates `root_caller` or UID 0.

The fresh072 safety rules remain intact: historical start ticks are explicit
`null` with `unknown_historical_start_ticks`; the exact launcher/child/group
identity comes from the immutable runtime receipt and
`Popen(start_new_session=True)`; two fresh in-lock probes must show `ENOENT`
for every target and a complete empty process group; stale caller evidence,
PID ambiguity, namespace changes, missing probes, GPU rows, unknown OS exit,
and non-target ledger changes all refuse.  A successful settlement charges the
full reserved CPU upper bound as `interrupted_unfinalized`, preserves the
original receipt sidecar, keeps child returncode `null`, and is idempotent.

The current source evidence records P03 and AY0270 typed receipts as
`running` with returncode absent/null.  Their old launcher status 143 remains
a separate fact.  Root must independently recapture the two `/proc` samples
under the unchanged runtime lock before applying any settlement.

The concrete disabled Root184 binding is in
`requests/root184_owner_aware_reconciliation_binding.json`; the earlier
Root174 binding is retained only as a superseded review artifact.

Run the synthetic checks with:

```text
python3 -B tests/test_fresh074_owner_qualification.py
```

The package is F3-local and does not modify the shared index or resource
ledger.
