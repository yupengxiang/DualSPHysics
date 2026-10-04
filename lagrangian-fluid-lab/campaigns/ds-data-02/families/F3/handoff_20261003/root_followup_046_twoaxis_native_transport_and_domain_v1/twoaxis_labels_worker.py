#!/usr/bin/env python3
"""Reusable binding-driven native label worker for F3 two-axis sloshing (Second Mechanism).

Preserves:
1. Frozen CELL3 canonical helper and event configuration (f3_legacy_plain_full_transport_config.v1.json).
2. All 23 event closure categories evaluated independently.
3. All 13 mandatory payload datasets in separate native-labels.h5; source trajectory.h5 immutable.
4. Full [0.0, 8.35] s window support.
5. Actual canonical physical binding condition hash:
   49e319c0a874733707a028e916362e74e2301d6681e34bc6b717581dbd7edaeb
   Preserving Root 072 erratum marker 49d16330fd5267668670f166a20191bfb00c5223ad5528439630c7e62dd4c6a0.
   Nominal single-axis controls hash MUST NOT transfer.
6. Pure descriptive evidence boundary: q_n='not_assessed', production_approval='none'.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
from typing import Any, Dict

import h5py
import numpy as np

# Canonical constants
CANONICAL_PHYSICAL_CONDITION_SHA256 = "49e319c0a874733707a028e916362e74e2301d6681e34bc6b717581dbd7edaeb"
DECLARED_TOP_LEVEL_ERRATUM_MARKER = "49d16330fd5267668670f166a20191bfb00c5223ad5528439630c7e62dd4c6a0"
FORBIDDEN_SINGLE_AXIS_HASHES = {
    "59abc8c59ecbb994aef358a683672feac00ff8d1024d55f0219c8fe257f6ff90",
    "86562c5afee8228131d58c1b53f360eb6c6a700381c01bf807a0f268bbc675c0",
}
FULL_WINDOW_TMAX_S = 8.35

MANDATORY_PAYLOAD_DATASETS = [
    "time",
    "particle_id",
    "particle_zone",
    "source_label",
    "destination_time_series",
    "final_category",
    "failure_reason",
    "first_passage_interval",
    "first_passage_chord_time",
    "first_passage_censor",
    "residence_time_s",
    "unresolved_interval_time_s",
    "initial_fluid_mass_kg",
]

MANDATORY_SUMMARY_DATASETS = [
    "forward_backward_mass_kg",
    "cumulative_net_flux_kg",
    "unknown_mass_kg",
    "numerical_loss_mass_kg",
    "invalid_state_mass_kg",
    "source_final_mass_kg",
]


def digest(path: Path | str) -> str:
    """Compute sha256 checksum of a file."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while chunk := f.read(1048576):
            h.update(chunk)
    return h.hexdigest()


def verified_copy(source: Path, destination: Path, expected_sha: str) -> None:
    """Copy source to destination with streaming SHA256 verification."""
    h = hashlib.sha256()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as fsrc, destination.open("wb") as fdst:
        while chunk := fsrc.read(1048576):
            h.update(chunk)
            fdst.write(chunk)
    actual_sha = h.hexdigest()
    if actual_sha != expected_sha:
        destination.unlink(missing_ok=True)
        raise ValueError(
            f"Source SHA mismatch during staging: expected {expected_sha}, got {actual_sha}"
        )


