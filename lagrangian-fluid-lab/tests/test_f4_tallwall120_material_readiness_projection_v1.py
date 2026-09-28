"""CPU-only tests for the non-authorizing F4 Tallwall120 projection."""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from scripts import f4_tallwall120_material_readiness_projection_v1 as module


LAB_ROOT = module.LAB_ROOT


def _fixture_inputs(tmp_path: Path) -> dict[str, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    result: dict[str, Path] = {}
    for name, relative in module.DEFAULT_INPUT_PATHS.items():
        target = tmp_path / f"{name}.json"
        shutil.copyfile(LAB_ROOT / relative, target)
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
    assert all(value == 0 for value in report["mutations"].values())


def test_missing_bounded_input_fails_closed(tmp_path: Path) -> None:
    inputs = _fixture_inputs(tmp_path)
    inputs["terminal_evidence"].unlink()

    with pytest.raises(module.F4MaterialReadinessProjectionError) as raised:
        module.build_report(inputs)

    assert raised.value.code == "missing_input"


def test_source_drift_mutation_is_rejected(tmp_path: Path) -> None:
    inputs = _fixture_inputs(tmp_path)
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
    tmp_path: Path, input_name: str, mutate, expected_code: str
) -> None:
    inputs = _fixture_inputs(tmp_path)
    _rewrite(inputs[input_name], mutate)

    with pytest.raises(module.F4MaterialReadinessProjectionError) as raised:
        module.build_report(inputs)

    assert raised.value.code == expected_code


def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(tmp_path: Path) -> None:
    inputs = _fixture_inputs(tmp_path)
    inputs["coarse_proposal"].write_bytes(b'{"schema":"x","schema":"y"}\n')
    with pytest.raises(module.F4MaterialReadinessProjectionError) as duplicate:
        module.build_report(inputs)
    assert duplicate.value.code == "duplicate_json_key"

    inputs = _fixture_inputs(tmp_path / "nonfinite")
    inputs["coarse_proposal"].write_bytes(b'{"value":NaN}\n')
    with pytest.raises(module.F4MaterialReadinessProjectionError) as nonfinite:
        module.build_report(inputs)
    assert nonfinite.value.code == "non_strict_json"


def test_symlink_input_is_rejected(tmp_path: Path) -> None:
    inputs = _fixture_inputs(tmp_path)
    target = inputs["coarse_proposal"]
    replacement = tmp_path / "coarse-real.json"
    target.unlink()
    replacement.write_bytes((LAB_ROOT / module.DEFAULT_INPUT_PATHS["coarse_proposal"]).read_bytes())
    target.symlink_to(replacement)

    with pytest.raises(module.F4MaterialReadinessProjectionError) as raised:
        module.build_report(inputs)

    assert raised.value.code == "symlink_path"


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


def test_report_binding_detects_semantic_input_rewrite(tmp_path: Path) -> None:
    inputs = _fixture_inputs(tmp_path / "inputs")
    report = module.build_report(inputs)
    report_path = tmp_path / "projection.json"
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
