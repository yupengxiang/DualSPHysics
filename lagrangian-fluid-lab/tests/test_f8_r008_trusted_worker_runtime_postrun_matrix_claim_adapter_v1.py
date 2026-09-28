from __future__ import annotations

import base64
import copy
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import f8_r008_t1_metric_matrix_adapter_v5 as matrix_v5
from scripts import f8_r008_trusted_worker_runtime_postrun_matrix_claim_adapter_v1 as adapter
from scripts import f8_r008_trusted_worker_runtime_replay_ledger_binding_v1 as replay
from tests import test_f8_r008_trusted_worker_runtime_handoff_v1 as handoff_fixtures
from tests import test_f8_r008_trusted_worker_runtime_replay_ledger_binding_v1 as replay_fixtures


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _public_bytes(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )


def _case_claim(
    case_id: str, handoff_binding: dict[str, Any], pre: dict[str, Any], post: dict[str, Any],
) -> dict[str, Any]:
    handoff_issuer = handoff_binding["handoff_issuer"]
    handoff_subject = handoff_binding["handoff_subject"]
    handoff_projection = {
        "scope_id": handoff_binding["scope_id"],
        "handoff_sha256": handoff_binding["handoff_sha256"],
        "attempt_id": handoff_binding["attempt_id"],
        "attempt_case_id": handoff_binding["case_id"],
        "nonce_hex": handoff_binding["nonce_hex"],
        "issuer": {
            "active_key_id": handoff_issuer["active_key_id"],
            "authority_binding_sha256": handoff_issuer["authority_binding_sha256"],
        },
        "subject": {
            "worker_principal_id": handoff_subject["worker_principal_id"],
            "worker_binding_sha256": handoff_subject["worker_binding_sha256"],
            "runtime_principal_id": handoff_subject["runtime_principal_id"],
            "runtime_binding_sha256": handoff_subject["runtime_binding_sha256"],
        },
    }
    pre_ledger = pre["ledger"]
    post_ledger = post["ledger"]
    replay_issuer = post["issuer"]
    replay_projection = {
        "scope_id": handoff_binding["scope_id"],
        "handoff_sha256": handoff_binding["handoff_sha256"],
        "attempt_id": handoff_binding["attempt_id"],
        "attempt_case_id": handoff_binding["case_id"],
        "nonce_hex": handoff_binding["nonce_hex"],
        "ledger_id": pre_ledger["ledger_id"],
        "entry_id": pre_ledger["entry_id"],
        "pre_generation": pre_ledger["generation"],
        "post_generation": post_ledger["generation"],
        "consumed_epoch": post_ledger["consumed_epoch"],
        "consumption_id_sha256": post_ledger["consumption_id_sha256"],
        "issuer": {
            "ledger_principal_id": replay_issuer["ledger_principal_id"],
            "key_id": replay_issuer["key_id"],
            "key_sha256": replay_issuer["key_sha256"],
        },
    }
    return {
        "schema": adapter.CASE_CLAIM_SCHEMA,
        "record_id": adapter.CASE_CLAIM_RECORD_ID,
        "status": adapter.CASE_CLAIM_STATUS,
        "synthetic_only": True,
        "input_origin": "synthetic_fixture",
        "scope_id": adapter.SCOPE_ID,
        "case_id": case_id,
        "handoff": handoff_projection,
        "replay": replay_projection,
    }


def _fixtures() -> dict[str, dict[str, Any]]:
    case_ids, _rows = matrix_v5._frozen_rows()
    handoff, _handoff_raw, root_public, active_key, identity_raw = handoff_fixtures._handoff()
    ledger_key = Ed25519PrivateKey.generate()
    ledger_public = _public_bytes(ledger_key)
    fixtures: dict[str, dict[str, Any]] = {}
    for index, case_id in enumerate(case_ids):
        value = copy.deepcopy(handoff)
        value["handoff_id"] = f"synthetic-handoff-{index + 1:03d}"
        value["attempt"]["attempt_id"] = f"synthetic-attempt-{index + 1:03d}"
        value["attempt"]["case_id"] = f"synthetic-matrix-{case_id}"
        value["attempt"]["nonce_hex"] = f"{index + 1:032x}"
        value["attempt"]["request_sha256"] = hashlib.sha256(
            f"synthetic-request-{index + 1:03d}".encode("ascii")
        ).hexdigest()
        handoff_raw = handoff_fixtures._resign(value, active_key)
        binding = replay.derive_handoff_binding(handoff_raw)
        ledger_id = f"synthetic-replay-ledger-{index + 1:03d}"
        entry_id = f"synthetic-replay-entry-{index + 1:03d}"
        pre_generation = 40 + index * 2
        post_generation = pre_generation + 1
        consumed_epoch = 100 + index
        pre = replay_fixtures._witness(
            binding, ledger_key, generation=pre_generation, consumed=False,
            ledger_id=ledger_id, entry_id=entry_id,
        )
        consumption_id = replay.consumption_id_sha256(
            binding,
            ledger_id=ledger_id,
            entry_id=entry_id,
            pre_generation=pre_generation,
            post_generation=post_generation,
            consumed_epoch=consumed_epoch,
        )
        post = replay_fixtures._witness(
            binding, ledger_key, generation=post_generation, consumed=True,
            ledger_id=ledger_id, entry_id=entry_id,
            consumed_epoch=consumed_epoch, consumption_id=consumption_id,
        )
        fixtures[case_id] = {
            "case_claim": _case_claim(case_id, binding, pre, post),
            "handoff_raw": handoff_raw,
            "identity_bundle_raw": identity_raw,
            "trust_root_public_key_bytes": root_public,
            "pre_ledger_witness_raw": _canonical(pre),
            "post_ledger_witness_raw": _canonical(post),
            "trusted_ledger_public_key_bytes": ledger_public,
        }
    return fixtures


