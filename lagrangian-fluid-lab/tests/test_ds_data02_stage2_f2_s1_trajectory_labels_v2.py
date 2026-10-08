from __future__ import annotations

import importlib.util
from pathlib import Path

import h5py
import numpy as np
import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_s1_trajectory_labels_v2.py"
spec = importlib.util.spec_from_file_location("f2_trajectory_labels_v2", SCRIPT)
assert spec and spec.loader
MODULE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODULE)


def test_complete_attribute_accepts_numpy_bool_but_rejects_string_and_integer() -> None:
    assert MODULE._strict_true(np.bool_(True), np) is True
    assert MODULE._strict_true(True, np) is True
    assert MODULE._strict_true("True", np) is False
    assert MODULE._strict_true("False", np) is False
    assert MODULE._strict_true(1, np) is False
    assert MODULE._strict_true(0, np) is False


def test_existing_label_attrs_are_strict_and_source_bound(tmp_path: Path) -> None:
    output = tmp_path / "labels.h5"
    source = tmp_path / "trajectory.h5"
    source.write_bytes(b"deferred source fixture")
    with h5py.File(output, "w") as handle:
        handle.attrs["schema"] = "ds-data-02.native-labels.v1"
        handle.attrs["complete"] = np.bool_(True)
        handle.attrs["source_hdf5_sha256"] = MODULE.EXPECTED_H5_SHA256
        handle.attrs["source_hdf5"] = str(source.resolve())
    with h5py.File(output, "r") as handle:
        MODULE._validate_existing_label_attrs(handle, {"trajectory_hdf5": {"path": str(source.resolve())}}, np)
    with h5py.File(output, "r+") as handle:
        handle.attrs["complete"] = "False"
    with h5py.File(output, "r") as handle:
        with pytest.raises(MODULE.TrajectoryLabelError, match="strict true boolean"):
            MODULE._validate_existing_label_attrs(handle, {"trajectory_hdf5": {"path": str(source.resolve())}}, np)


@pytest.mark.skipif(
    not Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/STAGE2_F2_S1_TRAJECTORY_LABELS_V1/f2-s1-trajectory-labels-v1-primary-001-root-forward-001/execution-receipt.json").is_file(),
    reason="shared completed v1 failure receipt is not mounted",
)
def test_actual_failed_receipt_is_recoverable_without_source_h5_hash() -> None:
    base = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/STAGE2_F2_S1_TRAJECTORY_LABELS_V1/f2-s1-trajectory-labels-v1-primary-001-root-forward-001")
    contract = ROOT / "campaigns/ds-data-02/stage2/requests/f2-s1-trajectory-labels-v1/f2-s1-trajectory-source-contract-v1.json"
    receipt = base / "execution-receipt.json"
    recovered = base / "f2-s1-trajectory-labels-v1.h5"
    original = MODULE.sha256

    def no_source_hash(path: Path | str) -> str:
        # The helper must skip the original source trajectory; it may hash the
        # small receipt inputs.  The exact source path is read from the
        # contract, so reject it dynamically.
        if Path(path).resolve() == Path(MODULE.read_json(contract, "contract")["trajectory_hdf5"]["path"]).resolve():
            raise AssertionError("recovery attempted to hash original trajectory H5")
        return original(path)

    MODULE.sha256 = no_source_hash
    try:
        info = MODULE._stable_failed_receipt(receipt, contract, recovered, verify_small_inputs=True)
    finally:
        MODULE.sha256 = original
    assert info["returncode"] == 1
    assert info["old_attempt_preserved"] is True
    assert info["failure_credit"] == "none; v1 worker summary schema failure only"
