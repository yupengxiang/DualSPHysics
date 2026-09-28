"""CPU-only tests for the non-authorizing F4 Tallwall120 projection."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

import pytest

from scripts import f4_tallwall120_material_readiness_projection_v1 as module


LAB_ROOT = module.LAB_ROOT


def _fixture_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    source_root = LAB_ROOT
    sandbox_root = tmp_path / "lab"
    sandbox_reports = sandbox_root / "reports"
    sandbox_reports.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, "LAB_ROOT", sandbox_root)
    result: dict[str, Path] = {}
    for name, relative in module.DEFAULT_INPUT_PATHS.items():
        target = sandbox_root / relative
        shutil.copyfile(source_root / relative, target)
        result[name] = target
    return result


def _rewrite(path: Path, mutate) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_build_report_is_bound_and_always_non_authorizing() -> None:
    report = module.build_report()

    assert report["schema"] == module.REPORT_SCHEMA
    assert report["status"] == "blocked_fail_closed"
    assert report["diagnostic_only"] is True
    assert report["launch_admitted"] is False
    assert report["formal"] is False
    assert report["T1"] is False
    assert report["T2"] is False
    assert report["qualification"] is False
    assert report["credit"] == 0
    assert report["qualification_credit"] == 0
    assert report["scope"]["case_id"] == module.CASE_ID
    assert report["source"]["target_path"] == module.TARGET_SOURCE_PATH
    assert report["source"]["target_sha256"] == module.SOURCE_SHA256
    assert report["parameters"]["q"] == module.Q
    assert report["parameters"]["dp_m"] == module.DP_M
    assert report["event_window"]["native_frames"] == 218
    assert report["event_window"]["native_transitions"] == 217
    assert report["event_window"]["required_window_s"] == 8.68
    assert report["sidecar_matrix"]["sidecar_count_supplied"] == 0
    assert report["sidecar_matrix"]["expected_case_count"] == 32
    assert report["terminal_evidence"]["present"] is False
    assert report["input_boundary"]["hdf5_opened"] is False
    assert report["input_boundary"]["hdf5_content_read"] is False
    assert report["input_boundary"]["lab_root_scope_restricted"] is True
    assert report["input_boundary"]["reports_output_scope_restricted"] is True
    assert report["input_boundary"]["held_directory_fd_no_follow"] is True
    assert report["input_boundary"]["max_json_depth"] == module.MAX_JSON_DEPTH
    assert all(value == 0 for value in report["mutations"].values())


def test_missing_bounded_input_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = _fixture_inputs(tmp_path, monkeypatch)
    inputs["terminal_evidence"].unlink()

    with pytest.raises(module.F4MaterialReadinessProjectionError) as raised:
        module.build_report(inputs)

    assert raised.value.code == "missing_input"


def test_source_drift_mutation_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = _fixture_inputs(tmp_path, monkeypatch)
    _rewrite(inputs["source_drift"], lambda value: value["checks"].update(collection_row_path_exact=True))

    with pytest.raises(module.F4MaterialReadinessProjectionError) as raised:
        module.build_report(inputs)

    assert raised.value.code == "source_drift"


@pytest.mark.parametrize(
    ("input_name", "mutate", "expected_code"),
    [
        ("root_scheduler", lambda value: value.update(formal=True), "authorization_drift"),
        ("t2_readiness", lambda value: value["decision"].update(qualification_credit=1), "authorization_drift"),
        ("sidecar_matrix", lambda value: value["qualification"].update(credit=1), "authorization_drift"),
    ],
)
def test_forged_formal_or_credit_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, input_name: str, mutate, expected_code: str
) -> None:
    inputs = _fixture_inputs(tmp_path, monkeypatch)
    _rewrite(inputs[input_name], mutate)

    with pytest.raises(module.F4MaterialReadinessProjectionError) as raised:
        module.build_report(inputs)

    assert raised.value.code == expected_code


def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = _fixture_inputs(tmp_path, monkeypatch)
    inputs["coarse_proposal"].write_bytes(b'{"schema":"x","schema":"y"}\n')
    with pytest.raises(module.F4MaterialReadinessProjectionError) as duplicate:
        module.build_report(inputs)
    assert duplicate.value.code == "duplicate_json_key"

    inputs = _fixture_inputs(tmp_path / "nonfinite", monkeypatch)
    inputs["coarse_proposal"].write_bytes(b'{"value":NaN}\n')
    with pytest.raises(module.F4MaterialReadinessProjectionError) as nonfinite:
        module.build_report(inputs)
    assert nonfinite.value.code == "non_strict_json"


def test_symlink_input_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = _fixture_inputs(tmp_path, monkeypatch)
    target = inputs["coarse_proposal"]
    replacement = tmp_path / "coarse-real.json"
    target.unlink()
    replacement.write_bytes((LAB_ROOT / module.DEFAULT_INPUT_PATHS["coarse_proposal"]).read_bytes())
    target.symlink_to(replacement)

    with pytest.raises(module.F4MaterialReadinessProjectionError) as raised:
        module.build_report(inputs)

    assert raised.value.code == "not_regular_file"


@pytest.mark.parametrize(
    ("bad_path", "expected_code"),
    [
        ("external", "path_scope"),
        ("traversal", "path_traversal"),
    ],
)
def test_input_path_scope_rejects_external_and_traversal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_path: str,
    expected_code: str,
) -> None:
    inputs = _fixture_inputs(tmp_path, monkeypatch)
    if bad_path == "external":
        outside = tmp_path / "outside.json"
        outside.write_bytes(inputs["coarse_proposal"].read_bytes())
        inputs["coarse_proposal"] = outside
    else:
        inputs["coarse_proposal"] = Path(
            "reports/../reports/F4-TALLWALL120-MATERIAL-COARSE-PROPOSAL-2026-09-28.json"
        )

    with pytest.raises(module.F4MaterialReadinessProjectionError) as raised:
        module.build_report(inputs)

    assert raised.value.code == expected_code


def test_parent_symlink_is_rejected_without_following_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _fixture_inputs(tmp_path, monkeypatch)
    alias = module.LAB_ROOT / "reports" / "reports-alias"
    alias.symlink_to(module.LAB_ROOT / "reports", target_is_directory=True)
    inputs["coarse_proposal"] = alias / inputs["coarse_proposal"].name

    with pytest.raises(module.F4MaterialReadinessProjectionError) as raised:
        module.build_report(inputs)

    assert raised.value.code == "safe_open"


def test_hardlink_input_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = _fixture_inputs(tmp_path, monkeypatch)
    alias = module.LAB_ROOT / "reports" / "coarse-hardlink.json"
    os.link(inputs["coarse_proposal"], alias)
    inputs["coarse_proposal"] = alias

    with pytest.raises(module.F4MaterialReadinessProjectionError) as raised:
        module.build_report(inputs)

    assert raised.value.code == "hardlink"


def test_input_replacement_between_stat_and_open_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _fixture_inputs(tmp_path, monkeypatch)
    target = inputs["coarse_proposal"]
    replacement = target.with_name("coarse-replacement.json")
    replacement.write_bytes(target.read_bytes())
    real_open = module.os.open
    switched = False

    def racing_open(path, flags, *args, **kwargs):
        nonlocal switched
        if kwargs.get("dir_fd") is not None and path == target.name and not switched:
            os.replace(replacement, target)
            switched = True
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", racing_open)
    with pytest.raises(module.F4MaterialReadinessProjectionError) as raised:
        module.build_report(inputs)

    assert raised.value.code == "input_drift"


def test_json_depth_and_malformed_check_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _fixture_inputs(tmp_path, monkeypatch)
    nested: dict[str, object] = {}
    cursor = nested
    for _ in range(module.MAX_JSON_DEPTH + 2):
        child: dict[str, object] = {}
        cursor["child"] = child
        cursor = child
    _rewrite(inputs["coarse_proposal"], lambda value: value.update(nested=nested))

    with pytest.raises(module.F4MaterialReadinessProjectionError) as depth:
        module.build_report(inputs)
    assert depth.value.code == "json_depth"

    inputs = _fixture_inputs(tmp_path / "malformed", monkeypatch)
    _rewrite(
        inputs["receipt_consistency"],
        lambda value: value.update(
            checks=[
                item
                for item in value["checks"]
                if item.get("check") != "planner_parameter_contract_matches_committed_receipt"
            ]
        ),
    )
    with pytest.raises(module.F4MaterialReadinessProjectionError) as malformed:
        module.build_report(inputs)
    assert malformed.value.code == "schema_drift"


def test_strict_types_and_record_identity_are_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _fixture_inputs(tmp_path, monkeypatch)
    _rewrite(inputs["root_scheduler"], lambda value: value.update(formal=0))
    with pytest.raises(module.F4MaterialReadinessProjectionError) as strict_type:
        module.build_report(inputs)
    assert strict_type.value.code == "schema_drift"

    inputs = _fixture_inputs(tmp_path / "record", monkeypatch)
    _rewrite(inputs["root_scheduler"], lambda value: value.update(record_id="wrong-record"))
    with pytest.raises(module.F4MaterialReadinessProjectionError) as record:
        module.build_report(inputs)
    assert record.value.code == "binding_drift"


def test_report_validator_rejects_numeric_boolean_boundary() -> None:
    report = module.build_report()
    report["formal"] = 0
    with pytest.raises(module.F4MaterialReadinessProjectionError) as raised:
        module.validate_report(report)
    assert raised.value.code == "authorization_drift"


def test_output_scope_symlink_hardlink_and_replacement_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(module.F4MaterialReadinessProjectionError) as external:
        module._write_new_regular_file(tmp_path / "external.json", b"{}", suffix=".json")
    assert external.value.code == "path_scope"
    with pytest.raises(module.F4MaterialReadinessProjectionError) as external_markdown:
        module._write_new_regular_file(tmp_path / "external.md", b"", suffix=".md")
    assert external_markdown.value.code == "path_scope"
    with pytest.raises(module.F4MaterialReadinessProjectionError) as external_report:
        module.verify_report(tmp_path / "external-report.json")
    assert external_report.value.code == "path_scope"

    inputs = _fixture_inputs(tmp_path / "output", monkeypatch)
    reports = module.LAB_ROOT / "reports"

    symlink_target = reports / "output-symlink.json"
    symlink_target.symlink_to(inputs["coarse_proposal"])
    with pytest.raises(module.F4MaterialReadinessProjectionError) as symlink:
        module._write_new_regular_file(symlink_target, b"{}", suffix=".json")
    assert symlink.value.code == "output_exists"

    hardlink_target = reports / "output-hardlink.json"
    os.link(inputs["coarse_proposal"], hardlink_target)
    with pytest.raises(module.F4MaterialReadinessProjectionError) as hardlink:
        module._write_new_regular_file(hardlink_target, b"{}", suffix=".json")
    assert hardlink.value.code == "output_exists"

    parent_alias = reports / "output-parent-alias"
    parent_alias.symlink_to(reports, target_is_directory=True)
    with pytest.raises(module.F4MaterialReadinessProjectionError) as parent:
        module._write_new_regular_file(parent_alias / "output.json", b"{}", suffix=".json")
    assert parent.value.code == "safe_open"

    replacement_target = reports / "output-replacement.json"
    replacement = reports / "output-replacement-source.json"
    replacement.write_bytes(b"replacement")
    real_write = module.os.write
    switched = False

    def racing_write(fd, data):
        nonlocal switched
        written = real_write(fd, data)
        if not switched:
            os.replace(replacement, replacement_target)
            switched = True
        return written

    monkeypatch.setattr(module.os, "write", racing_write)
    with pytest.raises(module.F4MaterialReadinessProjectionError) as output_race:
        module._write_new_regular_file(replacement_target, b"{}", suffix=".json")
    assert output_race.value.code == "output_drift"


def test_output_hardlink_created_during_write_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixture_inputs(tmp_path, monkeypatch)
    reports = module.LAB_ROOT / "reports"
    target = reports / "output-hardlink-race.json"
    alias = reports / "output-hardlink-race-alias.json"
    real_write = module.os.write
    linked = False

    def linking_write(fd, data):
        nonlocal linked
        written = real_write(fd, data)
        if not linked:
            os.link(target, alias)
            linked = True
        return written

    monkeypatch.setattr(module.os, "write", linking_write)
    with pytest.raises(module.F4MaterialReadinessProjectionError) as raised:
        module._write_new_regular_file(target, b"{}", suffix=".json")
    assert raised.value.code == "output_hardlink"


def test_hdf5_metadata_paths_are_never_opened(monkeypatch: pytest.MonkeyPatch) -> None:
    real_open = module.os.open

    def guarded_open(path, *args, **kwargs):
        if str(path).endswith(".h5"):
            raise AssertionError(f"HDF5 was opened: {path}")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", guarded_open)
    report = module.build_report()
    assert report["input_boundary"]["hdf5_opened"] is False
    assert report["input_boundary"]["hdf5_hash_recomputed"] is False


def test_report_binding_detects_semantic_input_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _fixture_inputs(tmp_path / "inputs", monkeypatch)
    report = module.build_report(inputs)
    report_path = module.LAB_ROOT / "reports" / "projection.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    assert module.verify_report(report_path, input_paths=inputs) == report

    # Keep the JSON meaning unchanged but change its raw bytes.  The fresh
    # projection must then disagree on the input SHA reference.
    value = json.loads(inputs["coarse_proposal"].read_text(encoding="utf-8"))
    inputs["coarse_proposal"].write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(module.F4MaterialReadinessProjectionError) as raised:
        module.verify_report(report_path, input_paths=inputs)
    assert raised.value.code == "report_binding_drift"


def test_report_validator_rejects_forged_output_boundary() -> None:
    report = module.build_report()
    report["formal"] = True
    with pytest.raises(module.F4MaterialReadinessProjectionError) as raised:
        module.validate_report(report)
    assert raised.value.code == "authorization_drift"


def test_markdown_is_rendered_from_the_validated_report() -> None:
    report = module.build_report()
    markdown = module.render_markdown(report)
    assert "F4 Tallwall120 material readiness projection v1" in markdown
    assert "0/32" in markdown
    assert "launch_admitted=false" in markdown
