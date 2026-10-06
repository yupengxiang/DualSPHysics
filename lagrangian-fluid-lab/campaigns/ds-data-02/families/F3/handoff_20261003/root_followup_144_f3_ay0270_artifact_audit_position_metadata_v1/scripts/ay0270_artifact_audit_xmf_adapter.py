#!/usr/bin/env python3
"""Build the AY0270 temporal XMF sidecar from independent audit evidence.

The preserved conversion attempt is intentionally *not* treated as a completed
conversion receipt: its receipt is still ``running`` and has no returncode
field.  This adapter accepts four separate metadata roles:

* original_conversion_receipt: the old, unresolved attempt;
* artifact_audit_receipt/report: Root1166's independent completed/0 audit;
* native_receipt: the completed/0 native production receipt; and
* conversion_report: the producer's completed report and legacy converter scope.

Only the registered Root CPU job may enter ``build``.  ``--metadata-preflight``
reads JSON/source metadata and does not open H5/BI4/CSV/DAT/VTK.  The build path
reuses the immutable fresh104 exporter for its FIELDS and XDMF DataItem writer,
then reads the existing H5 read-only and emits a new XMF/manifest.  It never
edits the old receipt, audit receipt, conversion report, or H5.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.f3.artifact-audit-aware-xmf-adapter.v1"
REQUEST_SCHEMA = "ds02.f3.artifact-audit-aware-xmf-request.v1"
RAW_SUFFIXES = {".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu", ".pvd"}


class BindingError(ValueError):
    """A disabled binding or metadata role is inconsistent."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BindingError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _absolute(path_text: str, *, label: str) -> Path:
    require(isinstance(path_text, str) and Path(path_text).is_absolute(),
            f"{label} must be an absolute path")
    return Path(path_text)


