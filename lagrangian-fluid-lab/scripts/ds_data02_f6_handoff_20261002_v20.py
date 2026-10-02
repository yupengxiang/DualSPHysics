#!/usr/bin/env python3
"""F6 enriched native trajectory metadata and rigid-state QA.

v19 successfully preserved sparse native identities, but the shared XML parser
only recognized the legacy ``Ixx/Iyy/Izz`` spelling.  RIGID003 serializes the
diagonal inertia as ``x/y/z``.  This additive wrapper keeps v19/H5_003 intact,
reuses its native sparse conversion in a new attempt, and records the actual
mass, center, body-frame inertia, and initial saved-pose comparison.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

try:
    import h5py
except (ImportError, OSError, ValueError):  # test/import on system Python only
    h5py = None  # type: ignore[assignment]


SCRIPT = Path(__file__).resolve()
V19 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v19.py")
V19_SPEC = importlib.util.spec_from_file_location("f6_handoff_v19_for_enriched_metadata", V19)
if V19_SPEC is None or V19_SPEC.loader is None:
    raise RuntimeError(f"cannot load v19: {V19}")
V19_MODULE = importlib.util.module_from_spec(V19_SPEC)
V19_SPEC.loader.exec_module(V19_MODULE)

V16_MODULE = V19_MODULE.V16_MODULE
FAMILY_ROOT = V19_MODULE.FAMILY_ROOT
RAW_ROOT = V19_MODULE.RAW_ROOT
INTEGRATION_LAB = V19_MODULE.INTEGRATION_LAB
VENV_PYTHON = V19_MODULE.VENV_PYTHON
POST_ROOT = FAMILY_ROOT / "postprocessing_005"
REQUEST_ROOT = POST_ROOT / "execution_requests"


def sha256(path: Path) -> str:
    return V19_MODULE.sha256(path)


def read_json(path: Path) -> dict[str, Any]:
    return V19_MODULE.read_json(path)


def write_json(path: Path, value: Any) -> None:
    V19_MODULE.write_json(path, value)


def _contract_from_xml(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    node = root.find(".//execution/particles/floating")
    if node is None:
        raise ValueError(f"execution floating contract missing: {path}")
    massbody_node = node.find("massbody")
    masspart_node = node.find("masspart")
    center_node = node.find("center")
    inertia_node = node.find("inertia")
    if any(item is None for item in (massbody_node, masspart_node, center_node, inertia_node)):
        raise ValueError(f"incomplete floating contract: {path}")
    massbody = float(massbody_node.get("value", "nan"))
    masspart = float(masspart_node.get("value", "nan"))
    center = [float(center_node.get(axis, "nan")) for axis in "xyz"]
    inertia_diag = [float(inertia_node.get(axis, "nan")) for axis in "xyz"]
    if not (math.isfinite(massbody) and massbody > 0 and math.isfinite(masspart) and masspart > 0):
        raise ValueError("floating mass contract is not positive finite")
    if not all(math.isfinite(value) for value in center + inertia_diag) or not all(value > 0 for value in inertia_diag):
        raise ValueError("floating center/inertia contract is not finite positive")
    return {
        "massbody_kg": massbody,
        "masspart_kg": masspart,
        "center_m": center,
        "inertia_diag_kg_m2": inertia_diag,
        "inertia_tensor_kg_m2": [[inertia_diag[0], 0.0, 0.0], [0.0, inertia_diag[1], 0.0], [0.0, 0.0, inertia_diag[2]]],
        "serialization": {"massbody": massbody_node.attrib, "masspart": masspart_node.attrib, "center": center_node.attrib, "inertia": inertia_node.attrib},
        "xml_sha256": sha256(path),
    }


def _enrich_h5(path: Path, contract: dict[str, Any]) -> dict[str, Any]:
    if h5py is None:
        raise RuntimeError("enriched H5 QA requires the integration .venv Python with compatible h5py")
    with h5py.File(path, "r+") as handle:
        handle.attrs["floating_massbody_kg"] = contract["massbody_kg"]
        handle.attrs["floating_masspart_kg"] = contract["masspart_kg"]
        handle.attrs["floating_center_m"] = json.dumps(contract["center_m"], separators=(",", ":"))
        handle.attrs["floating_inertia_kg_m2"] = json.dumps(contract["inertia_tensor_kg_m2"], separators=(",", ":"))
        handle.attrs["floating_inertia_source"] = "generated XML execution/particles/floating/inertia @x,@y,@z"
        handle.attrs["floating_contract_xml_sha256"] = contract["xml_sha256"]
        handle.attrs["rigid_metadata_schema"] = "ds-data-02.f6.rigid-body-contract.v2"
        handle.attrs["rigid_metadata_qa"] = "positive_mass_positive_diagonal_inertia_initial_pose_checked"
        group = handle["rigid_body"]
        group.attrs["mass_kg"] = contract["massbody_kg"]
        group.attrs["masspart_kg"] = contract["masspart_kg"]
        group.attrs["center_m"] = json.dumps(contract["center_m"], separators=(",", ":"))
        group.attrs["inertia_tensor_kg_m2"] = json.dumps(contract["inertia_tensor_kg_m2"], separators=(",", ":"))
        group.attrs["inertia_frame"] = "floating body frame from generated XML"
        group.attrs["inertia_source_xml_sha256"] = contract["xml_sha256"]
        position0 = [float(value) for value in group["position"][0]]
        fit_error = max(abs(a - b) for a, b in zip(position0, contract["center_m"]))
        force0 = [float(value) for value in group["fluid_force"][0]]
        torque0 = [float(value) for value in group["fluid_torque"][0]]
        qa = {
            "massbody_positive": contract["massbody_kg"] > 0,
            "masspart_positive": contract["masspart_kg"] > 0,
            "inertia_diagonal_positive": all(value > 0 for value in contract["inertia_diag_kg_m2"]),
            "inertia_not_default_zero": any(abs(value) > 0 for value in contract["inertia_diag_kg_m2"]),
            "initial_saved_pose_m": position0,
            "floating_contract_center_m": contract["center_m"],
            "initial_pose_center_fit_max_abs_m": fit_error,
            "initial_pose_center_fit_tolerance_m": 1.0e-5,
            "initial_pose_center_fit": fit_error <= 1.0e-5,
            "force_dataset_finite": all(math.isfinite(value) for value in force0),
            "torque_dataset_finite": all(math.isfinite(value) for value in torque0),
            "frame_count": int(len(group["position"])),
            "rigid_state_fields": sorted(group.keys()),
        }
    if not all(qa[key] for key in ("massbody_positive", "masspart_positive", "inertia_diagonal_positive", "inertia_not_default_zero", "initial_pose_center_fit", "force_dataset_finite", "torque_dataset_finite")):
        raise ValueError(f"enriched rigid-state QA failed: {qa}")
    return qa


def prepare() -> dict[str, Any]:
    """Prepare additive enriched conversion requests for the two medium cases."""

    audit = read_json(V16_MODULE.MEDIUM_AUDIT_PATH)
    rows = audit.get("cases", [])
    if len(rows) != 2 or not all(row.get("postprocessing_ready") for row in rows):
        raise RuntimeError("medium terminal audit is not ready")
    REQUEST_ROOT.mkdir(parents=True, exist_ok=True)
    requests: list[dict[str, Any]] = []
    for row in rows:
        mechanism = str(row["mechanism_id"])
        case = V16_MODULE._old_medium_case(mechanism)
        paths, inputs, motion_csv = V19_MODULE._source_inputs(row, mechanism)
        cid = str(case["case_id"])
        previous = RAW_ROOT / cid / f"{cid}_NATIVE_H5_003"
        previous_h5 = previous / "trajectory.h5"
        previous_report = previous / "conversion-report.json"
        inputs.extend([SCRIPT, V19, previous_h5, previous_report])
        unique: list[Path] = []
        seen: set[str] = set()
        for value in inputs:
            path = Path(value)
            key = str(path) if path == VENV_PYTHON else str(path.resolve())
            if key not in seen:
                seen.add(key)
                unique.append(path)
        if any(not path.is_file() for path in unique):
            raise FileNotFoundError("enriched input missing: " + ", ".join(str(path) for path in unique if not path.is_file()))
        strings = [str(path) if path == VENV_PYTHON else str(path.resolve()) for path in unique]
        hashes = {key: sha256(Path(key)) for key in strings}
        attempt = f"{cid}_NATIVE_H5_004"
        output = RAW_ROOT / cid / attempt / "trajectory.h5"
        report = RAW_ROOT / cid / attempt / "conversion-report.json"
        request = {
            "schema": "ds02.runner.request.v1",
            "family_id": "F6",
            "case_id": cid,
            "mechanism_id": mechanism,
            "resolution_id": "medium",
            "attempt_id": attempt,
            "kind": "cpu",
            "cpu_task_kind": "conversion",
            "cpu_threads": 4,
            "max_wall_seconds": 1800,
            "estimated_storage_bytes": 2147483648,
            "worktree_root": str(V16_MODULE.MODULE.REPO_ROOT.resolve()),
            "cwd": str(INTEGRATION_LAB),
            "command": [str(VENV_PYTHON), str(SCRIPT), "run-enriched-conversion", "--case-id", cid, "--data-dir", str(paths["data"].resolve()), "--generated-xml", str(paths["xml"].resolve()), "--motion-csv", str(motion_csv.resolve()), "--manifest", str(Path(row["native_frames"]["tree_manifest"]).resolve()), "--output", "{attempt_root}/trajectory.h5", "--report", "{attempt_root}/conversion-report.json"],
            "input_files": strings,
            "input_hashes_at_request": hashes,
            "source_sparse_attempt": f"{cid}_NATIVE_H5_003",
            "source_sparse_h5_sha256": sha256(previous_h5),
            "purpose": "enrich native sparse H5 with XML x/y/z rigid inertia, center, mass and saved-pose QA",
            "output_contract": {"trajectory": str(output), "report": str(report), "frames": 241, "positive_inertia_required": True, "saved_pose_center_fit_tolerance_m": 1.0e-5},
            "gpu_launch": False,
            "q_n_status": "pending_native_exclusion_reconciliation",
        }
        path = REQUEST_ROOT / f"{cid}_native_h5_004.json"
        write_json(path, request)
        requests.append({"path": str(path.resolve()), "sha256": sha256(path), "kind": "conversion", "case_id": cid})
    evidence = {"schema": "ds-data-02.f6.rigid003.postprocessing_005.enriched_metadata_001.v1", "family_id": "F6", "source_h5_003_immutable": True, "repair": "parse execution floating center/inertia attributes x/y/z and QA initial saved pose", "gpu_launch": False, "q_n_status": "pending_native_exclusion_reconciliation", "requests": requests}
    write_json(POST_ROOT / "enriched_metadata_evidence_001.json", evidence)
    result = {"schema": "ds-data-02.f6.rigid003.postprocessing_005.requests_001.v1", "family_id": "F6", "status": "prepared_pending_shared_conversion_slot", "requests": requests, "gpu_launch": False, "q_n_status": "pending enriched rigid metadata and PartVTKOut"}
    write_json(POST_ROOT / "request_manifest.json", result)
    return result


def _run_enriched(args: argparse.Namespace) -> int:
    if V19_MODULE.V16_MODULE is None:
        raise RuntimeError("v16 module unavailable")
    data_dir = Path(args.data_dir).resolve()
    manifest = Path(args.manifest).resolve()
    V19_MODULE._verify_tree(manifest, data_dir)
    contract = _contract_from_xml(Path(args.generated_xml).resolve())
    report = V19_MODULE.convert_sparse(case_id=str(args.case_id), data_dir=data_dir, generated_xml=Path(args.generated_xml), motion_csv=Path(args.motion_csv), output_h5=Path(args.output), report_path=Path(args.report))
    qa = _enrich_h5(Path(args.output).resolve(), contract)
    report["schema"] = "ds02.f6.enriched-sparse-conversion-report.v1"
    report["rigid_contract"] = contract
    report["rigid_state_qa"] = qa
    report["output_sha256"] = sha256(Path(args.output).resolve())
    report["q_n_status"] = "pending_native_exclusion_reconciliation"
    Path(args.report).resolve().write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    V19_MODULE._verify_tree(manifest, data_dir)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "run-enriched-conversion"])
    parser.add_argument("--case-id")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--motion-csv", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        print(json.dumps(prepare(), ensure_ascii=False, indent=2))
        return 0
    required = ("case_id", "data_dir", "generated_xml", "motion_csv", "manifest", "output", "report")
    for name in required:
        if getattr(args, name) is None:
            parser.error(f"run-enriched-conversion requires --{name.replace('_', '-')}")
    return _run_enriched(args)


if __name__ == "__main__":
    raise SystemExit(main())
