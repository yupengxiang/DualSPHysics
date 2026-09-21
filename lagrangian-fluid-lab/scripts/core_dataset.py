"""Portable full-axis HDF5 reader and immutable development split import.

Large source trajectories stay in place. A manifest contains only relative
asset paths; deployment chooses data_root explicitly. Qualification is copied
as a scoped source claim and is never inferred from successful file reads.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import tempfile

import h5py
import numpy as np

from scripts.core_contract import (FiniteGeometry, KnownInputs, PrescribedControl,
                                   PrescribedGeometry,
                                   State, StepPrediction, contract_hash, updater_oracle)

SCHEMA = "core.dataset.v1"
COMPACT_SCHEMA = "core.dataset.v2"
SUPPORTED_SCHEMAS = {SCHEMA, COMPACT_SCHEMA}
SPLITS = {"train", "validation", "test", "id_test", "ood_test", "qualification"}


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _validate_binary_valid_dataset(dataset):
    """Validate the raw lifecycle mask without materializing the full axis.

    ``read_state`` converts the source values to bool for the public State
    object.  That conversion must happen only after the source contract has
    established that the values really are binary; otherwise values such as
    ``2`` or ``0.5`` silently become active particles.
    """
    if dataset.dtype.kind not in "biu":
        raise ValueError("invalid valid dtype")
    if len(dataset.shape) != 2:
        raise ValueError("invalid validity axis")
    chunk = dataset.chunks[0] if dataset.chunks else 1024
    chunk = max(1, int(chunk))
    for start in range(0, dataset.shape[0], chunk):
        values = np.asarray(dataset[start:start + chunk])
        if not np.isin(values, (0, 1)).all():
            raise ValueError("invalid binary valid mask")


def _asset(root, value):
    path = Path(value)
    if path.is_absolute():
        raise ValueError("dataset assets must be relative to explicit data_root")
    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError as error:
        raise ValueError("asset escapes data_root") from error
    if not target.is_file():
        raise FileNotFoundError(target)
    return target


def _portable_asset_ref(value, *, name="asset"):
    """Validate a content-addressed relative asset reference without I/O."""
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise ValueError(f"{name} requires a relative path reference")
    path = Path(value["path"])
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{name} path is not portable")
    digest = value.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
        raise ValueError(f"{name} requires a SHA-256 reference")
    return value


def validate_manifest(manifest):
    if manifest.get("schema") not in SUPPORTED_SCHEMAS or not isinstance(manifest.get("cases"), list):
        raise ValueError("unsupported core dataset manifest")
    identities, physical, lineages = set(), {}, {}
    for row in manifest["cases"]:
        for key in ("case_id", "physical_case_id", "lineage_group_id", "family", "split",
                    "hdf5", "sha256", "known_inputs_sha256"):
            if not row.get(key):
                raise ValueError(f"missing case field {key}")
        if manifest["schema"] == SCHEMA and not row.get("known_inputs"):
            raise ValueError("missing case field known_inputs")
        if manifest["schema"] == COMPACT_SCHEMA and not row.get("known_inputs_ref"):
            raise ValueError("missing case field known_inputs_ref")
        if row["split"] not in SPLITS:
            raise ValueError("unsupported split")
        if row["case_id"] in identities:
            raise ValueError("duplicate case identity")
        # Multiple resolutions/crops may be views of one physical case, but
        # every view must stay in the same split.  Retaining the physical key
        # here prevents an adapter from hiding a train/validation leak by
        # inventing a per-view identity.
        prior_physical = physical.setdefault(row["physical_case_id"], row["split"])
        if prior_physical != row["split"]:
            raise ValueError("a physical case crosses splits")
        identities.add(row["case_id"])
        prior = lineages.setdefault(row["lineage_group_id"], row["split"])
        if prior != row["split"]:
            raise ValueError("a physical lineage crosses splits")
        if row.get("qualification_case", False) != (row["split"] == "qualification"):
            raise ValueError("qualification cases cannot enter development splits")
        if Path(row["hdf5"]).is_absolute() or ".." in Path(row["hdf5"]).parts:
            raise ValueError("nonportable HDF5 asset path")
        if manifest["schema"] == SCHEMA:
            known = known_inputs_from_dict(row["known_inputs"])
            if contract_hash(known) != row["known_inputs_sha256"]:
                raise ValueError("known input contract hash mismatch")
        else:
            references = row["known_inputs_ref"]
            for key in ("geometry", "control"):
                _portable_asset_ref(references.get(key), name=f"known_inputs_ref.{key}")
            for key in ("physics", "numerics", "coordinate_frame"):
                if key not in references:
                    raise ValueError(f"missing known input metadata {key}")
    if not identities:
        raise ValueError("empty dataset")
    return manifest


def known_inputs_from_dict(payload):
    geometry_payload = payload["geometry"]
    if geometry_payload.get("version") == "core.prescribed_geometry.v1":
        motion = geometry_payload.get("prescribed_motion")
        if not isinstance(motion, dict):
            raise ValueError("prescribed geometry requires declared prescribed_motion metadata")
        geometry = PrescribedGeometry(
            triangles=geometry_payload["triangles"],
            component_id=geometry_payload["component_id"],
            body_id=geometry_payload["body_id"],
            wall_velocity=geometry_payload["wall_velocity"],
            coordinate_frame=geometry_payload["coordinate_frame"],
            sample_times=motion["time_s"],
            sample_angles_degrees=motion["angle_degrees"],
            axis_point=motion["axis_point"],
            axis_direction=motion["axis_direction"],
            moving_body_id=motion.get("moving_body_id", 0),
            version=geometry_payload.get("version", "core.prescribed_geometry.v1"),
            motion_version=motion.get("version", "core.prescribed_rotation.v1"),
            motion_sha256=motion.get("sha256", ""),
        )
    else:
        geometry = FiniteGeometry(**geometry_payload)
    return KnownInputs(geometry, PrescribedControl(**payload["control"]),
                       payload["physics"], payload["numerics"], payload["coordinate_frame"],
                       payload.get("contract_version", "core.inputs.v1"))


def _write_npz_asset(path, *, arrays, metadata):
    """Write a compressed numeric asset once and return its content hash."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return sha256_file(path)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temporary = Path(temporary)
    try:
        np.savez_compressed(temporary, **arrays, metadata=np.asarray(json.dumps(metadata, sort_keys=True)))
        # numpy appends .npz when the temporary name does not have that suffix.
        generated = temporary.with_suffix(temporary.suffix + ".npz")
        if not generated.exists():
            generated = temporary
        os.replace(generated, path)
    finally:
        if temporary.exists():
            temporary.unlink()
        generated = temporary.with_suffix(temporary.suffix + ".npz")
        if generated.exists():
            generated.unlink()
    return sha256_file(path)


