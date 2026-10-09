from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
REQUEST = (
    ROOT
    / "campaigns/ds-data-02/stage2/requests/"
    / "full-goal-rollup-v155-final-code-bound-root-prepared-159-002/"
    / "full-goal-rollup-v155-final-code-bound-request.json"
)
TRANSITION = REQUEST.with_name("full-goal-rollup-v155-final-code-bound-manifest.json")
OLD_REQUEST = (
    ROOT
    / "campaigns/ds-data-02/stage2/requests/"
    / "full-goal-rollup-v155-root-prepared-155-001/"
    / "full-goal-rollup-v155-request.json"
)
OLD_MANIFEST = OLD_REQUEST.with_name("full-goal-rollup-v155-manifest.json")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_final_code_bound_request_rechecks_every_final_input() -> None:
    request = read_json(REQUEST)
    old = read_json(OLD_REQUEST)
    transition = read_json(TRANSITION)

    assert request["schema"] == request["request_schema"] == "ds02.request.v1"
    assert request["case_id"] == "DS02_STAGE2_FULL_GOAL_ROLLUP_V155"
    assert request["attempt_id"] == "full-goal-rollup-v155-final-code-bound-root-forward-159-002"
    assert request["status"] == "prepared_corrected_source_binding_guard_pending"
    assert len(request["input_files"]) == len(set(request["input_files"])) == 116
    assert set(request["input_files"]) == set(request["input_sha256"])

    for raw_path, expected in request["input_sha256"].items():
        path = Path(raw_path)
        assert path.is_file(), path
        assert sha256_file(path) == expected, path
        assert path.suffix.lower() in {".json", ".py"}, path

    worker = Path(request["command"][1])
    manifest = Path(request["command"][3])
    assert worker.is_file()
    assert manifest == OLD_MANIFEST.resolve()
    assert request["input_sha256"][str(worker)] == (
        "3fc9353eb5ce6102f029757bbcfd699773ab7b5b4464514b9013950c1ffe5e79"
    )
    assert request["input_sha256"][str(manifest)] == sha256_file(manifest)
    assert request["output"]["path"] == "{attempt_root}/full-goal-rollup-v155-final-code-bound.json"
    assert request["command"][-1] == request["output"]["path"]

    old_input_hashes = old["input_sha256"]
    new_input_hashes = request["input_sha256"]
    for raw_path, old_hash in old_input_hashes.items():
        if raw_path == str(worker):
            assert old_hash == (
                "ffc3f021f283ad73433bc6c2a7d0d24c87ec6d8b74568c58660e93f7d901d809"
            )
            assert new_input_hashes[raw_path] != old_hash
        else:
            assert new_input_hashes[raw_path] == old_hash

    assert transition["schema"] == "ds02.stage2.full-goal-rollup-v155.final-code-bound.manifest.v1"
    assert transition["original_request"]["path"] == str(OLD_REQUEST.resolve())
    assert transition["original_request"]["sha256"] == sha256_file(OLD_REQUEST)
    assert transition["unchanged_rollup_manifest"]["path"] == str(OLD_MANIFEST.resolve())
    assert transition["unchanged_rollup_manifest"]["sha256"] == sha256_file(OLD_MANIFEST)
    assert transition["worker_transition"]["original_request_sha256"] == old_input_hashes[str(worker)]
    assert transition["worker_transition"]["final_worker_sha256"] == new_input_hashes[str(worker)]
    assert transition["binding_audit"]["status"] == "STALE_OLD_REQUEST_WORKER_BINDING"
    assert transition["forward_contract"]["old_request_modified"] is False
    assert transition["forward_contract"]["old_manifest_modified"] is False
    assert request["source_binding_transition"]["transition_manifest_sha256"] == sha256_file(TRANSITION)


def test_final_code_bound_request_preserves_science_and_read_gates() -> None:
    request = read_json(REQUEST)
    old = read_json(OLD_REQUEST)
    assert request["claim_boundary"] == old["claim_boundary"]
    assert request["hdf5_read"] is False
    assert request["read_policy"]["h5_opened"] is False
    assert request["read_policy"]["bi4_opened"] is False
    assert request["read_policy"]["vtk_opened"] is False
    assert request["read_policy"]["solver_started"] is False
    assert request["read_policy"]["old_products_modified"] is False
    assert request["source_cost"]["hdf5_bytes_read"] == 0
    assert request["source_cost"]["bi4_bytes_read"] == 0
    assert request["source_cost"]["native_payload_bytes_read"] == 0
