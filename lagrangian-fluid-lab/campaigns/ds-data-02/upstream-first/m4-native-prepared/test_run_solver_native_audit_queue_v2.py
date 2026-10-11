"""Focused tests for the M4 solver/native-audit queue gates."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).with_name("run_solver_native_audit_queue_v2.py")
SPEC = importlib.util.spec_from_file_location("m4_native_queue", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
QUEUE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUEUE)


def test_case_aliases_and_solver_contract_are_root_bound() -> None:
    case = QUEUE._case_id("H052")
    assert case == "UF_F1_MDBC_DP010_H052"
    request = QUEUE._solver_request(case)
    grant = QUEUE._validate_solver_grant(case, request)
    assert request["estimated_storage_bytes"] == 9 * 1024**3
    assert request["time_max_s"] == 6.0
    assert request["time_out_s"] == 0.025
    assert request["dp_m"] == 0.01
    assert request["expected_frames"] == 241
    assert grant["attempt_id"] == f"F1/{case}/solver-001"


@pytest.mark.parametrize("status", ["running", "failed"])
def test_running_or_failed_receipts_fail_closed(tmp_path: Path, status: str) -> None:
    receipt = tmp_path / "execution-receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": QUEUE.RECEIPT_SCHEMA,
                "status": status,
                "request": {"case_id": "UF_F1_MDBC_DP010_H052", "attempt_id": "solver-001"},
            }
        ),
        encoding="utf-8",
    )
    state, _ = QUEUE._receipt_state(receipt, "UF_F1_MDBC_DP010_H052", "solver-001")
    assert state == status


def test_completed_receipt_requires_case_bound_terminal_returncode(tmp_path: Path) -> None:
    receipt = tmp_path / "execution-receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": QUEUE.RECEIPT_SCHEMA,
                "status": "completed",
                "request": {"case_id": "UF_F1_MDBC_DP010_H052", "attempt_id": "solver-001"},
            }
        ),
        encoding="utf-8",
    )
    state, _ = QUEUE._receipt_state(receipt, "UF_F1_MDBC_DP010_H052", "solver-001")
    assert state == "invalid"


def test_promotion_cannot_change_scientific_fields() -> None:
    candidate = {"case_id": "UF_F1_MDBC_DP010_H052", "time_out_s": 0.025, "status": "candidate"}
    promoted = copy.deepcopy(candidate)
    promoted["status"] = "root_authorized"
    QUEUE._assert_only_promotion_fields_changed(candidate, promoted)

    promoted["time_out_s"] = 0.01
    with pytest.raises(QUEUE.QueueError, match="non-authorization"):
        QUEUE._assert_only_promotion_fields_changed(candidate, promoted)


def test_frame_input_name_is_deferred_contract() -> None:
    assert QUEUE.FRAME_RE.fullmatch("Part_0000.bi4")
    assert QUEUE.FRAME_RE.fullmatch("Part_0240.bi4")
    assert not QUEUE.FRAME_RE.fullmatch("PartInfo.ibi4")


def test_completed_stage_rejects_missing_or_wrong_request_hash(tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    request.write_text('{"case_id":"UF_F1_MDBC_DP010_H052"}\n', encoding="utf-8")
    receipt = {"request_sha256": QUEUE._sha256(request)}
    QUEUE._assert_receipt_request_binding(
        receipt, request, "UF_F1_MDBC_DP010_H052", "solver-001"
    )

    missing = dict(receipt)
    missing.pop("request_sha256")
    with pytest.raises(QUEUE.QueueError, match="request_sha256"):
        QUEUE._assert_receipt_request_binding(
            missing, request, "UF_F1_MDBC_DP010_H052", "solver-001"
        )

    wrong = dict(receipt)
    wrong["request_sha256"] = "0" * 64
    with pytest.raises(QUEUE.QueueError, match="request_sha256"):
        QUEUE._assert_receipt_request_binding(
            wrong, request, "UF_F1_MDBC_DP010_H052", "solver-001"
        )


def test_exact_source_binding_rejects_a_case_path_swap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected_path = tmp_path / "UF_F1_MDBC_DP010_H052" / "Run.out"
    expected_path.parent.mkdir()
    expected_path.write_text("case-specific metadata\n", encoding="utf-8")
    swapped_path = tmp_path / "UF_F1_MDBC_DP010_H058" / "Run.out"
    swapped_path.parent.mkdir()
    swapped_path.write_text("different case\n", encoding="utf-8")
    monkeypatch.setattr(
        QUEUE,
        "_expected_native_source_paths",
        lambda case, mode: {"run_out": expected_path},
    )
    good = {"source_bindings": {"run_out": QUEUE._binding(expected_path, "fixture")}}
    QUEUE._assert_exact_native_source_bindings(good, "UF_F1_MDBC_DP010_H052", "exclusions")
    bad = {"source_bindings": {"run_out": QUEUE._binding(swapped_path, "fixture")}}
    with pytest.raises(QUEUE.QueueError, match="exact child file"):
        QUEUE._assert_exact_native_source_bindings(bad, "UF_F1_MDBC_DP010_H052", "exclusions")


def test_auditor_stdout_is_bound_to_report_and_execution_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt_root = tmp_path / "native-integrity-001"
    attempt_root.mkdir()
    report = attempt_root / "integrity.json"
    report.write_text(json.dumps({"status": "verified"}, sort_keys=True) + "\n", encoding="utf-8")
    stdout = attempt_root / "stdout.log"
    stdout.write_text(
        json.dumps({"path": str(report.resolve()), "status": "verified"}) + "\n",
        encoding="utf-8",
    )
    receipt_path = attempt_root / "execution-receipt.json"
    receipt_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        QUEUE,
        "_paths",
        lambda case: {
            "integrity_root": attempt_root,
            "frame_root": tmp_path / "frame",
            "integrity_receipt": receipt_path,
            "frame_receipt": tmp_path / "frame-receipt.json",
        },
    )
    receipt = {
        "stdout_sha256": QUEUE._sha256(stdout),
        "output_root": str(attempt_root.resolve()),
    }
    binding = QUEUE._assert_runner_report_binding(
        "UF_F1_MDBC_DP010_H052", "native-integrity-001", report, receipt
    )
    assert binding["report_sha256"] == QUEUE._sha256(report)

    stdout.write_text(stdout.read_text(encoding="utf-8") + "tampered", encoding="utf-8")
    with pytest.raises(QUEUE.QueueError, match="stdout_sha256"):
        QUEUE._assert_runner_report_binding(
            "UF_F1_MDBC_DP010_H052", "native-integrity-001", report, receipt
        )


def test_prepared_frame_sequence_uses_metadata_without_opening_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "solver-001" / "data"
    monkeypatch.setattr(QUEUE, "_paths", lambda case: {"solver_data": data_root})
    frame_bindings = []
    expected = hashlib.sha256()
    deferred = []
    for index in range(QUEUE.EXPECTED_FRAMES):
        name = f"Part_{index:04d}.bi4"
        path = data_root / name
        size = index + 1
        digest = f"{index + 1:064x}"
        frame_bindings.append({"path": str(path), "bytes": size, "sha256": digest})
        deferred.append(str(path.resolve()))
        expected.update(name.encode("ascii"))
        expected.update(b"\0")
        expected.update(str(size).encode("ascii"))
        expected.update(b"\0")
        expected.update(digest.encode("ascii"))
        expected.update(b"\n")
    candidate = {
        "actual_solver_binding": {
            "regular_native_solver_files": frame_bindings,
            "frame_files_deferred_from_input_files": deferred,
        }
    }
    assert QUEUE._prepared_frame_hash_sequence(candidate, "UF_F1_MDBC_DP010_H052") == expected.hexdigest()

    frame_bindings[-1] = dict(frame_bindings[-1], bytes=999)
    # The metadata remains structurally valid; recomputing here proves the
    # sequence changes when a prepared source binding changes.
    assert QUEUE._prepared_frame_hash_sequence(candidate, "UF_F1_MDBC_DP010_H052") != expected.hexdigest()


def _write(path: Path, payload: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return path


def _frozen_worker_candidate_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> tuple[Path, Path, dict[str, Path]]:
    """Build only metadata-shaped frozen-worker output; never create frames."""

    case = "UF_F1_MDBC_DP010_H052"
    root = tmp_path / "campaign-root"
    runs = tmp_path / "runs"
    additional = tmp_path / "additional"
    m2 = tmp_path / "m2" / "upstream_conversion"
    run = runs / case
    gencase = run / "gencase-001"
    solver = run / "solver-001"
    data = solver / "data"
    manifest_path = additional / "prepared" / ("native-exclusions" if mode == "exclusions" else "native-frames") / f"{case}-{'native-integrity-001' if mode == 'exclusions' else 'native-frame-scan-001'}-manifest.json"
    candidate_path = manifest_path.with_name(manifest_path.name.replace("-manifest.json", "-request.json"))
    definition = additional / f"{case}_Def.xml"
    case_manifest = additional / "manifests" / f"{case}.json"
    ds_config = root / "DsphConfig.xml"
    partvtk = root / "PartVTKOut_linux64"
    auditor = m2 / ("native_integrity_audit.py" if mode == "exclusions" else "native_frame_identity_scan.py")
    frozen_helper = additional / "prepare_m4_additional_audits.py"
    legacy_queue = root / "run_solver_native_audit_queue.py"
    for path in (definition, ds_config, partvtk, auditor, frozen_helper, legacy_queue):
        _write(path, "metadata fixture\n")
    xml = _write(
        gencase / f"{case}.xml",
        '<root><definition dp="0.01"/><execution><parameters>'
        '<parameter key="TimeMax" value="6"/>'
        '<parameter key="TimeOut" value="0.025"/>'
        '</parameters></execution></root>\n',
    )
    gencase_receipt = _write(gencase / "execution-receipt.json", "gencase metadata\n")
    for rel in ("PartInfo.ibi4", "PartOut_000.obi4"):
        _write(data / rel, f"{rel} metadata\n")
    run_out = _write(solver / "Run.out", "Run metadata\n")
    runparts = _write(solver / "RunPARTs.csv", "Run metadata\n")

    solver_request_path = tmp_path / "requests" / f"{case}-solver-001.json"
    solver_request = {
        "schema": QUEUE.REQUEST_SCHEMA,
        "family_id": "F1",
        "case_id": case,
        "attempt_id": "solver-001",
        "kind": "qualification",
        "output_storage": "upstream_nas",
        "estimated_storage_bytes": QUEUE.SOLVER_STORAGE,
        "expected_frames": QUEUE.EXPECTED_FRAMES,
        "time_max_s": 6.0,
        "time_out_s": 0.025,
        "dp_m": 0.01,
        "command": ["solver", "-gpu"],
        "gencase_receipt_sha256": "fixture-gencase",
        "actual_gencase_binding": {},
    }
    solver_request_path.parent.mkdir(parents=True, exist_ok=True)
    solver_request_path.write_text(json.dumps(solver_request), encoding="utf-8")
    solver_receipt = {
        "schema": QUEUE.RECEIPT_SCHEMA,
        "status": "completed",
        "returncode": 0,
        "request": {"case_id": case, "attempt_id": "solver-001"},
        "request_sha256": QUEUE._sha256(solver_request_path),
    }
    solver_receipt_path = _write(solver / "execution-receipt.json", json.dumps(solver_receipt))

    recipe_manifest = {
        "schema": "fixture.case-manifest.v1",
        "case_id": case,
        "numerical_output_recipe": {
            "dp_m": 0.01,
            "time_max_s": 6.0,
            "source_time_out_s": 0.01,
            "candidate_time_out_s": 0.025,
            "estimated_saved_frames": 241,
            "expected_frames": 241,
        },
    }
    case_manifest.parent.mkdir(parents=True, exist_ok=True)
    case_manifest.write_text(json.dumps(recipe_manifest), encoding="utf-8")

    sources = {
        "dsph_config": ds_config,
        "gencase_receipt": gencase_receipt,
        "generated_xml": xml,
        "part_info": data / "PartInfo.ibi4",
        "partvtk": partvtk,
        "raw_partout": data / "PartOut_000.obi4",
        "run_out": run_out,
        "runparts": runparts,
        "solver_receipt": solver_receipt_path,
        "source_definition": definition,
    }
    native_integrity = run / "native-integrity-001" / "integrity.json"
    if mode == "frames":
        _write(native_integrity, '{"schema":"fixture.integrity","status":"verified"}\n')
        sources["native_integrity"] = native_integrity
    source_bindings = {key: QUEUE._binding(path, f"fixture {key}") for key, path in sources.items()}
    manifest = {
        "schema": "ds-data-02.upstream-first.native-integrity-manifest.v1" if mode == "exclusions" else "ds-data-02.upstream-first.native-frame-scan-manifest.v1",
        "case_id": case,
        "m4_additional": True,
        "m3_completion_claim": False,
        "solver_root": str(solver.resolve()),
        "source" if mode == "exclusions" else "sources": source_bindings,
        "expected": {"frame_count": QUEUE.EXPECTED_FRAMES} if mode == "frames" else {},
    }
    if mode == "frames":
        manifest["data_root"] = str(data.resolve())
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    regular = [
        {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": QUEUE._sha256(path)}
        for path in (solver / "Run.out", solver / "RunPARTs.csv", data / "PartInfo.ibi4", data / "PartOut_000.obi4", solver_receipt_path)
    ]
    deferred: list[str] = []
    if mode == "frames":
        for index in range(QUEUE.EXPECTED_FRAMES):
            frame = data / f"Part_{index:04d}.bi4"
            # Metadata only: the file is deliberately absent so this test
            # cannot scan or hash a native trajectory payload.
            regular.append({"path": str(frame.resolve()), "bytes": index + 1, "sha256": f"{index + 1:064x}"})
            deferred.append(str(frame.resolve()))
    actual_solver_binding = {
        "receipt": QUEUE._binding(solver_receipt_path, "fixture solver receipt"),
        "regular_native_solver_files": regular,
    }
    if mode == "frames":
        actual_solver_binding["frame_files_deferred_from_input_files"] = deferred
    expected_command = [
        str(QUEUE.PYTHON),
        str(auditor),
        "--manifest",
        str(manifest_path),
        "--output",
        "{attempt_root}/integrity.json" if mode == "exclusions" else "{attempt_root}/frame-identity-scan.json",
    ]
    if mode == "frames":
        expected_command.extend(["--max-wall-seconds", "3600"])
    candidate = {
        "schema": QUEUE.REQUEST_SCHEMA,
        "family_id": "F1",
        "case_id": case,
        "attempt_id": "native-integrity-001" if mode == "exclusions" else "native-frame-scan-001",
        "m4_additional": True,
        "m3_completion_claim": False,
        "submission_forbidden": True,
        "native_audit_launch_forbidden": True,
        "kind": "cpu",
        "cpu_task_kind": "conversion",
        "cpu_threads": 1,
        "output_storage": "upstream_nas",
        "max_wall_seconds": QUEUE.NATIVE_INTEGRITY_MAX_WALL if mode == "exclusions" else QUEUE.NATIVE_FRAME_MAX_WALL,
        "estimated_storage_bytes": QUEUE.NATIVE_INTEGRITY_STORAGE if mode == "exclusions" else QUEUE.NATIVE_FRAME_STORAGE,
        "estimated_temp_peak_bytes": QUEUE.NATIVE_INTEGRITY_TEMP if mode == "exclusions" else QUEUE.NATIVE_FRAME_TEMP,
        "estimated_deferred_read_bytes": 0 if mode == "exclusions" else 241,
        "cwd": str(root),
        "worktree_root": str(root),
        "command": expected_command,
        "actual_gencase_receipt_sha256": QUEUE._sha256(gencase_receipt),
        "actual_solver_receipt_sha256": QUEUE._sha256(solver_receipt_path),
        "actual_solver_binding": actual_solver_binding,
        "input_files": [str(path.resolve()) for path in sources.values()],
        "input_bindings": {str(path.resolve()): QUEUE._binding(path, "fixture input") for path in sources.values()},
    }
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    monkeypatch.setattr(QUEUE, "ROOT", root)
    monkeypatch.setattr(QUEUE, "RUNS", runs)
    monkeypatch.setattr(QUEUE, "ADDITIONAL", additional)
    monkeypatch.setattr(QUEUE, "M2", m2)
    monkeypatch.setattr(QUEUE, "REQUESTS", tmp_path / "requests")
    monkeypatch.setattr(QUEUE, "GRANTS", tmp_path / "grants")
    monkeypatch.setattr(QUEUE, "DS_CONFIG", ds_config)
    monkeypatch.setattr(QUEUE, "PARTVTK", partvtk)
    monkeypatch.setattr(QUEUE, "HELPER", frozen_helper)
    monkeypatch.setattr(QUEUE, "LEGACY_SCRIPT", legacy_queue)
    return manifest_path, candidate_path, {"case_manifest": case_manifest, "solver_request": solver_request_path}


def test_actual_frozen_worker_h052_exclusion_candidate_accepts_without_flat_recipe() -> None:
    case = "UF_F1_MDBC_DP010_H052"
    manifest, candidate = QUEUE._audit_candidate_paths(case, "exclusions")
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    assert "time_max_s" not in payload
    assert "time_out_s" not in payload
    assert "dp_m" not in payload
    result = QUEUE._validate_native_candidate(candidate, manifest, case, "exclusions")
    assert result["recipe"]["expected_frames"] == QUEUE.EXPECTED_FRAMES
    assert result["manifest"]["source"]["generated_xml"]["path"].endswith(f"{case}.xml")


@pytest.mark.parametrize("mode", ["exclusions", "frames"])
def test_frozen_worker_shaped_candidate_accepts_metadata_only_recipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    manifest, candidate, _ = _frozen_worker_candidate_fixture(tmp_path, monkeypatch, mode)
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    assert not {"time_max_s", "time_out_s", "dp_m"}.intersection(payload)
    result = QUEUE._validate_native_candidate(candidate, manifest, "UF_F1_MDBC_DP010_H052", mode)
    assert result["recipe"]["dp_m"] == 0.01
    assert result["recipe"]["time_max_s"] == 6.0
    assert result["recipe"]["time_out_s"] == 0.025
    assert result["recipe"]["expected_frames"] == 241


def test_wrong_actual_recipe_is_rejected_even_when_candidate_omits_flat_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, candidate, paths = _frozen_worker_candidate_fixture(tmp_path, monkeypatch, "exclusions")
    recipe_manifest = json.loads(paths["case_manifest"].read_text(encoding="utf-8"))
    recipe_manifest["numerical_output_recipe"]["candidate_time_out_s"] = 0.01
    paths["case_manifest"].write_text(json.dumps(recipe_manifest), encoding="utf-8")
    with pytest.raises(QUEUE.QueueError, match="recipe"):
        QUEUE._validate_native_candidate(candidate, manifest, "UF_F1_MDBC_DP010_H052", "exclusions")


def test_optional_candidate_recipe_copy_must_match_bound_recipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, candidate, _ = _frozen_worker_candidate_fixture(tmp_path, monkeypatch, "exclusions")
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    payload["time_out_s"] = 0.01
    candidate.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(QUEUE.QueueError, match="optional candidate recipe"):
        QUEUE._validate_native_candidate(candidate, manifest, "UF_F1_MDBC_DP010_H052", "exclusions")


def test_completed_h052_preparation_is_reused_without_duplicate_or_mutation() -> None:
    case = "UF_F1_MDBC_DP010_H052"
    request_path = QUEUE._root_request_path(case, "native-preparation-integrity-001")
    grant_path = QUEUE._root_grant_path(case, "native-preparation-integrity-001")
    before = (request_path.read_bytes(), grant_path.read_bytes())
    reused = QUEUE._reuse_completed_preparation(case, "exclusions")
    assert reused == (request_path, grant_path)
    assert (request_path.read_bytes(), grant_path.read_bytes()) == before