def _load_npz_asset(root, reference, *, kind):
    path = _asset(root, reference["path"])
    observed = sha256_file(path)
    if observed != reference["sha256"]:
        raise ValueError(f"{kind} asset hash mismatch: {reference['path']}")
    try:
        with np.load(path, allow_pickle=False) as archive:
            metadata = json.loads(str(np.asarray(archive["metadata"]).item()))
            if metadata.get("kind") != kind:
                raise ValueError(f"unexpected {kind} asset kind")
            if kind == "geometry":
                if metadata.get("version") == "core.prescribed_geometry.v1":
                    return PrescribedGeometry(
                        archive["triangles"], archive["component_id"], archive["body_id"],
                        archive["wall_velocity"], metadata["coordinate_frame"],
                        archive["sample_times"], archive["sample_angles_degrees"],
                        metadata["axis_point"], metadata["axis_direction"],
                        metadata.get("moving_body_id", 0),
                        metadata["version"], metadata.get("motion_version", "core.prescribed_rotation.v1"),
                        metadata.get("motion_sha256", ""))
                return FiniteGeometry(archive["triangles"], archive["component_id"], archive["body_id"],
                                      archive["wall_velocity"], metadata["coordinate_frame"])
            if kind == "control":
                return PrescribedControl(
                    archive["samples"],
                    tuple(metadata.get("centre", (.45, 0.0, 0.0))),
                    metadata.get("semantics", "dualsphysics_f3_accinput_v1"),
                )
    except (KeyError, OSError, ValueError) as error:
        raise ValueError(f"invalid {kind} asset: {reference['path']}") from error
    raise ValueError(f"unknown compact input asset kind {kind}")


def known_inputs_from_record(row, data_root):
    """Resolve either inline v1 inputs or hashed compact v2 inputs."""
    if row.get("known_inputs") is not None:
        return known_inputs_from_dict(row["known_inputs"])
    references = row["known_inputs_ref"]
    geometry = _load_npz_asset(data_root, references["geometry"], kind="geometry")
    control = _load_npz_asset(data_root, references["control"], kind="control")
    return KnownInputs(geometry, control, references["physics"], references["numerics"],
                       references["coordinate_frame"], references.get("contract_version", "core.inputs.v1"))