def test_fifteen_frozen_cases_bind_without_authority_or_matrix_worker() -> None:
    result = adapter.bind_synthetic_postrun_matrix_claims(_fixtures())

    assert result["schema"] == adapter.SCHEMA
    assert result["status"] == adapter.STATUS
    assert result["case_count"] == 15
    assert result["case_ids"] == matrix_v5._frozen_rows()[0]
    assert result["frozen_case_set_bound"] is True
    assert len(result["case_bindings"]) == 15
    assert all(binding["handoff_verified"] for binding in result["case_bindings"].values())
    assert all(binding["replay_transition_verified"] for binding in result["case_bindings"].values())
    assert all(
        binding["attempt_case_id"] == f"synthetic-matrix-{case_id}"
        for case_id, binding in result["case_bindings"].items()
    )
    assert all(value is True for value in result["matrix_invariants"].values())
    assert result["non_authorizing_boundary"] == adapter.NON_AUTHORIZING_BOUNDARY


def test_missing_or_extra_case_row_fails_closed() -> None:
    rows = _fixtures()
    rows.pop(next(iter(rows)))
    with pytest.raises(adapter.TrustedPostrunMatrixClaimAdapterError, match="exactly the 15"):
        adapter.bind_synthetic_postrun_matrix_claims(rows)

    rows = _fixtures()
    rows["extra-case"] = copy.deepcopy(next(iter(rows.values())))
    with pytest.raises(adapter.TrustedPostrunMatrixClaimAdapterError, match="exactly the 15"):
        adapter.bind_synthetic_postrun_matrix_claims(rows)


@pytest.mark.parametrize(
    ("path", "message"),
    [
        (("scope_id",), "case claim identity"),
        (("handoff", "handoff_sha256"), "handoff projection"),
        (("handoff", "nonce_hex"), "handoff projection"),
        (("replay", "post_generation"), "replay projection"),
        (("replay", "consumption_id_sha256"), "replay projection"),
    ],
)
def test_digest_nonce_scope_and_generation_claim_mismatches_fail_closed(
    path: tuple[str, ...], message: str,
) -> None:
    rows = _fixtures()
    case_id = matrix_v5._frozen_rows()[0][1]
    target: Any = rows[case_id]["case_claim"]
    for key in path[:-1]:
        target = target[key]
    field = path[-1]
    if field == "scope_id":
        target[field] = "other-scope"
    elif field == "post_generation":
        target[field] += 2
    else:
        target[field] = "f" * 64 if "sha" in field or "id" in field else "e" * 32
    with pytest.raises(adapter.TrustedPostrunMatrixClaimAdapterError, match=message):
        adapter.bind_synthetic_postrun_matrix_claims(rows)


def test_cross_case_case_id_and_replay_reuse_fail_closed() -> None:
    rows = _fixtures()
    case_ids = matrix_v5._frozen_rows()[0]
    rows[case_ids[1]]["case_claim"]["case_id"] = case_ids[0]
    with pytest.raises(adapter.TrustedPostrunMatrixClaimAdapterError, match="case claim identity"):
        adapter.bind_synthetic_postrun_matrix_claims(rows)

    rows = _fixtures()
    rows[case_ids[1]]["case_claim"]["replay"]["consumption_id_sha256"] = (
        rows[case_ids[0]]["case_claim"]["replay"]["consumption_id_sha256"]
    )
    with pytest.raises(adapter.TrustedPostrunMatrixClaimAdapterError, match="replay projection"):
        adapter.bind_synthetic_postrun_matrix_claims(rows)


def test_trusted_issuer_and_subject_projection_must_match_shared_identity() -> None:
    rows = _fixtures()
    case_id = matrix_v5._frozen_rows()[0][2]
    rows[case_id]["case_claim"]["handoff"]["issuer"]["active_key_id"] = "other-key"
    with pytest.raises(adapter.TrustedPostrunMatrixClaimAdapterError, match="handoff projection"):
        adapter.bind_synthetic_postrun_matrix_claims(rows)


def test_adapter_is_disjoint_from_postrun_workers_and_report_is_fixed() -> None:
    source = inspect.getsource(adapter)
    assert "f8_r008_postrun_case_worker_v1" not in source
    assert "f8_r008_postrun_matrix_worker_v1" not in source
    assert "materialize_postrun_case_worker_v1" not in source
    assert "materialize_postrun_matrix_worker_v1" not in source

    report = adapter.build_report()
    assert report["schema"] == adapter.REPORT_SCHEMA
    assert report["matrix_contract"]["case_count"] == 15
    assert report["matrix_contract"]["postrun_case_worker_called"] is False
    assert report["matrix_contract"]["postrun_matrix_worker_called"] is False
    assert report["non_authorizing_boundary"] == adapter.NON_AUTHORIZING_BOUNDARY

    report_path = Path(__file__).resolve().parents[1] / (
        "reports/F8-R008-TRUSTED-WORKER-RUNTIME-POSTRUN-MATRIX-CLAIM-ADAPTER-V1.json"
    )
    assert json.loads(report_path.read_text(encoding="utf-8")) == report
