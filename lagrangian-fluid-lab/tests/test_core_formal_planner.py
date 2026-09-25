import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import scripts.core_formal_planner as formal_planner

from scripts.core_formal_planner import (CASES_PER_FAMILY, MODELS, REQUIRED_CODE_FILES,
                                         SEEDS, _qualification_marker, build_plan, inspect_inputs,
                                         main, sha256_bytes, sha256_file)


def _manifest(tmp_path, *, family_count=3):
    families = ("F1", "F2", "F4")[:family_count]
    cases = []
    for family in families:
        for index in range(CASES_PER_FAMILY):
            split = "train" if index < 16 else "validation" if index < 20 else "test"
            cases.append({
                "case_id": f"{family}_PROD_{index:02d}",
                "physical_case_id": f"{family}_PHYSICAL_{index:02d}",
                "lineage_group_id": f"{family}_LINEAGE_{index:02d}",
                "family": family, "split": split, "stage": "production",
                "scope_id": f"{family}_scope_v1", "recipe_id": f"{family}_recipe_v1",
                "qualification_case": False, "qualification_only": False,
                "T1_numerical": True,
                "audit": {"hard_integrity_pass": True, "structural_pass": True},
            })
    payload = {"schema": "core.dataset.v2", "dataset_id": "fixture-formal",
               "formal_release": True, "cases": cases}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload))
    return path, payload


def _profile():
    return {"schema": "core.measured_resource_profile.v1", "host": "h200",
            "resources": {"cpu_cores": 4, "ram_mib": 8192, "gpu_peak_mib": 10240,
                          "io_weight": 0.1}}


def _environment():
    return {"id": "fixture-python", "python_executable": sys.executable}


def _ready_plan(tmp_path):
    manifest_path, _ = _manifest(tmp_path)
    return build_plan(manifest_path, profile=_profile(), environment=_environment(),
                      data_root=tmp_path, code_root=Path(__file__).parents[1],
                      output_dir=tmp_path / "specs")


def test_complete_metadata_manifest_cannot_authorize_nine_formal_jobs(tmp_path):
    plan = _ready_plan(tmp_path)
    assert plan["status"] == "hold"
    assert plan["launch_allowed"] is False
    assert plan["formal_job_count"] == 0
    assert plan["required_job_count"] == len(MODELS) * len(SEEDS) == 9
    assert plan["spec_paths"] == []
    assert plan["audit"]["formal_eligible"] is False
    assert plan["audit"]["admission_basis"] == "metadata_only_untrusted"
    assert set(plan["audit"]["family_t1"].values()) == {None}
    assert any("trusted formal admission capability is unavailable"
               in reason for reason in plan["hold_reasons"])
    assert not (tmp_path / "specs").exists()


