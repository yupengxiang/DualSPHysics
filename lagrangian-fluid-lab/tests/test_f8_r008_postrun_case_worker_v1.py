from __future__ import annotations

import hashlib
import json
import os

import pytest

from scripts import core_contract
from scripts import core_dataset
from scripts import f8_r008_core_trajectory_adapter_v1 as trajectory_adapter
from scripts import f8_r008_native_fluid_table_metric_bundle_verifier_v2 as metric_bundle
from scripts import f8_r008_t1_metric_adapter_v2 as metric_adapter
from scripts import f8_r008_postrun_case_worker_v1 as postrun

from tests import test_f8_r008_native_fluid_table_bundle_verifier_v1 as table_fixtures
from tests import test_f8_r008_native_fluid_table_metric_bundle_verifier_v2 as metric_fixtures
from tests import test_f8_r008_per_case_bundle_verifier_v1 as bundle_fixtures


def _synthetic_inputs(tmp_path):
    tmp_path.mkdir(parents=True)
    roots, auth_bytes, auth, _frames = bundle_fixtures._build_chain(tmp_path)
    table_fixtures._freeze_b_source_bindings(roots)
    table_fixtures._materialize_synthetic_v2_table(roots)
    inputs = table_fixtures._verification_inputs(roots, auth_bytes, auth)
    metric_review = metric_fixtures._metric_review_bytes()
    inputs.update({
        "trusted_metric_review_receipt_bytes": metric_review,
        "trusted_metric_review_receipt_sha256": hashlib.sha256(metric_review).hexdigest(),
    })
    return inputs


def _output_dir_fd(path):
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)


def _valid_metric_stub(monkeypatch):
    def evaluate(_fd, *, table_verification, **_kwargs):
        return metric_fixtures._valid_metric_result(
            bundle_fixtures.CASE_ID, table_verification,
        )

    monkeypatch.setattr(metric_adapter, "evaluate_case_metrics_fd", evaluate)


