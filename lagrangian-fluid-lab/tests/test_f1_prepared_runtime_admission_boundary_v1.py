from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path

import pytest

from scripts import f1_prepared_runtime_admission_boundary_v1 as boundary


LAB_ROOT = Path(__file__).parents[1]


def _request_from_context(context: dict) -> dict:
    source = {
        "definition_sha256": "1" * 64,
        "core_manifest_sha256": "2" * 64,
        "known_inputs_sha256": "3" * 64,
        "solver_binary_sha256": "4" * 64,
        "runtime_identity_sha256": "5" * 64,
        "per_cell_source_hashes": [{"index": index, "sha256": f"{index + 10:064x}"} for index in range(15)],
        "trusted_root_attested": False,
    }
    return {
        "schema": boundary.REQUEST_SCHEMA,
        "request_id": "f1-admission-fixture-20260929",
        "boundary_id": boundary.BOUNDARY_ID,
        "scope_id": context["scope_id"],
        "prepared_revision": context["prepared_revision"],
        "matrix_sha256": context["matrix_sha256"],
        "design_sha256": context["design_sha256"],
        "observer_binding": {
            "revision_id": context["observer_revision"],
            "code_sha256": context["observer_code_sha256"],
            "observable_names_sha256": context["observable_names_sha256"],
            "runtime_instance_attested": False,
        },
        "source_identity": source,
        "rows": [
            {
                "index": row["index"],
                "case_id": row["case_id"],
                "prepared_path_metadata": row["prepared_path_metadata"],
                "prepared_row_sha256": row["prepared_row_sha256"],
                "job_id": row["job_id"],
                "required_outputs": list(boundary.REQUIRED_OUTPUTS),
                "namespace_id": f"future-f1-cell-{row['index']:02d}",
            }
            for row in context["rows"]
        ],
        "terminal_contract": {
            "required_outputs": list(boundary.REQUIRED_OUTPUTS),
            "terminal_evidence_schema": "core.f1.runtime.terminal_evidence.v1",
            "missing_outputs_are_failure": True,
            "no_survivor_renormalization": True,
        },
        "authorization": {"fresh_root_review": False, "execution_authorized": False},
    }


def test_current_boundary_derives_fifteen_bindings_without_admission() -> None:
    report = boundary.build_report()

    assert report["status"] == "blocked_fail_closed"
    assert report["boundary"] == {
        "boundary_id": boundary.BOUNDARY_ID,
        "input_class": "prepared_metadata_only",
        "prepared_rows": 15,
        "runtime_rows_admitted": 0,
        "admission_envelope_present": False,
        "admission_contract_valid": False,
        "prepared_row_bindings_derived": True,
        "runtime_receipts_present": False,
        "nested_artifact_paths_followed": False,
    }
    assert len(report["prepared_context"]["rows"]) == 15
    assert [row["index"] for row in report["prepared_context"]["rows"]] == list(range(15))
    assert all(row["runtime_receipt_required"] for row in report["prepared_context"]["rows"])
    assert all(row["prepared_cell_json_opened"] is False for row in report["prepared_context"]["rows"])
    assert report["authorization"]["formal"] is False
    assert report["authorization"]["T1_numerical"] is False
    assert report["authorization"]["credit"] == 0


def test_shape_valid_request_remains_non_authorizing() -> None:
    context = boundary.build_report()["prepared_context"]
    request = _request_from_context(context)

    observation = boundary.validate_admission_request(request, context)

    assert observation == {
        "contract_valid": True,
        "prepared_rows_bound": 15,
        "runtime_observer_instance_attested": False,
        "trusted_source_root_attested": False,
        "terminal_evidence_present": False,
        "fresh_root_review": False,
        "execution_authorized": False,
        "launch_admitted": False,
        "formal": False,
        "T1_numerical": False,
        "credit": 0,
    }


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("source_identity", "trusted_root_attested"), True, "caller cannot attest trusted source root"),
        (("observer_binding", "runtime_instance_attested"), True, "caller cannot attest runtime observer instance"),
        (("authorization", "fresh_root_review"), True, "caller cannot declare fresh root review"),
        (("authorization", "execution_authorized"), True, "caller cannot declare execution authorization"),
    ],
)
def test_caller_claims_cannot_mint_authority(path: tuple[str, str], value: bool, message: str) -> None:
    context = boundary.build_report()["prepared_context"]
    request = _request_from_context(context)
    request[path[0]][path[1]] = value

    with pytest.raises(boundary.AdmissionBoundaryError, match=message):
        boundary.validate_admission_request(request, context)


