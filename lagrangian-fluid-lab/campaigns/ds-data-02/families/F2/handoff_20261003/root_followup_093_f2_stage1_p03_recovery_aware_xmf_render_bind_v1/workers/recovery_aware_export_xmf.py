#!/usr/bin/env python3
"""Recovery-aware XDMF publisher for an interrupted DS-DATA-02 conversion.

The original conversion receipt is an immutable lifecycle fact.  This worker
accepts it only when a separate, completed opaque artifact audit proves the
published HDF5 bytes and JSON report.  It never edits or reclassifies that
receipt.  --metadata-only performs source contract checks without opening or
hashing the HDF5; normal root-owned execution is the only path that reads the
HDF5 to publish a complete temporal XDMF sidecar.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

FIELDS = (
    "valid",
    "initial_type",
    "particle_id",
    "particle_zone",
    "initial_mk",
    "initial_mass",
    "mass",
    "velocity",
    "density",
    "pressure",
    "type",
)
VECTOR_FIELDS = {"velocity"}
HEX = set("0123456789abcdefABCDEF")


class ContractError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ref(value, label: str) -> tuple[Path, dict]:
    if isinstance(value, (str, Path)):
        return Path(value), {"path": str(value)}
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise ContractError(f"{label} must be a path reference")
    return Path(value["path"]), value


def _json_ref(value, label: str) -> tuple[Path, dict, dict]:
    path, ref = _ref(value, label)
    if not path.is_file():
        raise ContractError(f"{label} is missing: {path}")
    declared = ref.get("sha256")
    if declared is not None:
        if not isinstance(declared, str) or len(declared) != 64 or not set(declared) <= HEX:
            raise ContractError(f"{label} has an invalid declared SHA-256")
        actual = sha256(path)
        if actual != declared:
            raise ContractError(f"{label} changed: {actual} != {declared}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not readable JSON: {path}") from exc
    if not isinstance(data, dict):
        raise ContractError(f"{label} must contain a JSON object")
    return path, ref, data


def _same(actual, expected, label: str) -> None:
    if actual != expected:
        raise ContractError(f"{label} differs: {actual!r} != {expected!r}")


def _positive_int(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractError(f"{label} must be a positive integer")
    return value


def read_contract(binding_path: Path) -> dict:
    _, _, binding = _json_ref(binding_path, "binding")
    required = (
        "schema",
        "case_id",
        "physical_case_id",
        "physical_condition_sha256",
        "canonical_physical_binding_sha256",
        "canonical_native_condition_sha256",
        "numerical_recipe_sha256",
        "expected_frames",
        "expected_particles",
        "source_h5",
        "original_conversion",
        "recovery_audit",
        "canonical_binding",
        "owner_metadata",
        "renderer_contract",
    )
    missing = [key for key in required if key not in binding]
    if missing:
        raise ContractError("binding is missing: " + ", ".join(missing))
    _same(binding["schema"], "ds02.f2.recovery-aware-temporal-binding.v1", "binding schema")
    if binding.get("source_only") is not True:
        raise ContractError("binding must remain source-only")
    if binding.get("independent_case_count_increment") != 0:
        raise ContractError("derived preview cannot increment case count")
    _positive_int(binding["expected_frames"], "expected_frames")
    _positive_int(binding["expected_particles"], "expected_particles")
    return binding


def verify_metadata(binding_path: Path, binding: dict) -> dict:
    """Verify only JSON provenance.  This function never opens source_h5."""
    source_h5_path, source_h5 = _ref(binding["source_h5"], "source_h5")
    if not source_h5_path.is_absolute() or not source_h5_path.name.endswith(".h5"):
        raise ContractError("source_h5 must be an absolute HDF5 path")
    expected_h5_sha = source_h5.get("sha256")
    if not isinstance(expected_h5_sha, str) or len(expected_h5_sha) != 64:
        raise ContractError("source_h5.sha256 must be the producer's expected digest")
    if binding.get("source_h5_read_policy") != "root_worker_only_hash_and_read":
        raise ContractError("source HDF5 read policy is not root-worker-only")
    if binding.get("visual_status") != "pending":
        raise ContractError("binding cannot pre-approve visual status")
    if binding.get("q_n") != "not_granted" or binding.get("production_approval") != "none":
        raise ContractError("binding carries an impermissible acceptance claim")

    original = binding["original_conversion"]
    original_receipt_path, original_receipt_ref, original_receipt = _json_ref(
        original["receipt"], "original conversion receipt"
    )
    expected_original = original["receipt"]
    _same(original_receipt.get("status"), expected_original.get("status"), "original receipt status")
    _same(original_receipt.get("returncode"), expected_original.get("returncode"),
          "original receipt returncode")
    _same(original_receipt.get("pid"), expected_original.get("pid"), "original receipt pid")
    if original_receipt.get("status") != "running" or original_receipt.get("returncode") is not None:
        raise ContractError("recovery binding requires the preserved running/null original receipt")
    _same(original.get("tool_status"), 143, "original tool status")
    if original.get("conversion_completed_claim") is not False:
        raise ContractError("original conversion cannot be claimed completed")
    if original.get("must_preserve_byte_exact") is not True:
        raise ContractError("original receipt preservation guard is missing")

    report_path, report_ref, report = _json_ref(original["report"], "conversion report")
    _same(report.get("output_sha256"), expected_h5_sha, "conversion report output SHA")
    frames = _positive_int(report.get("frames"), "conversion report frames")
    particles = _positive_int(report.get("particles"), "conversion report particles")
    _same(frames, binding["expected_frames"], "report/binding frames")
    _same(particles, binding["expected_particles"], "report/binding particles")
    _same(report.get("hash_scopes", {}).get("physical_condition_sha256"),
          binding["canonical_native_condition_sha256"],
          "report canonical physical condition")

    audit = binding["recovery_audit"]
    audit_receipt_path, audit_receipt_ref, audit_receipt = _json_ref(
        audit["receipt"], "recovery audit execution receipt"
    )
    _same(audit_receipt.get("status"), "completed", "recovery audit receipt status")
    _same(audit_receipt.get("returncode"), 0, "recovery audit receipt returncode")
    audit_path, audit_ref, audit_data = _json_ref(audit["report"], "recovery audit report")
    _same(audit_data.get("artifact_integrity_status"), "completed", "artifact audit status")
    _same(audit_data.get("worker_returncode"), 0, "artifact audit worker returncode")
    _same(audit_data.get("opaque_hash_only"), True, "artifact audit opaque mode")
    _same(audit_data.get("arrays_decoded"), False, "artifact audit array policy")
    _same(audit_data.get("partvtk_all_passed"), True, "artifact audit PartVTK status")
    _same(audit_data.get("source_conversion_reclassified"), False,
          "artifact audit source lifecycle")
    _same(audit_data.get("source_receipt_edited"), False,
          "artifact audit source receipt immutability")
    _same(audit_data.get("verified_trajectory_sha256"), expected_h5_sha,
          "artifact audit HDF5 SHA")
    _same(audit_data.get("source_receipt_sha256"), original_receipt_ref.get("sha256"),
          "artifact audit/original receipt SHA")
    _same(audit_data.get("source_report_sha256"), report_ref.get("sha256"),
          "artifact audit/report SHA")
    _same(audit_data.get("verified_frames"), binding["expected_frames"],
          "artifact audit frames")
    _same(audit_data.get("verified_particles"), binding["expected_particles"],
          "artifact audit particles")
    _same(audit_data.get("physical_case_id"), binding["physical_case_id"],
          "artifact audit physical case")
    _same(audit_data.get("physical_condition_sha256"), binding["physical_condition_sha256"],
          "artifact audit physical condition")

    canonical_path, canonical_ref, canonical = _json_ref(
        binding["canonical_binding"], "canonical native binding"
    )
    _same(canonical.get("canonical_physical_binding_sha256"),
          binding["canonical_physical_binding_sha256"],
          "canonical physical binding SHA")
    _same(canonical.get("source_physical_condition_sha256"),
          binding["physical_condition_sha256"],
          "source physical condition SHA")
    _same(binding["canonical_native_condition_sha256"],
          binding["canonical_physical_binding_sha256"],
          "canonical native condition SHA")
    owner_path, owner_ref, owner = _json_ref(binding["owner_metadata"], "owner metadata")
    _same(owner.get("physical_case_id"), binding["physical_case_id"], "owner physical case")
    _same(owner.get("physical_condition_sha256"), binding["physical_condition_sha256"],
          "owner physical condition")
    _same(owner.get("numerical_recipe_sha256"), binding["numerical_recipe_sha256"],
          "owner numerical recipe")

    actual = {
        "source_h5": str(source_h5_path),
        "source_h5_sha256": expected_h5_sha,
        "original_conversion_receipt": {
            "path": str(original_receipt_path),
            "sha256": original_receipt_ref.get("sha256"),
            "status": original_receipt.get("status"),
            "returncode": original_receipt.get("returncode"),
            "tool_status": original.get("tool_status"),
        },
        "conversion_report": {
            "path": str(report_path),
            "sha256": report_ref.get("sha256"),
            "frames": frames,
            "particles": particles,
            "conversion_status": report.get("conversion_status"),
        },
        "recovery_audit": {
            "receipt": {"path": str(audit_receipt_path), "sha256": audit_receipt_ref.get("sha256")},
            "report": {"path": str(audit_path), "sha256": audit_ref.get("sha256")},
            "status": audit_data.get("artifact_integrity_status"),
            "returncode": audit_data.get("worker_returncode"),
            "verified_frames": audit_data.get("verified_frames"),
            "verified_particles": audit_data.get("verified_particles"),
            "verified_trajectory_sha256": audit_data.get("verified_trajectory_sha256"),
        },
        "canonical_binding": {"path": str(canonical_path), "sha256": canonical_ref.get("sha256")},
        "owner_metadata": {"path": str(owner_path), "sha256": owner_ref.get("sha256")},
    }
    return actual


def _item(parent, dataset, source: Path, frame: int, frames: int, particles: int) -> None:
    shape = tuple(int(value) for value in dataset.shape)
    dtype = dataset.dtype
    if dtype.kind not in "uifb":
        raise ContractError(f"{dataset.name} has unsupported dtype {dtype}")
    dynamic = len(shape) >= 2 and shape[:2] == (frames, particles)
    if not dynamic and shape != (particles,):
        raise ContractError(f"{dataset.name} has unsupported shape {shape}")
    outshape = shape[1:] if dynamic else shape
    dimensions = " ".join(str(value) for value in outshape)
    target = parent
    if dynamic:
        target = ET.SubElement(parent, "DataItem", ItemType="HyperSlab",
                               Dimensions=dimensions, Type="HyperSlab")
        selection = ET.SubElement(target, "DataItem",
                                  Dimensions=f"3 {len(shape)}", Format="XML")
        selection.text = "\n" + "\n".join(
            " ".join(map(str, row))
            for row in (
                [frame] + [0] * (len(shape) - 1),
                [1] * len(shape),
                [1] + list(shape[1:]),
            )
        ) + "\n"
    ET.SubElement(
        target,
        "DataItem",
        Dimensions=" ".join(map(str, shape)),
        NumberType="Float" if dtype.kind == "f" else "UInt" if dtype.kind in "ub" else "Int",
        Precision=str(dtype.itemsize),
        Format="HDF",
    ).text = str(source) + ":" + dataset.name


def _write_xdmf(binding: dict, actual: dict, output_dir: Path, binding_path: Path) -> dict:
    import h5py
    import numpy as np

    source = Path(actual["source_h5"])
    original_sha = sha256(source)
    if original_sha != actual["source_h5_sha256"]:
        raise ContractError("source HDF5 differs from independent recovery audit")
    if output_dir.exists():
        raise ContractError(f"refusing to reuse output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)
    xmf_tmp = output_dir / "case.xmf.partial"
    manifest_tmp = output_dir / "manifest.json.partial"
    with h5py.File(source, "r") as h:
        missing = sorted(set(("time", "position", *FIELDS)) - set(h))
        if missing:
            raise ContractError("HDF5 is missing fields: " + ", ".join(missing))
        times = np.asarray(h["time"][:], dtype=np.float64)
        frames, particles, dimension = tuple(int(value) for value in h["position"].shape)
        _same(frames, binding["expected_frames"], "HDF5 frames")
        _same(particles, binding["expected_particles"], "HDF5 particles")
        _same(dimension, 3, "HDF5 position dimension")
        _same(len(times), frames, "HDF5 time length")
        if len(times) == 0 or times[0] != 0 or not np.isfinite(times).all() or not np.all(np.diff(times) > 0):
            raise ContractError("HDF5 time axis is not finite and strictly increasing")
        if times[-1] < float(binding["physical_window_s"][1]):
            raise ContractError("HDF5 ends before the bound physical window")
        field_meta = {}
        for name in ("time", "position", *FIELDS):
            field = h[name]
            field_meta[name] = {"shape": [int(v) for v in field.shape], "dtype": str(field.dtype)}
        velocity_shape = tuple(int(v) for v in h["velocity"].shape)
        if velocity_shape[-1] != 3 or len(velocity_shape) < 3:
            raise ContractError(f"velocity is not native N3: {velocity_shape}")

        root = ET.Element("Xdmf", Version="2.0")
        domain = ET.SubElement(root, "Domain")
        collection = ET.SubElement(
            domain, "Grid", Name=binding["physical_case_id"],
            GridType="Collection", CollectionType="Temporal"
        )
        for frame, time in enumerate(times):
            grid = ET.SubElement(collection, "Grid", Name=f"frame_{frame:04d}",
                                  GridType="Uniform")
            ET.SubElement(grid, "Time", Value=format(float(time), ".17g"))
            ET.SubElement(grid, "Topology", TopologyType="Polyvertex",
                          NumberOfElements=str(particles))
            geometry = ET.SubElement(grid, "Geometry", GeometryType="XYZ")
            _item(geometry, h["position"], source, frame, frames, particles)
            for name in FIELDS:
                field = h[name]
                attribute = ET.SubElement(
                    grid, "Attribute", Name=name, Center="Node",
                    AttributeType="Vector" if name in VECTOR_FIELDS else "Scalar"
                )
                _item(attribute, field, source, frame, frames, particles)
        condition = str(h.attrs.get("physical_condition_sha256", ""))
        _same(condition, binding["canonical_native_condition_sha256"],
              "HDF5 canonical native physical condition")
        ET.indent(root)
        ET.ElementTree(root).write(xmf_tmp, encoding="utf-8", xml_declaration=True)
    xmf_path = output_dir / "case.xmf"
    xmf_tmp.replace(xmf_path)
    xmf_sha = sha256(xmf_path)
    manifest = {
        "schema": "ds02.stage1.paraview-temporal-product.v1",
        "family_id": binding["family_id"],
        "case_id": binding["case_id"],
        "physical_case_id": binding["physical_case_id"],
        "physical_condition_sha256": binding["canonical_native_condition_sha256"],
        "source_physical_condition_sha256": binding["physical_condition_sha256"],
        "canonical_physical_binding_sha256": binding["canonical_physical_binding_sha256"],
        "numerical_recipe_sha256": binding["numerical_recipe_sha256"],
        "xdmf": str(xmf_path),
        "xdmf_sha256": xmf_sha,
        "source_h5": actual["source_h5"],
        "source_h5_sha256": actual["source_h5_sha256"],
        "frames": int(frames),
        "particles": int(particles),
        "actual_time_s": [float(value) for value in times],
        "fields": field_meta,
        "finite_fields": ["mass", "velocity", "density", "pressure"],
        "type_aliases": {"fixed": [0], "moving": [1], "floating": [2], "fluid": [3]},
        "boundary_type_codes": [0],
        "velocity_vector_dimension": 3,
        "native_vector_contract": "velocity is stored as N3 and is exported as XDMF Vector",
        "renderer_contract": "Root023 all saved frames; no diagnostic frame subset",
        "recovery_provenance": {
            "schema": "ds02.recovery-aware-xdmf-provenance.v1",
            "original_conversion_receipt": binding["original_conversion"],
            "artifact_recovery_audit": binding["recovery_audit"],
            "original_conversion_completed_claim": False,
            "independent_artifact_audit_completed": True,
            "source_receipt_edited": False,
        },
        "source_h5_read_only": True,
        "visual_status": "pending",
        "numerical_precision_status": "not accepted",
        "production_approval": "none",
        "q_n": "not_granted",
        "independent_case_count_increment": 0,
        "binding_sha256": sha256(binding_path),
    }
    manifest_tmp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    manifest_tmp.replace(output_dir / "manifest.json")
    (output_dir / "README.txt").write_text(
        "Root023 must render every saved frame from case.xmf.\n"
        "The velocity field is native N3; no component is remapped.\n"
        "This is a recovery-aware derived view. The original conversion receipt "
        "remains running/null with tool status 143 and is never rewritten.\n"
        "The independent opaque artifact audit proves the HDF5 bytes; visual review "
        "and any case/Q-N decision remain pending.\n",
        encoding="utf-8",
    )
    return {
        "xdmf": str(xmf_path),
        "xdmf_sha256": xmf_sha,
        "manifest": str(output_dir / "manifest.json"),
        "frames": frames,
        "particles": particles,
        "source_h5_sha256": actual["source_h5_sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--metadata-only", action="store_true")
    args = parser.parse_args()
    binding = read_contract(args.binding)
    actual = verify_metadata(args.binding, binding)
    if args.metadata_only:
        print(json.dumps({
            "status": "metadata_contract_pass",
            "source_h5_opened": False,
            "source_h5_hashed": False,
            "original_conversion": actual["original_conversion_receipt"],
            "recovery_audit": actual["recovery_audit"],
            "frames": actual["conversion_report"]["frames"],
            "particles": actual["conversion_report"]["particles"],
            "independent_case_count_increment": 0,
        }, sort_keys=True))
        return 0
    result = _write_xdmf(binding, actual, args.output_dir, args.binding)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