def _reader_manifest(path, binding):
    coordinate_frame = "synthetic-postrun-fixture"
    known_inputs = {
        "contract_version": core_contract.INPUT_VERSION,
        "coordinate_frame": coordinate_frame,
        "geometry": {
            "version": "core.finite_geometry.v1",
            "coordinate_frame": coordinate_frame,
            "triangles": [[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]],
            "component_id": [0],
            "body_id": [0],
            "wall_velocity": [[0.0, 0.0, 0.0]],
        },
        "control": {
            "samples": [[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                        [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]],
            "centre": [0.0, 0.0, 0.0],
            "semantics": "dualsphysics_f3_accinput_v1",
        },
        "physics": {"family": "synthetic"},
        "numerics": {"dp_m": 0.1, "h_m": 0.2},
    }
    known = core_dataset.known_inputs_from_dict(known_inputs)
    return {
        "schema": core_dataset.SCHEMA,
        "formal_release": False,
        "diagnostic_only": True,
        "cases": [{
            "case_id": bundle_fixtures.CASE_ID,
            "physical_case_id": "synthetic-postrun-physical-case",
            "lineage_group_id": "synthetic-postrun-lineage",
            "family": "F8",
            "split": "qualification",
            "qualification_case": True,
            "hdf5": path.name,
            "sha256": binding["sha256"],
            "known_inputs": known_inputs,
            "known_inputs_sha256": core_contract.contract_hash(known),
        }],
    }


def _run(inputs, output_fd, *, case_id=bundle_fixtures.CASE_ID):
    return postrun.materialize_postrun_case_worker_v1(
        **inputs,
        case_id=case_id,
        output_directory_fd=output_fd,
    )


def _minimal_inputs():
    return {
        "bundle_roots": {},
        "trusted_authorization_bytes": {},
        "trusted_authorization_sha256": {},
        "expected_authorization_envelopes": {},
        "trusted_table_review_receipt_bytes": b"",
        "trusted_table_review_receipt_sha256": "",
        "trusted_metric_review_receipt_bytes": b"",
        "trusted_metric_review_receipt_sha256": "",
        "trusted_code_review_receipt_bytes": b"",
        "trusted_runtime_assumption": {},
    }


def test_postrun_bridge_materializes_core_readable_qualification_trajectory(
    tmp_path, monkeypatch,
):
    inputs = _synthetic_inputs(tmp_path / "bundles")
    output_dir = tmp_path / "core-output"
    output_dir.mkdir(mode=0o700)
    _valid_metric_stub(monkeypatch)
    output_fd = _output_dir_fd(output_dir)

    result = _run(inputs, output_fd)

    trajectory = output_dir / trajectory_adapter.OUTPUT_FILENAME
    assert trajectory.is_file()
    assert result["status"] == "diagnostic_postrun_trajectory_and_v2_metrics_revalidated"
    assert result["trajectory_binding"]["sha256"] == hashlib.sha256(trajectory.read_bytes()).hexdigest()
    assert result["case_metrics"]["case_id"] == bundle_fixtures.CASE_ID
    assert result["metric_gates_passed"] is True
    assert result["split"] == "qualification"
    assert result["formal_eligible"] is False
    assert result["external_authorization_authenticated"] is False
    assert result["supervisor_identity_authenticated"] is False
    assert result["loaded_module_code_identity_verified"] is False
    assert result["native_integrity_evaluated"] is False
    assert result["native_integrity_pass"] is False
    assert result["T1_numerical"] is False
    assert result["readiness_pass"] is False
    assert result["qualification_credit"] == 0
    with pytest.raises(OSError):
        os.fstat(output_fd)

    manifest = _reader_manifest(trajectory, result["trajectory_binding"])
    with core_dataset.CoreDataset(manifest, data_root=output_dir, strict=True) as reader:
        assert reader.case_ids(split="qualification") == (bundle_fixtures.CASE_ID,)
        assert reader.formal_eligible is False
        assert reader.record(bundle_fixtures.CASE_ID)["qualification_case"] is True
        state = reader.read_state(bundle_fixtures.CASE_ID, 0)
        assert state.count == 1
        assert state.particle_id.tolist() == [0]
        assert state.particle_zone.tolist() == [0]
        assert state.valid.tolist() == [True]


def test_qualification_trajectory_cannot_be_relabelled_as_training_data(
    tmp_path, monkeypatch,
):
    inputs = _synthetic_inputs(tmp_path / "bundles")
    output_dir = tmp_path / "core-output"
    output_dir.mkdir(mode=0o700)
    _valid_metric_stub(monkeypatch)
    result = _run(inputs, _output_dir_fd(output_dir))
    trajectory = output_dir / trajectory_adapter.OUTPUT_FILENAME

    manifest = _reader_manifest(trajectory, result["trajectory_binding"])
    with core_dataset.CoreDataset(manifest, data_root=output_dir, strict=True) as reader:
        # Warm the cached HDF5 handle before changing the caller-owned manifest
        # row; subsequent training reads must still recheck the embedded split.
        reader.read_state(bundle_fixtures.CASE_ID, 0)
        row = manifest["cases"][0]
        row["split"] = "train"
        row["qualification_case"] = False
        assert reader.formal_eligible is False
        with pytest.raises(ValueError, match="HDF5 split attribute differs"):
            reader.training_transition(bundle_fixtures.CASE_ID, 0)


def test_postrun_bridge_refuses_to_overwrite_existing_output(tmp_path):
    output_dir = tmp_path / "core-output"
    output_dir.mkdir(mode=0o700)
    target = output_dir / trajectory_adapter.OUTPUT_FILENAME
    original = b"pre-existing user artifact\n"
    target.write_bytes(original)
    output_fd = _output_dir_fd(output_dir)
    with pytest.raises(FileExistsError):
        _run(_minimal_inputs(), output_fd)

    assert target.read_bytes() == original
    with pytest.raises(OSError):
        os.fstat(output_fd)


def test_postrun_bridge_preserves_replacement_on_d_chain_drift(
    tmp_path, monkeypatch,
):
    inputs = _synthetic_inputs(tmp_path / "bundles")
    output_dir = tmp_path / "core-output"
    output_dir.mkdir(mode=0o700)
    sentinel = output_dir / "unrelated-user-file.bin"
    sentinel.write_bytes(b"leave untouched\n")
    _valid_metric_stub(monkeypatch)
    output_fd = _output_dir_fd(output_dir)
    original_verifier = metric_bundle.verify_native_fluid_table_chain_and_metrics
    calls = 0

    def drift_on_postvalidation(roots, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            target = output_dir / trajectory_adapter.OUTPUT_FILENAME
            replacement = output_dir / "replacement-user-artifact.bin"
            replacement.write_bytes(b"concurrent replacement must survive\n")
            os.replace(replacement, target)
            d_receipt_path = roots["D"] / "receipt.json"
            receipt = json.loads(d_receipt_path.read_bytes())
            receipt["status"] = "failed"
            d_receipt_path.write_text(
                json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            assert (output_dir / trajectory_adapter.OUTPUT_FILENAME).is_file()
        return original_verifier(roots, **kwargs)

    monkeypatch.setattr(metric_bundle, "verify_native_fluid_table_chain_and_metrics",
                        drift_on_postvalidation)
    with pytest.raises(ValueError):
        _run(inputs, output_fd)

    assert calls == 2
    assert (output_dir / trajectory_adapter.OUTPUT_FILENAME).read_bytes() == (
        b"concurrent replacement must survive\n"
    )
    assert sentinel.read_bytes() == b"leave untouched\n"
    with pytest.raises(OSError):
        os.fstat(output_fd)


def test_postrun_bridge_rejects_case_outside_frozen_denominator(tmp_path):
    output_dir = tmp_path / "core-output"
    output_dir.mkdir(mode=0o700)
    output_fd = _output_dir_fd(output_dir)
    with pytest.raises(postrun.PostrunCaseWorkerError, match="frozen R008 qualification denominator"):
        _run(_minimal_inputs(), output_fd, case_id="not-a-frozen-case")
    with pytest.raises(OSError):
        os.fstat(output_fd)


def test_postrun_bridge_fails_closed_on_group_writable_output_directory(tmp_path):
    output_dir = tmp_path / "core-output"
    output_dir.mkdir(mode=0o700)
    output_dir.chmod(0o770)
    output_fd = _output_dir_fd(output_dir)
    try:
        with pytest.raises(postrun.PostrunCaseWorkerError,
                           match="not group/world-writable"):
            _run(_minimal_inputs(), output_fd)
        with pytest.raises(OSError):
            os.fstat(output_fd)
    finally:
        output_dir.chmod(0o700)