def compactify_manifest(source_manifest, data_root, *, asset_dir=None,
                        output_manifest=None, formal_release=None):
    """Materialize a v1 reader manifest as a portable v2 manifest.

    This operation is intentionally limited to the JSON known-input contract.
    It opens no trajectory files, reads no future state and never changes a
    registry or qualification record.  Geometry and control arrays are stored
    once per distinct content hash under ``data_root``; every case retains its
    original HDF5 path, byte count, trajectory hash and input-contract hash.
    """
    root = Path(data_root).expanduser().resolve()
    source_path = Path(source_manifest).expanduser().resolve()
    source = json.loads(source_path.read_text())
    if source.get("schema") != SCHEMA:
        raise ValueError("compactify_manifest expects a core.dataset.v1 source")
    validate_manifest(source)
    asset_root = (root / (asset_dir or "campaigns/core-v1/assets/core-inputs-v2")).resolve()
    try:
        asset_root.relative_to(root)
    except ValueError as error:
        raise ValueError("compact input assets must remain under data_root") from error

    def asset_reference(kind, payload, arrays, metadata):
        identity = _canonical_hash({"kind": kind, "metadata": metadata,
                                    "arrays": {key: np.asarray(value).tolist()
                                               for key, value in arrays.items()}})
        path = asset_root / f"{kind}-{identity}.npz"
        observed = _write_npz_asset(path, arrays=arrays,
                                     metadata={"kind": kind, **metadata})
        return {"path": str(path.relative_to(root)), "sha256": observed,
                "bytes": path.stat().st_size, "format": "npz",
                "version": str(metadata.get("version", "core.input_asset.v1"))}

    geometry_cache, control_cache = {}, {}
    compact_cases = []
    for row in source["cases"]:
        known = known_inputs_from_dict(row["known_inputs"])
        if contract_hash(known) != row["known_inputs_sha256"]:
            raise ValueError(f"known input contract hash mismatch: {row['case_id']}")
        geometry_dict = known.geometry.as_dict()
        geometry_key = _canonical_hash(geometry_dict)
        if geometry_key not in geometry_cache:
            geometry_arrays = {
                "triangles": known.geometry.triangles,
                "component_id": known.geometry.component_id,
                "body_id": known.geometry.body_id,
                "wall_velocity": known.geometry.wall_velocity,
            }
            geometry_metadata = {
                "version": known.geometry.version,
                "coordinate_frame": known.geometry.coordinate_frame,
            }
            if isinstance(known.geometry, PrescribedGeometry):
                geometry_arrays.update({
                    "sample_times": known.geometry.sample_times,
                    "sample_angles_degrees": known.geometry.sample_angles_degrees,
                })
                geometry_metadata.update({
                    "axis_point": known.geometry.axis_point.tolist(),
                    "axis_direction": known.geometry.axis_direction.tolist(),
                    "moving_body_id": known.geometry.moving_body_id,
                    "motion_version": known.geometry.motion_version,
                    "motion_sha256": known.geometry.motion_sha256,
                })
            geometry_cache[geometry_key] = asset_reference(
                "geometry", geometry_dict, geometry_arrays, geometry_metadata)

        control_dict = known.control.as_dict()
        control_key = _canonical_hash(control_dict)
        if control_key not in control_cache:
            control_cache[control_key] = asset_reference(
                "control", control_dict, {"samples": known.control.samples}, {
                    "version": "core.input_asset.v1",
                    "centre": list(known.control.centre),
                    "semantics": known.control.semantics,
                })

        compact = {key: value for key, value in row.items() if key != "known_inputs"}
        compact["known_inputs_ref"] = {
            "geometry": geometry_cache[geometry_key],
            "control": control_cache[control_key],
            "physics": dict(known.physics),
            "numerics": dict(known.numerics),
            "coordinate_frame": known.coordinate_frame,
            "contract_version": known.contract_version,
        }
        compact_cases.append(compact)

    result = {key: value for key, value in source.items() if key != "cases"}
    result.update({
        "schema": COMPACT_SCHEMA,
        "source_schema": SCHEMA,
        "source_manifest_sha256": sha256_file(source_path),
        "dataset_id": f"{source.get('dataset_id', 'core-dataset')}_compact_v2",
        "formal_release": source.get("formal_release", False)
        if formal_release is None else bool(formal_release),
        "input_asset_policy": "content_addressed_compressed_npz",
        "cases": compact_cases,
    })
    validate_manifest(result)
    if output_manifest is not None:
        target = Path(output_manifest).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".partial")
        temporary.write_text(json.dumps(result, indent=2, sort_keys=True,
                                        allow_nan=False) + "\n")
        os.replace(temporary, target)
    return result