def evaluate_23_closure_categories(
    labels_h5_path: Path, expected_ids: np.ndarray, expected_mass: float
) -> Dict[str, Any]:
    """Check identity, fate, censoring, residence, and mass ledgers across exactly 23 categories."""
    checks: Dict[str, bool] = {}
    with h5py.File(labels_h5_path, "r") as h:
        time = h["time"][:]
        ids = np.column_stack((h["particle_zone"][:], h["particle_id"][:]))
        mass = h["initial_fluid_mass_kg"][:]
        fluid = mass > 0
        nt, n = h["destination_time_series"].shape
        config = json.loads(h.attrs["config_json"])
        nr, ne = len(config["destination_regions"]), len(config.get("events", []))

        # Check 1: complete attribute
        checks["complete"] = bool(h.attrs.get("complete", False))
        # Check 2: unique identity
        checks["unique_identity"] = len(np.unique(ids, axis=0)) == n
        # Check 3: exact source identity
        checks["exact_source_identity"] = np.array_equal(ids, expected_ids)
        # Check 4: finite positive initial cohort
        checks["finite_positive_initial_cohort"] = bool(
            np.isfinite(mass).all() and fluid.any()
        )
        # Check 5: native initial mass matches expected
        checks["native_initial_mass"] = bool(
            np.isclose(mass.sum(), expected_mass, rtol=1e-10, atol=1e-9)
        )
        # Check 6: finite increasing time support covering full window
        checks["finite_increasing_time"] = bool(
            len(time) == nt
            and np.isfinite(time).all()
            and (np.diff(time) > 0).all()
            and time[0] == 0.0
            and time[-1] >= FULL_WINDOW_TMAX_S
        )
        # Check 7: source labels cover initial fluid
        checks["source_labels_cover_initial_fluid"] = bool(
            (h["source_label"][:][fluid] > 0).all()
        )
        # Check 8: final category matches last destination frame
        checks["final_matches_last_destination"] = np.array_equal(
            h["final_category"][:], h["destination_time_series"][-1]
        )
        # Check 9: source final mass closed
        checks["source_final_mass_closed"] = bool(
            np.isclose(h["source_final_mass_kg"][:].sum(), mass.sum(), rtol=1e-10, atol=1e-9)
        )

        brackets = h["first_passage_interval"][:]
        estimates = h["first_passage_chord_time"][:]
        censor = h["first_passage_censor"][:]
        observed = censor == 0

        # Check 10: censor codes binary {0, 1}
        checks["censor_codes"] = bool(np.isin(censor, [0, 1]).all())
        # Check 11: finite observed brackets
        checks["finite_observed_brackets"] = bool(
            np.isfinite(brackets[observed]).all() and np.isfinite(estimates[observed]).all()
        )
        # Check 12: positive observed brackets (upper > lower)
        checks["positive_observed_brackets"] = bool(
            (brackets[..., 1][observed] > brackets[..., 0][observed]).all()
        )
        # Check 13: estimates strictly within bracket bounds
        checks["estimates_within_brackets"] = bool(
            (
                (estimates[observed] >= brackets[..., 0][observed] - 1e-12)
                & (estimates[observed] <= brackets[..., 1][observed] + 1e-12)
            ).all()
        )
        # Check 14: unobserved brackets and estimates NaN
        checks["unobserved_brackets_nan"] = bool(
            np.isnan(brackets[~observed]).all() and np.isnan(estimates[~observed]).all()
        )

        residence = h["residence_time_s"][:]
        unresolved = h["unresolved_interval_time_s"][:]

        # Check 15: finite non-negative residence times
        checks["finite_nonnegative_residence"] = bool(
            np.isfinite(residence).all() and (residence >= -1e-12).all()
        )
        # Check 16: finite non-negative unresolved times
        checks["finite_nonnegative_unresolved"] = bool(
            np.isfinite(unresolved).all() and (unresolved >= -1e-12).all()
        )
        # Check 17: disjoint residence within window bounds
        checks["disjoint_residence_within_window"] = bool(
            (residence.sum(axis=1) + unresolved <= (time[-1] - time[0] + 1e-9)).all()
        )

        fb = h["forward_backward_mass_kg"][:]
        # Check 18: finite monotone directional flux
        checks["finite_monotone_directional_flux"] = bool(
            np.isfinite(fb).all()
            and (fb >= -1e-12).all()
            and (np.diff(fb, axis=0) >= -1e-9).all()
        )
        # Check 19: net flux difference matches forward - backward
        checks["net_flux_difference"] = bool(
            np.allclose(h["cumulative_net_flux_kg"][:], fb[..., 0] - fb[..., 1], rtol=1e-9, atol=1e-8)
        )
        # Check 20: label tensor shapes
        checks["label_shapes"] = brackets.shape == (n, ne, 2) and residence.shape == (n, nr)

        max_residual = 0.0
        checks["destination_codes"] = True
        checks["fluid_cohort_identity"] = True
        for ti in range(nt):
            dest = h["destination_time_series"][ti]
            if not np.isin(dest, np.arange(-3, nr + 1)).all():
                checks["destination_codes"] = False
            for code, name in [
                (0, "unknown_mass_kg"),
                (-1, "numerical_loss_mass_kg"),
                (-2, "invalid_state_mass_kg"),
            ]:
                max_residual = max(
                    max_residual, abs(float(mass[dest == code].sum()) - float(h[name][ti]))
                )
            if not (dest[~fluid] == -3).all() or (dest[fluid] == -3).any():
                checks["fluid_cohort_identity"] = False

        # Check 21: destination codes cover legal vocabulary (-3 to nr)
        # Check 22: non-fluid fixed particles marked -3, fluid particles never -3
        # Check 23: every frame unknown, loss, invalid mass ledger residual bounded
        checks["every_frame_unknown_loss_invalid_ledger"] = max_residual <= 1e-8

        # Verify all 13 mandatory payload datasets are present
        for ds_name in MANDATORY_PAYLOAD_DATASETS:
            if ds_name not in h:
                checks[f"payload_dataset_{ds_name}"] = False

        for ds_name in MANDATORY_SUMMARY_DATASETS:
            if ds_name not in h:
                checks[f"summary_dataset_{ds_name}"] = False

        passed = len(checks) >= 23 and all(checks.values())
        return {
            "checks": checks,
            "passed": passed,
            "category_count": len(checks),
            "frames": int(nt),
            "identities": int(n),
            "fluid_identities": int(fluid.sum()),
            "initial_native_float_mass_kg": float(mass.sum()),
            "observed_first_passages": int(observed[fluid].sum()),
            "final_numerical_loss_mass_kg": float(h["numerical_loss_mass_kg"][-1]),
            "final_unknown_mass_kg": float(h["unknown_mass_kg"][-1]),
            "maximum_ledger_residual_kg": float(max_residual),
            "q_n_status": "not_assessed",
            "production_approval": "none",
        }