def test_planner_script_entrypoint_imports_shared_strict_json_module():
    completed = subprocess.run(
        [sys.executable, "scripts/core_formal_planner.py", "--help"],
        cwd=Path(__file__).parents[1], capture_output=True, text=True,
        timeout=5, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "{plan}" in completed.stdout


def test_complete_in_memory_mapping_is_also_diagnostic_only(tmp_path):
    _, payload = _manifest(tmp_path)
    report = inspect_inputs(payload)
    plan = build_plan(
        payload, profile=_profile(), environment=_environment(),
        data_root=tmp_path, code_root=Path(__file__).parents[1],
    )
    assert report["formal_eligible"] is False
    assert report["admission_basis"] == "metadata_only_untrusted"
    assert report["family_t1"] == {"F1": None, "F2": None, "F4": None}
    assert plan["status"] == "hold"
    assert plan["launch_allowed"] is False
    assert plan["formal_job_count"] == 0


@pytest.mark.parametrize("raw", [
    b'{"schema":"core.dataset.v2","schema":"core.dataset.v3","cases":[]}',
    b'{"schema":"core.dataset.v2","cases":[],"marker":NaN}',
    b'{"schema":"core.dataset.v2","cases":[],"marker":1e400}',
    b'{"schema":"core.dataset.v2","cases":[],"marker":' + b"9" * 129 + b"}",
    b'{"schema":"core.dataset.v2","label":"\xff"}',
])
def test_path_backed_manifest_requires_bounded_strict_raw_json(tmp_path, raw):
    manifest_path = tmp_path / "strict-manifest.json"
    manifest_path.write_bytes(raw)
    specs = tmp_path / "specs"
    with pytest.raises(ValueError):
        build_plan(
            manifest_path,
            profile=_profile(), environment=_environment(), data_root=tmp_path,
            code_root=Path(__file__).parents[1], output_dir=specs,
        )
    assert not specs.exists()


def test_path_backed_manifest_enforces_configured_byte_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(formal_planner, "MAX_PLANNER_JSON_BYTES", 32)
    manifest_path = tmp_path / "oversized-manifest.json"
    manifest_path.write_bytes(b"{" + b" " * 32 + b"}")
    with pytest.raises(ValueError, match="byte limit"):
        inspect_inputs(manifest_path, data_root=tmp_path)


def test_bounded_json_reader_rejects_symlink(tmp_path):
    target = tmp_path / "target.json"
    target.write_text('{"cases": []}')
    link = tmp_path / "input.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        inspect_inputs(link, data_root=tmp_path)


def test_bounded_json_reader_rejects_fifo_without_blocking(tmp_path):
    if not hasattr(os, "mkfifo") or not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("FIFO/no-follow semantics require POSIX support")
    fifo = tmp_path / "planner-input.fifo"
    os.mkfifo(fifo)
    script = (
        "from pathlib import Path; import sys; "
        "from scripts.core_formal_planner import _read_bounded_raw_json; "
        "_read_bounded_raw_json(Path(sys.argv[1]))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(fifo)],
        cwd=Path(__file__).parents[1], capture_output=True, text=True,
        timeout=3, check=False,
    )
    assert completed.returncode != 0
    assert "not a regular file" in completed.stderr


def test_manifest_reference_hash_is_from_exact_bytes_parsed(tmp_path, monkeypatch):
    manifest_path, _ = _manifest(tmp_path)
    parsed_raw = manifest_path.read_bytes()
    replacement_raw = b'{"schema":"core.dataset.v2","cases":[]}'
    read_raw = formal_planner._read_bounded_raw_json
    replaced = False

    def read_then_replace(path):
        nonlocal replaced
        raw = read_raw(path)
        if Path(path) == manifest_path and not replaced:
            manifest_path.write_bytes(replacement_raw)
            replaced = True
        return raw

    monkeypatch.setattr(formal_planner, "_read_bounded_raw_json", read_then_replace)
    report = inspect_inputs(manifest_path, data_root=tmp_path)
    assert replaced
    assert manifest_path.read_bytes() == replacement_raw
    assert report["case_count"] == 3 * CASES_PER_FAMILY
    assert report["manifest"]["sha256"] == sha256_bytes(parsed_raw)
    assert report["manifest"]["sha256"] != sha256_bytes(replacement_raw)


def test_referenced_audit_json_with_duplicate_keys_is_rejected(tmp_path):
    manifest_path, payload = _manifest(tmp_path)
    audit_raw = (
        b'{"case_id":"F1_PROD_00","hard_integrity_pass":false,'
        b'"hard_integrity_pass":true,"structural_pass":true}'
    )
    audit_path = tmp_path / "duplicate-audit.json"
    audit_path.write_bytes(audit_raw)
    payload["cases"][0]["audit"] = {
        "path": audit_path.name,
        "sha256": sha256_bytes(audit_raw),
    }
    manifest_path.write_text(json.dumps(payload))
    report = inspect_inputs(manifest_path, data_root=tmp_path)
    assert report["formal_eligible"] is False
    assert any("invalid audit JSON" in reason for reason in report["hold_reasons"])


def _source_snapshot() -> dict:
    root = Path(__file__).parents[1]
    return {
        "files": [
            {
                "relative_path": relative,
                "sha256": sha256_file(root / relative),
                "bytes": (root / relative).stat().st_size,
            }
            for relative in REQUIRED_CODE_FILES
        ]
    }


def test_explicit_source_snapshot_is_hash_and_byte_bound(tmp_path):
    manifest_path, _ = _manifest(tmp_path)
    snapshot = _source_snapshot()
    plan = build_plan(
        manifest_path, profile=_profile(), environment=_environment(),
        data_root=tmp_path, code_root=Path(__file__).parents[1],
        source_snapshot=snapshot,
    )
    assert plan["status"] == "hold"
    assert plan["formal_job_count"] == 0
    assert plan["launch_allowed"] is False
    assert plan["source_snapshot"]["verified"] is True

    snapshot["files"][0]["sha256"] = "0" * 64
    broken = build_plan(
        manifest_path, profile=_profile(), environment=_environment(),
        data_root=tmp_path, code_root=Path(__file__).parents[1],
        source_snapshot=snapshot,
    )
    assert broken["status"] == "hold"
    assert broken["formal_job_count"] == 0
    assert any("source snapshot hash mismatch" in reason
               for reason in broken["hold_reasons"])


def test_invalid_resource_numbers_hold_the_formal_plan(tmp_path):
    manifest_path, _ = _manifest(tmp_path)
    profile = _profile()
    profile["resources"]["gpu_peak_mib"] = "nan"
    plan = build_plan(
        manifest_path, profile=profile, environment=_environment(),
        data_root=tmp_path, code_root=Path(__file__).parents[1],
    )
    assert plan["status"] == "hold"
    assert plan["formal_job_count"] == 0
    assert any("invalid positive gpu_peak_mib" in reason
               for reason in plan["hold_reasons"])


def test_source_snapshot_directory_is_compared_to_code_root(tmp_path):
    manifest_path, _ = _manifest(tmp_path)
    root = Path(__file__).parents[1]
    snapshot_dir = tmp_path / "snapshot"
    for relative in REQUIRED_CODE_FILES:
        target = snapshot_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, target)

    plan = build_plan(
        manifest_path, profile=_profile(), environment=_environment(),
        data_root=tmp_path, code_root=root, source_snapshot=snapshot_dir,
    )
    assert plan["status"] == "hold"
    assert plan["formal_job_count"] == 0
    assert plan["launch_allowed"] is False
    assert plan["source_snapshot"]["verified"] is True

    broken_file = snapshot_dir / REQUIRED_CODE_FILES[0]
    broken_file.write_text(broken_file.read_text(encoding="utf-8") + "\n")
    broken = build_plan(
        manifest_path, profile=_profile(), environment=_environment(),
        data_root=tmp_path, code_root=root, source_snapshot=snapshot_dir,
    )
    assert broken["status"] == "hold"
    assert any("source snapshot hash mismatch" in reason
               or "source snapshot byte count mismatch" in reason
               for reason in broken["hold_reasons"])


