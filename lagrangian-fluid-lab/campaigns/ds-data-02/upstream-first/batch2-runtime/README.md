# Upstream first batch 2 runtime gate

This directory documents the root-authored artifacts consumed by
`scripts/ds_data02_runtime_v6_batch2.py`. It contains no active admission,
request grant, or ledger update. The `*.example.json` files are templates with
deliberately non-final values and must fail validation until root replaces every
placeholder after the M3 and cost review.

The existing accepted certificates are:

* M1: `../milestone-evidence/M1-complete-v1.json`, SHA-256
  `65ebd22bd6bfd5303da90472e8eb1accb8eb6b16aae0cf88e5fc1c578baa034f`.
* M2: `../milestone-evidence/M2-complete-v1.json`, SHA-256
  `d1beb6ea82a27a41a396470ce8eefefd216768efcaaffc0f6651f138ed2562ee`.

M3 is still pending. Root must create an M3 certificate with the same
`ds02.upstream-first.milestone-evidence.v1` schema, `milestone: "M3"`,
`status: "complete"`, `acceptance_status: "accepted"`, and a non-empty
`receipts` list. Each receipt binding must point to a real regular JSON file,
carry its raw-byte SHA-256 and terminal status, and agree with the receipt's
own `status`. A certificate marked complete cannot conceal a pending or failed
receipt.

The M1--M3 cost audit is a separate root artifact. It must use
`ds02.upstream.cost-audit.v1`, be complete and accepted, and repeat the exact
`prior_charged_ids` and `prior_usage` recorded in the admission. Until M3 and
that audit are complete, no final admission is valid and no batch-2 request
may be launched.

## Admission object

`batch-admission.example.json` lists every required key. The final object must
have schema `ds02.upstream-first.batch-admission.v1`, `status: "admitted"`,
`issuer: "root"`, `immutable: true`, `batch_index: 2`, and
`previous_batch_index: 1`. `payload_sha256` is the SHA-256 of the canonical
UTF-8 JSON object after removing that field: sorted keys, `ensure_ascii=false`,
compact separators `(',', ':')`, and `allow_nan=false`.

The final batch limits are exactly 86,400 GPU seconds, 345,600 CPU-core
seconds, and 24 solver attempts. `additional_storage_bytes` is a positive,
finite integer chosen from the actual M4 product and peak reservation and must
be no greater than 256 GiB (`MAX_ADDITIONAL_STORAGE_BYTES`). The 256 GiB value
is an operational ceiling, not an allocation or a promise to use that much.
The initial 50 GiB tranche is not copied into this field unless the actual
cost review supports that amount.

The admission must also contain:

* `evidence.M1`, `.M2`, and `.M3`, each with `status`, `acceptance_status`,
  absolute `path`, and raw-file `sha256`.
* `cost_audit` with `status`, `acceptance_status`, absolute `path`, and
  raw-file `sha256`.
* `parent_ledger_path`, exactly
  `<data_root>/runtime/resource-ledger.json`, and `parent_deadline_utc` copied
  from that ledger.
* `parent_limits`, copied exactly from the live ledger, including all five
  resource limits and `storage_policy`, `home_min_free_bytes`, and `home_path`.
* A complete cumulative baseline: sorted unique `prior_charged_ids`, an exact
  `prior_charge_row_sha256` entry for every charge row, sorted unique
  `prior_attempt_ids`, an exact `prior_attempt_row_sha256` entry for every
  attempt row, `prior_reservation_ids: []`, numeric `prior_usage`, and
  `prior_charges_sha256`.

The row hashes use the same canonical JSON rule over each complete ledger row.
`prior_charges_sha256` hashes the canonical JSON list of the prior charge rows
sorted by `id`. The baseline is cumulative: it preserves all historical
charges and attempts and never resets after admission. At admission time the
ledger must be quiescent; rows added later must stay in the `UF_` namespace.

## Per-request grant

The admission intentionally does not enumerate future conversion or solver
request files. Root creates one immutable grant per concrete request using
`batch-request-grant.example.json`. The grant must have schema
`ds02.upstream-first.batch-request-grant.v1`, `status: "granted"`,
`issuer: "root"`, `immutable: true`, and `batch_index: 2`. It binds:

* the normalized absolute admission path and its `admission_payload_sha256`;
* the normalized absolute request path and the request's raw-byte
  `request_sha256`; and
* the exact UF attempt ID (`family/case/attempt`) in `attempt_id`.

The grant has its own canonical `payload_sha256`. It does not need future
receipt hashes; the runtime binds the grant and admission into the execution
receipt after the request is admitted.

## Read-only validation and launch command

Use the canonical environment below for a read-only preflight after root has
filled the artifacts. This validates the admission, its M1--M3 evidence and
cost audit, the live cumulative ledger baseline, and one request grant without
launching or mutating anything:

```sh
export PYTHON=/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
export SCRIPT=/home/jade/.codex/worktrees/upstream-first/DualSPHysics/lagrangian-fluid-lab/scripts
export DATA_ROOT=/home/jade/Projects/DualSPHysics-data/ds-data-02
export ADMISSION=/home/jade/.codex/worktrees/upstream-first/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/batch2-runtime/root-batch-2-admission.json
export REQUEST=/ABSOLUTE/PATH/TO/ONE_ROOT_GRANTED_REQUEST.json
export GRANT=/ABSOLUTE/PATH/TO/ONE_ROOT_REQUEST_GRANT.json

"$PYTHON" - <<'PY'
import os
from pathlib import Path
import sys

sys.path.insert(0, os.environ["SCRIPT"])
import ds_data02_runtime_v6_batch2 as runtime

data_root = Path(os.environ["DATA_ROOT"])
admission_path = Path(os.environ["ADMISSION"])
request_path = Path(os.environ["REQUEST"])
grant_path = Path(os.environ["GRANT"])
admission = runtime.validate_admission(admission_path, data_root=data_root)
grant = runtime.validate_request_grant(
    grant_path,
    admission_path=admission_path,
    admission=admission,
    request_path=request_path,
)
print({"admission": admission["payload_sha256"], "grant": grant["payload_sha256"]})
PY
```

After the root gate and grant are independently reviewed, the corresponding
runner invocation is:

```sh
"$PYTHON" /home/jade/.codex/worktrees/upstream-first/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v6_batch2.py run \
  --data-root "$DATA_ROOT" \
  --request "$REQUEST" \
  --batch-admission "$ADMISSION" \
  --batch-grant "$GRANT"
```

The runner retains v6 UUID leases, single-heavy-task admission, NAS headroom,
Home free-space floor, parent live-limit checks, and terminal receipt accounting.
Batch-2 compute and storage are incremental bounds; parent compute and all
historical storage remain cumulative.