def import_f3_manifest(source_manifest, data_root, *, compact=False, asset_dir=None):
    """Read registered 32-case metadata without rewriting native HDF5.

    ``compact=True`` stores finite geometry and control arrays once each in
    content-addressed compressed NPZ assets and places only relative hashed
    references in the manifest. The default v1 form remains available for
    backwards-compatible diagnostic comparisons.
    """
    root = Path(data_root).expanduser().resolve()
    source_path = Path(source_manifest).resolve()
    source = json.loads(source_path.read_text())
    if source.get("schema") != "l2.f3.canonical_manifest.v1":
        raise ValueError("expected registered F3 canonical manifest")
    result_schema = COMPACT_SCHEMA if compact else SCHEMA
    result = {"schema": result_schema,
              "dataset_id": "F3_registered32_core_native_v2" if compact else "F3_registered32_core_native_v1",
              "formal_release": False, "source_manifest_sha256": sha256_file(source_path),
              "source_qualification_claims": source.get("qualification_axes", {}),
              "case_count": len(source["cases"]), "cases": [],
              "input_asset_policy": "content_addressed_compressed_npz" if compact else "inline"}
    asset_root = (root / (asset_dir or "campaigns/core-v1/assets/core-inputs-v2")).resolve()
    try:
        asset_root.relative_to(root)
    except ValueError as error:
        raise ValueError("compact input assets must remain under data_root") from error
    geometry_cache, control_cache = {}, {}
    for row in source["cases"]:
        evidence = row["source_evidence"]
        prepared_path = _asset(root, evidence["prepared"]["path"])
        control_path = _asset(root, evidence["control"]["path"])
        for path, record in ((prepared_path, evidence["prepared"]), (control_path, evidence["control"])):
            if sha256_file(path) != record["sha256"]:
                raise ValueError(f"changed registered metadata/control: {path}")
        prepared = json.loads(prepared_path.read_text())
        trajectory = _asset(root, row["hdf5"])
        if trajectory.stat().st_size != row["file"]["bytes"]:
            raise ValueError("registered HDF5 byte count changed; full hash verification required")
        frame = source["recipe"]["coordinate_frame"]
        geometry = FiniteGeometry.from_wall_spec(prepared["wall_spec"], coordinate_frame=frame)
        controls = np.loadtxt(control_path, delimiter=";", comments="#")
        dp = float(prepared["dp_m"])
        known = KnownInputs(geometry, PrescribedControl(controls),
                            {"gravity_mps2": [0., 0., -9.81], "reference_density_kgm3": 1000.,
                             "drive_amplitude": row["drive_amplitude"]},
                            {"dp_m": dp, "h_m": .91924 * np.sqrt(3.) * dp,
                             "recipe_id": row["recipe_id"], "native_velocity_correction": True,
                             "viscosity_coefficient": source["recipe"]["visco"]}, frame)
        compact_refs = None
        if compact:
            geometry_key = (evidence["prepared"]["path"], frame)
            control_key = evidence["control"]["path"]
            if geometry_key not in geometry_cache:
                geometry_payload = {
                    "triangles": geometry.triangles,
                    "component_id": geometry.component_id,
                    "body_id": geometry.body_id,
                    "wall_velocity": geometry.wall_velocity,
                }
                geometry_name = "geometry-" + hashlib.sha256(
                    json.dumps(geometry.as_dict(), sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest() + ".npz"
                geometry_path = asset_root / geometry_name
                geometry_hash = _write_npz_asset(
                    geometry_path, arrays=geometry_payload,
                    metadata={"kind": "geometry", "coordinate_frame": frame, "version": "core.input_asset.v1"})
                geometry_cache[geometry_key] = {
                    "path": str(geometry_path.relative_to(root)), "sha256": geometry_hash,
                    "format": "npz", "version": "core.input_asset.v1",
                }
            if control_key not in control_cache:
                control_name = "control-" + hashlib.sha256(controls.tobytes()).hexdigest() + ".npz"
                control_path_asset = asset_root / control_name
                control_hash = _write_npz_asset(
                    control_path_asset, arrays={"samples": controls},
                    metadata={"kind": "control", "version": "core.input_asset.v1"})
                control_cache[control_key] = {
                    "path": str(control_path_asset.relative_to(root)), "sha256": control_hash,
                    "format": "npz", "version": "core.input_asset.v1",
                }
            compact_refs = {"geometry": geometry_cache[geometry_key], "control": control_cache[control_key],
                            "physics": dict(known.physics), "numerics": dict(known.numerics),
                            "coordinate_frame": frame, "contract_version": known.contract_version}
        case = {"case_id": row["case_id"], "physical_case_id": row["physical_case_id"],
            "lineage_group_id": row["lineage_group_id"], "family": row["family"],
            "scope_id": row["recipe_id"], "split": row["split"], "evaluation_role": row["evaluation_role"],
            "hdf5": row["hdf5"], "sha256": row["file"]["sha256"], "bytes": row["file"]["bytes"],
            "qualification_case": False,
            "known_inputs_sha256": contract_hash(known),
            "provenance": {"prepared": evidence["prepared"], "control": evidence["control"],
                           "audit": evidence["audit"]},
            "semantics": {"velocity": "native saved numerical velocity", "position": "native saved numerical position",
                          "identity": "particle_zone,particle_id", "units": "SI",
                          "native_hdf5_rewritten": False, "material_path_qualification": False}}
        if compact:
            case["known_inputs_ref"] = compact_refs
        else:
            case["known_inputs"] = known.as_dict()
        result["cases"].append(case)
    validate_manifest(result)
    return result


def new_scope_split(parameter_min, parameter_max):
    """Frozen 16/4/6/6 design within a separately qualified scalar domain."""
    if not np.isfinite([parameter_min, parameter_max]).all() or parameter_min >= parameter_max:
        raise ValueError("a qualified nonempty scalar interval is required")
    validation = {8, 13, 18, 23}; id_test = {5, 9, 14, 17, 22, 26}; ood = {0, 1, 2, 29, 30, 31}
    return [{"index": i, "parameter": parameter_min + (i + .5) * (parameter_max - parameter_min) / 32,
             "split": "validation" if i in validation else "id_test" if i in id_test else "ood_test" if i in ood else "train"}
            for i in range(32)]


class CoreDataset:
    def __init__(self, manifest, data_root=None, *, max_open_files=4):
        if isinstance(manifest, (str, Path)):
            path = Path(manifest).expanduser().resolve()
            payload = json.loads(path.read_text())
            root = Path(data_root).expanduser().resolve() if data_root is not None else path.parent
        else:
            if not isinstance(manifest, dict):
                raise ValueError("manifest must be a mapping or JSON path")
            # Keep the caller's arrays out of a second JSON serialization. The
            # validator is read-only; copying the case list is enough to keep
            # the record index stable while allowing compact v2 manifests to
            # remain small in memory.
            payload = dict(manifest)
            payload["cases"] = list(manifest["cases"])
            if data_root is None:
                raise ValueError("an in-memory manifest requires explicit data_root")
            root = Path(data_root).expanduser().resolve()
        self.manifest = validate_manifest(payload)
        self.manifest_sha256 = _canonical_hash(payload)
        self.data_root = root
        self._records = {row["case_id"]: row for row in payload["cases"]}
        if not isinstance(max_open_files, int) or max_open_files < 1:
            raise ValueError("positive open-file bound required")
        self.max_open_files = max_open_files
        self._handles = OrderedDict(); self._known = {}; self._mass_reference = {}; self.read_log = []

    def case_ids(self, split=None):
        return tuple(key for key, row in self._records.items() if split is None or row["split"] == split)

    def record(self, case_id):
        return json.loads(json.dumps(self._records[case_id]))

    def _handle(self, case_id):
        if case_id in self._handles:
            self._handles.move_to_end(case_id)
            return self._handles[case_id]
        row = self._records[case_id]
        path = _asset(self.data_root, row["hdf5"])
        if row.get("bytes") and path.stat().st_size != row["bytes"]:
            raise ValueError("source HDF5 size mismatch")
        handle = h5py.File(path, "r")
        required = {"time", "position", "velocity", "particle_id", "particle_zone", "mass", "valid"}
        try:
            if not required <= set(handle):
                raise ValueError("missing native HDF5 fields")
            time = np.asarray(handle["time"])
            n = len(handle["particle_id"])
            if not len(time) >= 2 or not np.isfinite(time).all() or np.any(np.diff(time) <= 0):
                raise ValueError("invalid native time axis")
            if any(handle[key].shape != (len(time), n, 3) for key in ("position", "velocity")):
                raise ValueError("invalid full particle axis")
            if handle["valid"].shape != (len(time), n) or handle["particle_zone"].shape != (n,):
                raise ValueError("invalid validity or zone axis")
            _validate_binary_valid_dataset(handle["valid"])
            if handle["mass"].shape not in ((n,), (len(time), n)):
                raise ValueError("invalid mass shape")
        except BaseException:
            handle.close(); raise
        while len(self._handles) >= self.max_open_files:
            _, oldest = self._handles.popitem(last=False); oldest.close()
        self._handles[case_id] = handle
        return handle

    def verify_sources(self, case_ids=None):
        result = {}
        for case_id in self.case_ids() if case_ids is None else case_ids:
            row = self._records[case_id]
            observed = sha256_file(_asset(self.data_root, row["hdf5"]))
            if observed != row["sha256"]:
                raise ValueError(f"HDF5 hash mismatch: {case_id}")
            result[case_id] = observed
            if row.get("known_inputs_ref"):
                for key, reference in row["known_inputs_ref"].items():
                    if key not in ("geometry", "control"):
                        continue
                    input_path = _asset(self.data_root, reference["path"])
                    input_hash = sha256_file(input_path)
                    if input_hash != reference["sha256"]:
                        raise ValueError(f"input asset hash mismatch: {case_id}/{key}")
        return result

    def times(self, case_id):
        result = np.array(self._handle(case_id)["time"], dtype=float)
        result.setflags(write=False)
        return result

    def known_inputs(self, case_id):
        if case_id not in self._known:
            self._known[case_id] = known_inputs_from_record(self._records[case_id], self.data_root)
            if contract_hash(self._known[case_id]) != self._records[case_id]["known_inputs_sha256"]:
                raise ValueError("known input contract hash mismatch")
        return self._known[case_id]

    def read_state(self, case_id, frame):
        handle = self._handle(case_id)
        if isinstance(frame, bool) or not isinstance(frame, (int, np.integer)) or not 0 <= frame < len(handle["time"]):
            raise ValueError("frame outside native source")
        mass = handle["mass"][:] if handle["mass"].ndim == 1 else handle["mass"][frame]
        if case_id not in self._mass_reference:
            # Bind mass to the immutable particle identity axis at frame zero.
            # Native solvers may leave an invalid particle's later payload as
            # NaN; the public State still carries this initial axis so an
            # invalid row cannot silently change the identity/mass contract.
            reference = handle["mass"][:] if handle["mass"].ndim == 1 else handle["mass"][0]
            self._mass_reference[case_id] = np.array(reference, dtype=np.float64, copy=True)
        initial_mass = self._mass_reference[case_id]
        valid = np.asarray(handle["valid"][frame], dtype=bool)
        current_mass = np.asarray(mass, dtype=np.float64)
        # Only active particles participate in the native mass invariant.
        # Inactive payloads are outside the state update contract and may be
        # NaN, but the returned State uses the initial mass axis for every ID.
        if valid.any():
            if (not np.isfinite(current_mass[valid]).all()
                    or not np.isfinite(initial_mass[valid]).all()
                    or not np.array_equal(current_mass[valid], initial_mass[valid])):
                raise ValueError("changed active particle masses require another lifecycle contract")
        state = State(float(handle["time"][frame]), handle["position"][frame], handle["velocity"][frame],
                      handle["particle_id"][:], handle["particle_zone"][:], initial_mass, valid)
        self.read_log.append((case_id, int(frame)))
        return state

    def training_transition(self, case_id, frame):
        if self._records[case_id]["split"] != "train":
            raise ValueError("optimization/normalization may read train cases only")
        return self.supervised_transition(case_id, frame)

    def supervised_transition(self, case_id, frame):
        """Reference boundary for training/scoring; never give this object to a predictor."""
        now, following = self.read_state(case_id, frame), self.read_state(case_id, frame + 1)
        if not np.array_equal(now.valid, following.valid) or not now.valid.all():
            raise ValueError("closed-system learning requires complete persistent identities")
        return now, self.known_inputs(case_id), following.time_s - now.time_s, StepPrediction(
            following.position - now.position, following.velocity - now.velocity)

    def oracle(self, case_id, frame=0):
        return updater_oracle(self.read_state(case_id, frame), self.read_state(case_id, frame + 1))

    def close(self):
        for handle in self._handles.values():
            handle.close()
        self._handles.clear()
        self._mass_reference.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