def _metadata_ref(ref: dict[str, Any], *, label: str) -> tuple[Path, dict[str, Any]]:
    require(isinstance(ref, dict), f"{label} must be an object")
    path = _absolute(ref.get("path"), label=f"{label}.path")
    expected = ref.get("sha256")
    require(isinstance(expected, str) and len(expected) == 64,
            f"{label}.sha256 must be present")
    require(path.suffix.lower() not in RAW_SUFFIXES,
            f"{label} cannot be a scientific payload")
    require(path.is_file(), f"{label} is missing: {path}")
    actual = sha256_file(path)
    require(actual == expected, f"{label} changed: {actual} != {expected}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BindingError(f"{label} is not a JSON object") from error
    require(isinstance(value, dict), f"{label} is not a JSON object")
    return path, value


def _file_ref(ref: dict[str, Any], *, label: str, allow_code: bool = True) -> Path:
    require(isinstance(ref, dict), f"{label} must be an object")
    path = _absolute(ref.get("path"), label=f"{label}.path")
    expected = ref.get("sha256")
    require(isinstance(expected, str) and len(expected) == 64,
            f"{label}.sha256 must be present")
    if not allow_code:
        require(path.suffix.lower() not in RAW_SUFFIXES, f"{label} is a payload")
    require(path.is_file(), f"{label} is missing: {path}")
    require(sha256_file(path) == expected, f"{label} changed")
    return path


def _role_path(binding: dict[str, Any], role: str) -> dict[str, Any]:
    value = binding.get(role)
    require(isinstance(value, dict), f"missing receipt role: {role}")
    return value


def _verify_metadata_closure(binding: dict[str, Any]) -> None:
    closure = binding.get("metadata_input_sha256")
    require(isinstance(closure, dict) and closure, "metadata_input_sha256 is empty")
    for path_text, expected in closure.items():
        path = _absolute(path_text, label="metadata input")
        require(path.suffix.lower() not in RAW_SUFFIXES,
                f"scientific payload in metadata input closure: {path}")
        require(isinstance(expected, str) and len(expected) == 64,
                f"invalid metadata input digest: {path}")
        require(path.is_file(), f"metadata input is missing: {path}")
        require(sha256_file(path) == expected, f"metadata input changed: {path}")


def _all_true(mapping: dict[str, Any], keys: tuple[str, ...], label: str) -> None:
    for key in keys:
        require(mapping.get(key) is True, f"{label}.{key} is not true")


def metadata_preflight(binding_path: Path) -> dict[str, Any]:
    """Validate role separation and metadata closure without opening scientific data."""
    binding_path = Path(binding_path).resolve()
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    require(binding.get("schema") == REQUEST_SCHEMA, "unexpected request schema")
    require(binding.get("source_only") is True, "source binding must remain source-only")
    require(binding.get("disabled") is True, "source XMF request must be disabled")
    require(binding.get("launch_allowed") is False and binding.get("execution_allowed") is False,
            "source XMF request cannot be launchable")
    require(binding.get("cpu_threads") == 2 and binding.get("serial_cap") == 1,
            "XMF request must be CPU2 serial1")
    require(binding.get("case_credit") == 0 and binding.get("independent_case_count_increment") == 0,
            "XMF request cannot grant case credit")
    require(binding.get("future_outputs") and all(value is None for value in binding["future_outputs"].values()),
            "future XMF outputs must remain null")
    _verify_metadata_closure(binding)

    _, original = _metadata_ref(_role_path(binding, "original_conversion_receipt"),
                                label="original_conversion_receipt")
    _, audit_receipt = _metadata_ref(_role_path(binding, "artifact_audit_receipt"),
                                     label="artifact_audit_receipt")
    _, audit_report = _metadata_ref(_role_path(binding, "artifact_audit_report"),
                                    label="artifact_audit_report")
    _, native = _metadata_ref(_role_path(binding, "native_receipt"), label="native_receipt")
    _, conversion = _metadata_ref(_role_path(binding, "conversion_report"),
                                  label="conversion_report")
    _, typed_request = _metadata_ref(_role_path(binding, "original_typed_request"),
                                     label="original_typed_request")

    # The old converter lifecycle is preserved exactly.  In particular, the
    # absent returncode is meaningful and cannot be inferred from the audit.
    require(original.get("status") == "running", "original conversion status changed")
    require("returncode" not in original, "original conversion receipt was rewritten")
    old_req = original.get("request", {})
    require(old_req.get("attempt_id") == binding["original_attempt_id"],
            "original conversion attempt identity changed")
    require(original.get("output_root") == binding["original_output_root"],
            "original conversion output root changed")

    require(audit_receipt.get("status") == "completed" and audit_receipt.get("returncode") == 0,
            "artifact audit is not completed/0")
    require(audit_report.get("artifact_integrity_status") == "completed",
            "artifact audit report is not complete")
    require(audit_report.get("worker_returncode") == 0, "artifact audit worker did not return 0")
    audit_scope = audit_report.get("audit_scope", {})
    _all_true(audit_scope, ("h5_hashed_by_root_worker", "h5_read_by_root_worker"), "audit_scope")
    require(audit_scope.get("arrays_decoded_by_source_agent") is False,
            "audit source-agent boundary changed")
    require(audit_scope.get("source_arrays_modified") is False,
            "audit reports source-array modification")
    field = audit_report.get("field_audit", {})
    _all_true(field, ("finite_position_velocity_density_pressure_mass", "n3_shape_verified",
                      "report_frame_ledger_verified", "time_axis_verified_against_report",
                      "type_mk_verified_all_frames", "uid_composite_unique",
                      ), "field_audit")
    require(field.get("source_arrays_modified") is False,
            "field_audit reports source-array modification")
    require(field.get("uid_lifecycle_missing_count") == 0, "audit reports missing UID lifecycle")
    require(field.get("frames") == binding["expected_frames"] and
            field.get("particles") == binding["expected_particles"],
            "audit frame/particle counts differ")
    producer = audit_report.get("producer_attestation", {})
    require(producer.get("verified_trajectory_sha256") == binding["expected_h5_sha256"],
            "audit H5 attestation differs")
    require(producer.get("conversion_report_sha256") == binding["conversion_report"]["sha256"],
            "audit conversion-report attestation differs")
    lifecycle = audit_report.get("source_conversion_lifecycle", {})
    require(lifecycle.get("attempt_id") == binding["original_attempt_id"],
            "audit lifecycle points at another conversion attempt")
    require(lifecycle.get("receipt_status") == "running" and lifecycle.get("receipt_returncode") is None,
            "audit did not preserve the unresolved original lifecycle")
    require(lifecycle.get("source_receipt_edited") is False and
            lifecycle.get("source_conversion_reclassified") is False,
            "audit reclassified or edited the old conversion")

    require(native.get("status") == "completed" and native.get("returncode") == 0,
            "native receipt is not completed/0")
    native_req = native.get("request", {})
    require(native_req.get("case_id") == binding["case_id"] and
            native_req.get("physical_case_id") == binding["physical_case_id"],
            "native identity differs")
    require(native_req.get("physical_condition_sha256") == binding["canonical_source_physical_condition_sha256"],
            "native canonical scope differs")

    require(conversion.get("conversion_status") == "completed", "conversion report is not complete")
    require(conversion.get("frames") == binding["expected_frames"] and
            conversion.get("particles") == binding["expected_particles"],
            "conversion report counts differ")
    require(conversion.get("output_hdf5") == binding["trajectory_h5"],
            "conversion report H5 path differs")
    require(conversion.get("output_sha256") == binding["expected_h5_sha256"],
            "conversion report H5 attestation differs")
    require(conversion.get("partvtk_validation", {}).get("all_passed") is True,
            "conversion PartVTK metadata is not passed")
    report_scope = conversion.get("hash_scopes", {}).get("physical_condition", {})
    require(conversion.get("hash_scopes", {}).get("physical_condition_sha256") ==
            binding["actual_converter_scope_sha256"],
            "legacy converter scope differs")
    require(report_scope.get("schema") == "legacy-owner-scope.v0" and
            report_scope.get("physical_case_id") == binding["physical_case_id"],
            "legacy converter scope semantics differ")

    audit_identity = audit_report.get("physical_identity", {})
    require(audit_identity.get("canonical_native_condition_sha256") ==
            binding["canonical_source_physical_condition_sha256"],
            "audit canonical scope differs")
    require(audit_identity.get("converter_legacy_scope_sha256") ==
            binding["actual_converter_scope_sha256"],
            "audit legacy scope differs")
    require(audit_identity.get("physical_case_id") == binding["physical_case_id"],
            "audit physical identity differs")

    # The original XMF source interface is retained as metadata, but its typed
    # receipt requirement is deliberately replaced by the three explicit roles.
    require("typed_receipt" not in binding, "audit was incorrectly presented as typed_receipt")
    require(binding["original_conversion_receipt"]["path"] != binding["artifact_audit_receipt"]["path"],
            "receipt roles collapsed")
    require(binding["artifact_audit_receipt"]["path"] != binding["native_receipt"]["path"],
            "audit and native receipt roles collapsed")
    require(typed_request.get("attempt_id") == binding["original_attempt_id"],
            "original typed request identity changed")

    return {
        "binding": binding,
        "original_conversion_receipt": original,
        "artifact_audit_receipt": audit_receipt,
        "artifact_audit_report": audit_report,
        "native_receipt": native,
        "conversion_report": conversion,
    }


def _load_verified_exporter(binding: dict[str, Any]):
    source = _file_ref(binding["upstream_export_xmf"], label="upstream export_xmf")
    spec = importlib.util.spec_from_file_location("ds02_fresh104_export_xmf", source)
    require(spec is not None and spec.loader is not None, "cannot load upstream exporter")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    require(tuple(module.FIELDS) == tuple(binding["expected_fields"]),
            "upstream XMF field contract changed")
    require(hasattr(module, "item") and hasattr(module, "sha"),
            "upstream XMF writer contract changed")
    return module


def xmf_metadata_names(fields: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Return the original fresh104 manifest field order, including position."""
    names = ("time", "position", *tuple(fields))
    require(names[0:2] == ("time", "position"),
            "XMF metadata contract must begin with time and position")
    require(tuple(names[2:]) == tuple(fields),
            "XMF metadata field contract changed")
    return names


def build(binding_path: Path, output_dir: Path) -> dict[str, Any]:
    ctx = metadata_preflight(binding_path)
    binding = ctx["binding"]
    exporter = _load_verified_exporter(binding)
    import h5py
    import numpy as np

    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise BindingError(f"refusing to reuse non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    source = _absolute(binding["trajectory_h5"], label="trajectory_h5")
    observed_h5_sha = exporter.sha(source)
    require(observed_h5_sha == binding["expected_h5_sha256"],
            "trajectory H5 differs from Root1166 audit/producer attestation")
    report = ctx["conversion_report"]
    root = ET.Element("Xdmf", Version="2.0")
    domain = ET.SubElement(root, "Domain")
    collection = ET.SubElement(domain, "Grid", Name=binding["physical_case_id"],
                               GridType="Collection", CollectionType="Temporal")
    with h5py.File(source, "r") as handle:
        fields = tuple(binding["expected_fields"])
        require({"time", "position", *fields} <= set(handle),
                "trajectory is missing required XMF fields")
        times = np.asarray(handle["time"][...], dtype=np.float64)
        frames, particles, dimension = handle["position"].shape
        require(frames == report["frames"] == binding["expected_frames"],
                "H5/report frame count differs")
        require(particles == report["particles"] == binding["expected_particles"] and dimension == 3,
                "H5/report dimension or particle count differs")
        require(len(times) == frames and times[0] == 0 and np.all(np.diff(times) > 0),
                "H5 time axis is not strictly increasing")
        require(times[-1] >= binding["physical_window_s"][1],
                "H5 time window is shorter than the preserved recipe")
        metadata_names = xmf_metadata_names(fields)
        require(set(metadata_names) <= set(handle),
                "trajectory is missing an XMF metadata field")
        metadata = {name: {"shape": list(handle[name].shape), "dtype": str(handle[name].dtype)}
                    for name in metadata_names}
        for frame, time in enumerate(times):
            grid = ET.SubElement(collection, "Grid", Name=f"frame_{frame:04d}", GridType="Uniform")
            ET.SubElement(grid, "Time", Value=format(float(time), ".17g"))
            ET.SubElement(grid, "Topology", TopologyType="Polyvertex",
                          NumberOfElements=str(particles))
            geometry = ET.SubElement(grid, "Geometry", GeometryType="XYZ")
            exporter.item(geometry, handle["position"], source, frame, frames, particles)
            for name in fields:
                attribute = ET.SubElement(grid, "Attribute", Name=name, Center="Node",
                                          AttributeType="Vector" if name == "velocity" else "Scalar")
                exporter.item(attribute, handle[name], source, frame, frames, particles)
        # The typed H5 stores the producer's legacy converter scope.  The
        # native canonical scope remains a separate manifest field.
        condition = str(handle.attrs["physical_condition_sha256"])
        require(condition == binding["actual_converter_scope_sha256"],
                "H5 physical condition differs from the legacy converter scope")
    output = output_dir / "case.xmf"
    ET.indent(root)
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
    require(exporter.sha(source) == observed_h5_sha, "source H5 changed while publishing XMF")
    manifest = {
        "schema": "ds02.stage1.paraview-temporal-product.v1",
        "family_id": binding["family_id"],
        "case_id": binding["case_id"],
        "physical_case_id": binding["physical_case_id"],
        "physical_condition_sha256": binding["physical_condition_sha256"],
        "canonical_source_physical_condition_sha256": binding["canonical_source_physical_condition_sha256"],
        "actual_converter_scope_sha256": binding["actual_converter_scope_sha256"],
        "source_plan_scope_sha256": binding["source_plan_scope_sha256"],
        "receipt_roles": {
            "original_conversion_receipt": binding["original_conversion_receipt"],
            "artifact_audit_receipt": binding["artifact_audit_receipt"],
            "native_receipt": binding["native_receipt"],
            "conversion_report": binding["conversion_report"],
        },
        "audit_provenance": {
            "artifact_audit_report": binding["artifact_audit_report"],
            "audit_status": "completed/0 independent audit",
            "original_conversion_status": "running; returncode field absent; preserved",
            "old_typed_receipt_is_not_reclassified": True,
        },
        "xdmf": str(output),
        "xdmf_sha256": exporter.sha(output),
        "source_h5_sha256": observed_h5_sha,
        "source_h5_sha256_matches_root1166_audit": True,
        "fields": metadata,
        "frames": frames,
        "particles": particles,
        "actual_time_s": times.tolist(),
        "coordinate_frame": report["coordinate_frame"],
        "source_h5_read_only": True,
        "relative_or_absolute_paths": "Absolute local immutable HDF5 reference",
        "identity_and_state": "All original stored particles/fields; select valid=1 for active points",
        "visual_status": "pending actual ParaView full-animation review",
        "numerical_precision_status": "not accepted; historical numerical evidence retained",
        "independent_case_increment": 0,
        "case_credit": 0,
        "count_policy": "Derived sidecar for one existing physical condition; Root owns case counting",
        "xmf_shape_contract": binding.get("xmf_shape_contract"),
        "camera_bounds_policy": "Root023 scans all native valid positions across every saved frame; no fixed bounds",
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Open case.xmf in ParaView 6.1.1, Apply, then Play. All original saved frames are included.\n"
        "The original conversion receipt remains unresolved; Root1166 artifact audit and native receipt are separate evidence.\n"
        "The source HDF5 remains immutable and is referenced in place. Visual and numerical acceptance remain pending.\n",
        encoding="utf-8")
    return {"xdmf": str(output), "frames": frames, "particles": particles,
            "artifact_audit_receipt": binding["artifact_audit_receipt"]["path"],
            "original_conversion_receipt": binding["original_conversion_receipt"]["path"],
            "native_receipt": binding["native_receipt"]["path"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--metadata-preflight", action="store_true")
    args = parser.parse_args()
    if args.metadata_preflight:
        ctx = metadata_preflight(args.binding)
        print(json.dumps({"status": "metadata_preflight_pass", "schema": SCHEMA,
                          "case_id": ctx["binding"]["case_id"],
                          "original_conversion_status": ctx["original_conversion_receipt"].get("status"),
                          "artifact_audit_status": ctx["artifact_audit_receipt"].get("status"),
                          "native_status": ctx["native_receipt"].get("status"),
                          "scientific_payload_opened": False}, indent=2), flush=True)
        return
    require(args.output_dir is not None, "--output-dir is required for execution")
    print(json.dumps(build(args.binding, args.output_dir)), flush=True)


if __name__ == "__main__":
    main()