def validate_root_guard(binding: Dict[str, Any]) -> None:
    """Validate binding inputs, receipts, and physical condition body hash."""
    # 1. Check physical condition hash
    cond_hash = binding.get("physical_condition_sha256")
    if cond_hash != CANONICAL_PHYSICAL_CONDITION_SHA256:
        raise ValueError(
            f"Invalid physical condition hash: expected canonical {CANONICAL_PHYSICAL_CONDITION_SHA256}, got {cond_hash}"
        )
    if cond_hash in FORBIDDEN_SINGLE_AXIS_HASHES:
        raise ValueError("Single-axis controls hash MUST NOT transfer to two-axis mechanism")

    # 2. Check erratum marker
    declared = binding.get("declared_top_level_digest")
    if declared and declared != DECLARED_TOP_LEVEL_ERRATUM_MARKER:
        raise ValueError(
            f"Erratum declared digest mismatch: expected {DECLARED_TOP_LEVEL_ERRATUM_MARKER}, got {declared}"
        )

    # 3. Check source conversion receipt and report
    receipt_path = Path(binding["conversion_receipt"])
    report_path = Path(binding["conversion_report"])
    if not receipt_path.is_file():
        raise FileNotFoundError(f"Missing conversion receipt: {receipt_path}")
    if not report_path.is_file():
        raise FileNotFoundError(f"Missing conversion report: {report_path}")

    if digest(receipt_path) != binding["conversion_receipt_sha256"]:
        raise ValueError(f"Conversion receipt SHA mismatch: {receipt_path}")
    if digest(report_path) != binding["conversion_report_sha256"]:
        raise ValueError(f"Conversion report SHA mismatch: {report_path}")

    receipt = json.loads(receipt_path.read_text())
    report = json.loads(report_path.read_text())
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError("Actual completed typed conversion with returncode 0 required")
    if report.get("conversion_status") != "completed":
        raise ValueError("Conversion report status must be completed")

    # 4. Check source HDF5 existence
    source_h5 = Path(binding["source_hdf5"])
    if not source_h5.is_file():
        raise FileNotFoundError(f"Missing source trajectory HDF5: {source_h5}")


