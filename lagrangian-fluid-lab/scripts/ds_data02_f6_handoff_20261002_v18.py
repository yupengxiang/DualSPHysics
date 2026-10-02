#!/usr/bin/env python3
"""F6 additive conversion retry with the integration virtualenv preserved.

The frozen v16 wrapper resolved ``.venv/bin/python`` to the system interpreter,
which exposed an ABI-incompatible system h5py.  v18 keeps the failed attempt
immutable and runs the converter through the literal virtualenv symlink path.
It does not start a solver or GPU job.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
V16 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v16.py")
V17 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v17.py")
spec = importlib.util.spec_from_file_location("f6_handoff_20261002_v16_for_conversion_retry", V16)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load frozen v16 module: {V16}")
V16_MODULE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V16_MODULE)

FAMILY_ROOT = V16_MODULE.FAMILY_ROOT
RAW_ROOT = V16_MODULE.RAW_ROOT
INTEGRATION_LAB = V16_MODULE.INTEGRATION_LAB
# Do not call resolve(): the symlink is the virtualenv selection mechanism.
VENV_PYTHON = INTEGRATION_LAB / ".venv/bin/python"
CONVERTER = V16_MODULE.CONVERTER
NATIVE_LABELS = V16_MODULE.NATIVE_LABELS
SIMPLE_LABEL_CONFIG = V16_MODULE.SIMPLE_LABEL_CONFIG
WAVE_LABEL_CONFIG = V16_MODULE.WAVE_LABEL_CONFIG
POST_ROOT = FAMILY_ROOT / "postprocessing_003"
REQUEST_ROOT = POST_ROOT / "execution_requests"
MECHANISMS = ("simple_free_response", "wave_no_contact")


def sha256(path: Path) -> str:
    return V16_MODULE.sha256(path)


def write_json(path: Path, value: Any) -> None:
    V16_MODULE.MODULE.write_json(path, value)


def read_json(path: Path) -> dict[str, Any]:
    return V16_MODULE.read_json(path)


def _source_inputs(row: dict[str, Any], mechanism: str) -> tuple[dict[str, Path], list[Path]]:
    case = V16_MODULE._old_medium_case(mechanism)
    paths = V16_MODULE._old_medium_paths(case)
    inputs = V16_MODULE._post_common_inputs(row)
    config = SIMPLE_LABEL_CONFIG if mechanism == "simple_free_response" else WAVE_LABEL_CONFIG
    inputs.extend([SCRIPT, V16, V17, V17.parent / "ds_data02_f6_handoff_20261002_v17.py", VENV_PYTHON, CONVERTER, NATIVE_LABELS, config])
    unique: list[Path] = []
    seen: set[str] = set()
    for value in inputs:
        path = Path(value)
        key = str(path.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(path)
    missing = [str(path) for path in unique if not path.is_file()]
    if missing:
        raise FileNotFoundError("conversion retry input missing: " + ", ".join(missing))
    return paths, unique


def prepare() -> dict[str, Any]:
    audit = read_json(V16_MODULE.MEDIUM_AUDIT_PATH)
    rows = audit.get("cases", [])
    if len(rows) != 2 or not all(row.get("postprocessing_ready") for row in rows):
        raise RuntimeError("medium terminal audit is not ready")
    REQUEST_ROOT.mkdir(parents=True, exist_ok=True)
    requests = []
    repair = {
        "schema": "ds-data-02.f6.rigid003.postprocessing_003.conversion_retry_001.v1",
        "family_id": "F6",
        "source_failed_attempts": [],
        "root_cause": "v16 resolved .venv/bin/python to /usr/bin/python3.10; system h5py and numpy ABI are incompatible",
        "repair": "execute the same converter through the literal integration .venv/bin/python path",
        "old_attempts_immutable": True,
        "gpu_launch": False,
    }
    for row in rows:
        mechanism = row["mechanism_id"]
        case = V16_MODULE._old_medium_case(mechanism)
        paths, inputs = _source_inputs(row, mechanism)
        cid = str(case["case_id"])
        old_attempt = f"{cid}_NATIVE_H5_001"
        conversion_attempt = f"{cid}_NATIVE_H5_002"
        conversion_output = RAW_ROOT / cid / conversion_attempt / "trajectory.h5"
        report_output = RAW_ROOT / cid / conversion_attempt / "conversion-report.json"
        common = {
            "schema": "ds-data-02.runner.request.v1",
            "family_id": "F6",
            "case_id": cid,
            "mechanism_id": mechanism,
            "resolution_id": "medium",
            "kind": "cpu",
            "cpu_task_kind": "conversion",
            "cpu_threads": 4,
            "max_wall_seconds": 1800,
            "estimated_storage_bytes": 2147483648,
            "input_files": [str(path.resolve()) for path in inputs],
            "input_hashes_at_request": {str(path.resolve()): sha256(path) for path in inputs},
            "worktree_root": str(V16_MODULE.MODULE.REPO_ROOT.resolve()),
            "cwd": str(INTEGRATION_LAB.resolve()),
            "source_raw_tree_manifest": row["native_frames"]["tree_manifest"],
            "source_raw_tree_manifest_sha256": row["native_frames"]["tree_manifest_sha256"],
            "source_solver_attempt": row["solver_receipt"]["path"],
            "source_solver_receipt_sha256": row["solver_receipt"]["sha256"],
            "supersedes_attempt": old_attempt,
            "retry_root_cause": repair["root_cause"],
            "conversion_concurrency_note": "one conversion slot; submit only through shared runtime v2",
            "q_n_status": "pending",
            "gpu_launch": False,
        }
        conversion = {
            **common,
            "attempt_id": conversion_attempt,
            "command": [str(VENV_PYTHON), str(SCRIPT), "run-native-conversion", "--case-id", cid, "--data-dir", str(paths["data"].resolve()), "--generated-xml", str(paths["xml"].resolve()), "--manifest", str(Path(row["native_frames"]["tree_manifest"]).resolve()), "--output", "{attempt_root}/trajectory.h5", "--report", "{attempt_root}/conversion-report.json"],
            "purpose": "retry full native BI4 to HDF5 using the integration virtualenv; old failed attempt remains evidence",
            "output_contract": {"trajectory": str(conversion_output), "report": str(report_output), "frames": 241, "complete_rigid_state": ["pose", "orientation", "quaternion", "linear_velocity", "angular_velocity", "force", "torque", "massbody", "inertia"]},
        }
        conversion_path = REQUEST_ROOT / f"{cid}_native_h5_002.json"
        write_json(conversion_path, conversion)
        requests.append({"path": str(conversion_path.resolve()), "sha256": sha256(conversion_path), "kind": "conversion", "case_id": cid})

        label_config = SIMPLE_LABEL_CONFIG if mechanism == "simple_free_response" else WAVE_LABEL_CONFIG
        label_attempt = f"{cid}_LABELS_002"
        label_inputs = inputs + [conversion_output]
        labels = {
            **common,
            "attempt_id": label_attempt,
            "cpu_task_kind": "labels",
            "cpu_threads": 2,
            "max_wall_seconds": 900,
            "estimated_storage_bytes": 536870912,
            "input_files": [str(path.resolve()) for path in label_inputs],
            "input_hashes_at_request": {str(path.resolve()): (sha256(path) if path.is_file() else "deferred_until_native_h5_002_receipt") for path in label_inputs},
            "command": [str(VENV_PYTHON), str(SCRIPT), "run-labels", "--source", str(conversion_output.resolve()), "--config", str(label_config.resolve()), "--output", "{attempt_root}/native-labels.h5"],
            "purpose": "materialize native labels only after v18 HDF5 conversion succeeds",
            "deferred_until_attempt": conversion_attempt,
            "source_trajectory": str(conversion_output.resolve()),
            "source_trajectory_sha256": "deferred_until_native_h5_002_receipt",
            "required_label_semantics": ["fluid_type3_only", "fixed_identity", "finite_saved_frame_chord_events", "mass_ledger", "no_model"],
        }
        labels_path = REQUEST_ROOT / f"{cid}_labels_002.json"
        write_json(labels_path, labels)
        requests.append({"path": str(labels_path.resolve()), "sha256": sha256(labels_path), "kind": "labels", "case_id": cid, "deferred": True})
        repair["source_failed_attempts"].append({"case_id": cid, "attempt_id": old_attempt, "receipt": str((RAW_ROOT / cid / old_attempt / "execution-receipt.json").resolve())})

    write_json(POST_ROOT / "conversion_retry_evidence_001.json", repair)
    result = {
        "schema": "ds-data-02.f6.rigid003.postprocessing_003.requests_001.v1",
        "family_id": "F6",
        "created_at": V16_MODULE.MODULE.now(),
        "status": "prepared_pending_shared_conversion_slot",
        "requests": requests,
        "conversion_launch": False,
        "gpu_launch": False,
        "retry_evidence": str((POST_ROOT / "conversion_retry_evidence_001.json").resolve()),
        "q_n_status": "pending actual HDF5 and labels",
    }
    write_json(POST_ROOT / "request_manifest.json", result)
    return result


def _verify_tree(manifest: Path, data_dir: Path) -> None:
    V16_MODULE._verify_tree(manifest, data_dir)


def _run_native_conversion(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).resolve()
    manifest = Path(args.manifest).resolve()
    output = Path(args.output).resolve()
    report = Path(args.report).resolve()
    _verify_tree(manifest, data_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [str(VENV_PYTHON), str(CONVERTER.resolve()), "--direct-run", "--case-id", args.case_id, "--data-dir", str(data_dir), "--generated-xml", str(Path(args.generated_xml).resolve()), "--output", str(output), "--report", str(report)]
    completed = subprocess.run(command, cwd=INTEGRATION_LAB, check=False)
    if completed.returncode != 0:
        return completed.returncode
    _verify_tree(manifest, data_dir)
    return 0


def _run_labels(args: argparse.Namespace) -> int:
    return V16_MODULE._run_labels(args)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "run-native-conversion", "run-labels"])
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.action == "run-native-conversion":
        for name in ("case_id", "data_dir", "manifest", "generated_xml", "output", "report"):
            if getattr(args, name) is None:
                parser.error(f"run-native-conversion requires --{name.replace('_', '-')}")
        return _run_native_conversion(args)
    for name in ("source", "config", "output"):
        if getattr(args, name) is None:
            parser.error(f"run-labels requires --{name}")
    return _run_labels(args)


if __name__ == "__main__":
    raise SystemExit(main())