@pytest.mark.parametrize('replacement, reason', [('train', 'requires 12'), ('unassigned', 'unrecognized production splits')])
def test_missing_test_denominator_is_not_a_formal_plan(tmp_path, replacement, reason):
    path, payload = _manifest(tmp_path)
    for row in payload['cases']:
        if row['family'] == 'F4' and row['split'] == 'test':
            row['split'] = replacement
    path.write_text(json.dumps(payload))
    plan = build_plan(path, profile=_profile(), environment=_environment(),
                      data_root=tmp_path, code_root=Path(__file__).parents[1],
                      output_dir=tmp_path / 'specs')
    assert plan['status'] == 'hold'
    assert plan['formal_job_count'] == 0
    assert any(reason in item for item in plan['hold_reasons'])


def test_structural_success_alone_does_not_prove_hard_integrity(tmp_path):
    path, payload = _manifest(tmp_path)
    payload['cases'][0]['audit'] = {'structural_pass': True, 'passed': True,
                                    'audit_status': 'pass_diagnostic'}
    path.write_text(json.dumps(payload))
    plan = build_plan(path, profile=_profile(), environment=_environment(),
                      data_root=tmp_path, code_root=Path(__file__).parents[1],
                      output_dir=tmp_path / 'specs')
    assert plan['status'] == 'hold'
    assert plan['formal_job_count'] == 0
    assert any('explicit hard audit required' in item for item in plan['hold_reasons'])


@pytest.mark.parametrize("mutation, expected", [
    ("missing_family", "distinct T1 families"),
    ("qualification_only", "qualification_only case"),
    ("duplicate_case", "duplicate case_id"),
    ("duplicate_physical", "duplicate physical_case_id"),
])
def test_invalid_manifest_is_a_hold_and_writes_no_specs(tmp_path, mutation, expected):
    manifest_path, payload = _manifest(tmp_path)
    payload = copy.deepcopy(payload)
    if mutation == "missing_family":
        payload["cases"] = [row for row in payload["cases"] if row["family"] != "F4"]
    elif mutation == "qualification_only":
        payload["cases"][0]["qualification_only"] = True
    elif mutation == "duplicate_case":
        payload["cases"].append(copy.deepcopy(payload["cases"][1]))
    elif mutation == "duplicate_physical":
        payload["cases"][1]["physical_case_id"] = payload["cases"][0]["physical_case_id"]
    manifest_path.write_text(json.dumps(payload))
    spec_dir = tmp_path / "specs"
    plan = build_plan(manifest_path, profile=_profile(), environment=_environment(),
                      data_root=tmp_path, code_root=Path(__file__).parents[1],
                      output_dir=spec_dir)
    assert plan["status"] == "hold"
    assert plan["formal_job_count"] == 0
    assert any(expected in reason for reason in plan["hold_reasons"])
    assert not spec_dir.exists()