def run_labels_worker(
    binding_path: Path,
    config_path: Path,
    output_dir: Path,
    scratch_parent: Path | None = None,
    dry_run_check: bool = False,
) -> Dict[str, Any]:
    """Execute Root-guarded label materialization and 23-category closure evaluation."""
    binding = json.loads(binding_path.read_text())
    validate_root_guard(binding)

    config = json.loads(config_path.read_text())
    source_h5 = Path(binding["source_hdf5"])

    if dry_run_check:
        return {
            "status": "preflight_passed",
            "binding": binding_path.name,
            "source_h5": str(source_h5),
            "expected_h5_sha256": binding["source_hdf5_sha256"],
            "physical_condition_sha256": binding["physical_condition_sha256"],
            "declared_top_level_digest": binding.get("declared_top_level_digest"),
            "event_config": config_path.name,
            "closure_categories": 23,
            "mandatory_payload_datasets": len(MANDATORY_PAYLOAD_DATASETS),
            "mandatory_summary_datasets": len(MANDATORY_SUMMARY_DATASETS),
            "q_n": "not_granted",
            "production_approval": "none",
        }

    # Verify source HDF5 hash before processing
    source_hash_before = digest(source_h5)
    if source_hash_before != binding["source_hdf5_sha256"]:
        raise ValueError(
            f"Source HDF5 SHA256 changed: expected {binding['source_hdf5_sha256']}, got {source_hash_before}"
        )
    source_stat_before = source_h5.stat()

    output_dir.mkdir(parents=True, exist_ok=True)
    final_labels = output_dir / "native-labels.h5"
    stage_labels = output_dir / "native-labels.h5.unpublished"
    report_json = output_dir / "labels-report.json"

    if final_labels.exists() or stage_labels.exists():
        raise FileExistsError(f"Preserve existing label artifact: {final_labels}")

    # Import canonical materialize from scripts
    lab_scripts = Path(__file__).resolve().parents[4] / "scripts"
    if str(lab_scripts) not in sys.path:
        sys.path.insert(0, str(lab_scripts))

    from ds_data02_native_labels import materialize

    scratch = scratch_parent or Path(tempfile.gettempdir()) / "ds02-twoaxis-labels"
    scratch.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ds02-twoaxis-labels-", dir=scratch) as temp_dir:
        staged_source = Path(temp_dir) / "trajectory.h5"
        verified_copy(source_h5, staged_source, binding["source_hdf5_sha256"])

        with h5py.File(staged_source, "r") as h:
            expected_ids = np.column_stack((h["particle_zone"][:], h["particle_id"][:]))
            expected_mass = float(
                np.where(h["valid"][0].astype(bool) & (h["type"][0] == 3), h["mass"][0].astype(float), 0).sum()
            )

        # Materialize labels on staged file
        mat_result = materialize(staged_source, stage_labels, config, particle_chunk=65536)

        # Evaluate 23-category closure
        closure = evaluate_23_closure_categories(stage_labels, expected_ids, expected_mass)
        if not closure["passed"]:
            (output_dir / "failed-closure.json").write_text(json.dumps(closure, indent=2) + "\n")
            raise ValueError("Labels failed independent 23-category closure; preserve unpublished artifact")

        # Record provenance attributes
        with h5py.File(stage_labels, "r+") as h:
            h.attrs["source_hdf5"] = str(source_h5.resolve())
            h.attrs["source_hdf5_sha256"] = binding["source_hdf5_sha256"]
            h.attrs["canonical_physical_condition_sha256"] = CANONICAL_PHYSICAL_CONDITION_SHA256
            h.attrs["declared_top_level_erratum_marker"] = DECLARED_TOP_LEVEL_ERRATUM_MARKER
            h.attrs["mechanism_id"] = "F3_TWOAXIS_TRANSVERSE_LINACC_V1"
            h.attrs["audit_storage_protocol"] = (
                "SHA256-identical private NVMe input; unchanged canonical CELL3 label operator"
            )

        # Check source immutability
        source_stat_after = source_h5.stat()
        if (
            source_stat_before.st_ino,
            source_stat_before.st_size,
            source_stat_before.st_mtime_ns,
        ) != (
            source_stat_after.st_ino,
            source_stat_after.st_size,
            source_stat_after.st_mtime_ns,
        ):
            raise ValueError("CRITICAL: Source trajectory mutated during labeling!")

        os.replace(stage_labels, final_labels)

    final_sha = digest(final_labels)
    result = {
        "schema": "ds02.f3.twoaxis-canonical-native-labels-report.v1",
        "path": str(final_labels),
        "sha256": final_sha,
        "source_hdf5": str(source_h5),
        "source_hdf5_sha256": binding["source_hdf5_sha256"],
        "canonical_physical_condition_sha256": CANONICAL_PHYSICAL_CONDITION_SHA256,
        "declared_top_level_erratum_marker": DECLARED_TOP_LEVEL_ERRATUM_MARKER,
        "mechanism_id": "F3_TWOAXIS_TRANSVERSE_LINACC_V1",
        "closure": closure,
        "frames": closure["frames"],
        "identities": closure["identities"],
        "fluid_identities": closure["fluid_identities"],
        "initial_fluid_mass_kg": closure["initial_native_float_mass_kg"],
        "observed_first_passages": closure["observed_first_passages"],
        "q_n": "not_granted",
        "production_approval": "none",
        "claim": "Actual full canonical native labels; 23-category closure verified; source immutable",
    }
    report_json.write_text(json.dumps(result, indent=2) + "\n")
    return result


DEFAULT_CONFIG_PATH = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/legacy_plain_8/f3_legacy_plain_full_transport_config.v1.json"
)

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True, help="Path to label binding JSON")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to event configuration JSON",
    )
    parser.add_argument("--output-dir", type=Path, required=True, help="Output directory for labels")
    parser.add_argument("--scratch-parent", type=Path, default=None, help="Optional scratch directory")
    parser.add_argument(
        "--dry-run-check", action="store_true", help="Perform preflight validation without executing materialization"
    )
    args = parser.parse_args()

    def sig_handler(*_: Any) -> None:
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, sig_handler)

    res = run_labels_worker(
        binding_path=args.binding,
        config_path=args.config,
        output_dir=args.output_dir,
        scratch_parent=args.scratch_parent,
        dry_run_check=args.dry_run_check,
    )
    print(json.dumps(res, indent=2), flush=True)


if __name__ == "__main__":
    main()