def test_row_digest_and_namespace_binding_fail_closed() -> None:
    context = boundary.build_report()["prepared_context"]

    request = _request_from_context(context)
    request["rows"][4]["prepared_row_sha256"] = "f" * 64
    with pytest.raises(boundary.AdmissionBoundaryError, match="admission row binding drift at 4"):
        boundary.validate_admission_request(request, context)

    request = _request_from_context(context)
    request["rows"][4]["namespace_id"] = "../../runtime"
    with pytest.raises(boundary.AdmissionBoundaryError, match="namespace path-like token at 4"):
        boundary.validate_admission_request(request, context)


def test_formal_or_t1_claim_is_not_part_of_request_schema() -> None:
    context = boundary.build_report()["prepared_context"]
    request = _request_from_context(context)
    request["formal"] = True

    with pytest.raises(boundary.AdmissionBoundaryError, match="admission envelope fields differ"):
        boundary.validate_admission_request(request, context)


def test_strict_reader_rejects_non_json_before_open(tmp_path: Path) -> None:
    trajectory = tmp_path / "trajectory.h5"
    trajectory.write_bytes(b"not opened")

    with pytest.raises(boundary.AdmissionBoundaryError, match="non-JSON dependency rejected before open"):
        boundary._read_bounded_json(tmp_path, trajectory, role="test")


def test_strict_reader_rejects_duplicate_keys(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")

    with pytest.raises(boundary.AdmissionBoundaryError, match="duplicate JSON object key"):
        boundary._read_bounded_json(tmp_path, path, role="test")


def test_strict_reader_rejects_symlink_before_following_it(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text('{"schema":"x"}', encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)

    with pytest.raises(boundary.AdmissionBoundaryError, match="symlink dependency component rejected"):
        boundary._read_bounded_json(tmp_path, link, role="test")


def test_report_mutation_is_rejected() -> None:
    report = copy.deepcopy(boundary.build_report())
    report["authorization"]["launch_admitted"] = True

    with pytest.raises(boundary.AdmissionBoundaryError, match="authorization promotion detected"):
        boundary.validate_report(report)


def test_checked_in_report_and_campaign_are_bounded() -> None:
    report_path = LAB_ROOT / "reports/F1-PREPARED-RUNTIME-ADMISSION-BOUNDARY-V1-2026-09-29.json"
    campaign_path = LAB_ROOT / "campaigns/core-v1/cfd/f1-prepared-runtime-admission-v1.json"
    assert boundary.verify_report(report_path) == json.loads(report_path.read_text(encoding="utf-8"))

    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    assert campaign["status"] == "contract_only_blocked"
    assert campaign["execution"]["launch_allowed"] is False
    assert campaign["authorization"]["formal"] is False
    assert campaign["authorization"]["T1_numerical"] is False
    assert campaign["authorization"]["credit"] == 0


def test_component_has_no_execution_or_production_reader_surface() -> None:
    source = inspect.getsource(boundary)

    for forbidden in (
        "import h5py",
        "import numpy",
        "import subprocess",
        "import torch",
        "CUDA_VISIBLE_DEVICES",
        "nvidia-smi",
        "os.system",
        "subprocess.Popen",
    ):
        assert forbidden not in source
    assert boundary.READ_POLICY["nested_artifact_paths_followed"] is False
    assert boundary.READ_POLICY["runtime_result_audit_observation_trajectory_opened"] is False
    assert boundary.SIDE_EFFECTS["solver_started"] is False
    assert boundary.SIDE_EFFECTS["gpu_started"] is False