def test_lineage_cross_split_isolation_is_required(tmp_path):
    manifest_path, payload = _manifest(tmp_path)
    payload = copy.deepcopy(payload)
    payload["cases"][28]["lineage_group_id"] = payload["cases"][0]["lineage_group_id"]
    manifest_path.write_text(json.dumps(payload))
    report = inspect_inputs(manifest_path, data_root=tmp_path)
    assert report["formal_eligible"] is False
    assert any("lineage crosses splits" in reason for reason in report["hold_reasons"])


def test_explicit_hard_false_cannot_be_masked_by_positive_metadata(tmp_path):
    manifest_path, payload = _manifest(tmp_path)
    payload = copy.deepcopy(payload)
    payload["cases"][0]["audit"]["hard_integrity_pass"] = False
    payload["cases"][0]["audit"]["structural_pass"] = True
    manifest_path.write_text(json.dumps(payload))
    report = inspect_inputs(manifest_path, data_root=tmp_path)
    assert any("hard/structural audit" in reason for reason in report["hold_reasons"])
    assert report["formal_eligible"] is False


def test_explanatory_none_qualification_claim_does_not_remove_production_case():
    """A prose ``none; ...`` marker is an explicit absence of a claim."""
    assert _qualification_marker([{
        "case_id": "F4_PROD_00",
        "qualification_claim": "none; one case cannot establish range qualification",
    }]) is False
    assert _qualification_marker([{
        "case_id": "F4_PROD_00",
        "qualification_claim": "formal range qualification",
    }]) is True


def test_t1_evidence_must_match_case_scope_and_recipe(tmp_path):
    manifest_path, payload = _manifest(tmp_path)
    payload = copy.deepcopy(payload)
    # Remove the inline T1 marker for one case so only the supplied family
    # record can qualify it.  That record deliberately belongs to another
    # registered recipe.
    payload["cases"][0].pop("T1_numerical")
    payload["cases"][0]["audit"].pop("structural_pass")
    manifest_path.write_text(json.dumps(payload))
    evidence = [{"case_id": payload["cases"][0]["case_id"], "family": "F1",
                 "scope_id": "F1_other_scope", "recipe_id": "F1_other_recipe",
                 "T1_numerical": True}]
    report = inspect_inputs(manifest_path, evidence=evidence, data_root=tmp_path)
    assert any("T1 qualification" in reason for reason in report["hold_reasons"])
    assert any("scope/recipe mismatch" in reason for reason in report["hold_reasons"])


def test_audit_reference_requires_matching_declared_hash(tmp_path):
    manifest_path, payload = _manifest(tmp_path)
    payload = copy.deepcopy(payload)
    audit_path = tmp_path / "case-audit.json"
    audit_path.write_text(json.dumps({"case_id": payload["cases"][0]["case_id"],
                                      "hard_integrity_pass": True,
                                      "T1_numerical": True}))
    payload["cases"][0].pop("audit")
    payload["cases"][0]["audit"] = {"path": audit_path.name, "sha256": "0" * 64}
    manifest_path.write_text(json.dumps(payload))
    report = inspect_inputs(manifest_path, data_root=tmp_path)
    assert any("hash/format failure" in reason for reason in report["hold_reasons"])
    assert report["formal_eligible"] is False


def test_missing_physical_or_lineage_identity_is_not_inferred_from_case_id(tmp_path):
    manifest_path, payload = _manifest(tmp_path)
    payload = copy.deepcopy(payload)
    payload["cases"][0].pop("physical_case_id")
    payload["cases"][1].pop("lineage_group_id")
    manifest_path.write_text(json.dumps(payload))
    report = inspect_inputs(manifest_path, data_root=tmp_path)
    assert any("no physical_case_id" in reason for reason in report["hold_reasons"])
    assert any("no lineage_group_id" in reason for reason in report["hold_reasons"])


def test_real_f3_compact_manifest_is_hold_and_never_creates_formal_jobs(tmp_path):
    lab = Path(__file__).parents[1]
    manifest = lab / "campaigns/core-v1/f3-dataset-v2.json"
    evidence = lab / "campaigns/core-v1/evidence/f3-inherited-qualification.json"
    profile = lab / "campaigns/core-v1/learning/backward-resource-measurements.json"
    report_path = tmp_path / "f3-plan.json"
    exit_code = main([
        "plan", "--manifest", str(manifest), "--data-root", str(lab),
        "--evidence", str(evidence), "--profile-resource", str(profile),
        "--python-executable", sys.executable, "--output", str(report_path),
    ])
    assert exit_code == 2
    report = json.loads(report_path.read_text())
    assert report["status"] == "hold"
    assert report["formal_job_count"] == 0
    assert any("distinct T1 families" in reason for reason in report["hold_reasons"])
