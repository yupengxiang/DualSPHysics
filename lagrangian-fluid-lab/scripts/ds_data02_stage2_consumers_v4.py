#!/usr/bin/env python3
"""Strict, portable consumers for the DS-DATA-02 Stage 2 catalog.

The Stage 1 label/audit scripts are historical producers.  They may discover a
``trajectory.h5`` by sorting a glob, select a fixed list of cases, or fall back
to an arbitrary ``Run.out``.  This module intentionally has none of those
behaviours.  Every read starts from an immutable ``CURRENT336.json`` row and
every produced label keeps the catalog, case-row, source, identity, operator,
and quality-status bindings beside the data.

The observation labels are deliberately scoped.  They describe saved-frame
identity histories, interval-bounded first passage, piecewise-linear residence,
and explicitly moving axis-aligned planes.  A label is useful without a model,
but it never grants Q-I, Q-N, or Q-E qualification by itself.

The v4 evaluator consumes a label sidecar and a separately authored analytic
expectation bundle.  It is an operator replay check for manufactured data only;
it refuses unqualified scientific subdomains and never turns a passing replay
into a scientific or numerical qualification.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence
import xml.etree.ElementTree as ET

import h5py
import numpy as np


CURRENT_SCHEMA = "ds02.stage2.current336.v1"
TRAJECTORY_SCHEMA = "ds-data-02.hdf5-schema.v1"
LABEL_SCHEMA = "ds02.stage2.observation-labels.v2"
SPLIT_SCHEMA = "ds02.stage2.prospective-split.v1"
SENTINEL_SCHEMA = "ds02.stage2.sentinel-observation-plan.v1"
EVALUATOR_SCHEMA = "ds02.stage2.model-free-operator-evaluation.v1"
EVALUATOR_TOLERANCE_PROFILE = {
    "schema": "ds02.stage2.manufactured-tolerance.v1",
    "absolute": 1e-6,
    "relative": 1e-8,
    "nan_equal": True,
}
LABEL_WORKING_SET_BOUND_BYTES = 256 * 1024 ** 2

TYPE_FIXED = 0
TYPE_MOVING = 1
TYPE_FLOATING = 2
TYPE_FLUID = 3
KNOWN_TYPES = {TYPE_FIXED, TYPE_MOVING, TYPE_FLOATING, TYPE_FLUID}

STATIC_FIELDS = ("particle_id", "particle_zone", "initial_type", "initial_mass", "initial_mk")
FRAME_FIELDS = ("time", "valid", "type", "mk", "position", "velocity", "density", "mass", "pressure")
REQUIRED_FIELDS = set(STATIC_FIELDS) | set(FRAME_FIELDS)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class BindingError(ValueError):
    """A catalog, source, identity, or operator binding is not trustworthy."""


class LifecycleError(BindingError):
    """A fixed-axis label encountered unsupported births, revival, or mass changes."""


def _alias_evidence(row: Mapping[str, Any]) -> Any:
    """Return preserved alias provenance under either catalog spelling."""
    evidence = row.get("accepted_alias_evidence")
    return evidence if evidence is not None else row.get("accepted_alias_provenance")


def is_accepted_alias_row(row: Mapping[str, Any]) -> bool:
    """Identify aliases by distinct IDs plus explicit preserved provenance.

    A complete CURRENT rebuild may populate ``manifest_physical_case_id`` on
    every row.  Presence of that field is therefore insufficient: equal IDs
    remain canonical, including the explicit equal-ID counterexample used by
    the v2 tests.
    """
    physical = row.get("physical_case_id")
    manifest = row.get("manifest_physical_case_id")
    return (isinstance(physical, str) and isinstance(manifest, str)
            and manifest != physical and isinstance(_alias_evidence(row), Mapping))


def sha256(path: Path | str) -> str:
    """Hash a file in bounded memory."""
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _json_no_nan(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant {value!r} is not permitted")


def read_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=_json_no_nan)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, np.generic):
        value = value.item()
    return str(value)


def _finite_vector(value: Any, length: int, name: str) -> np.ndarray:
    result = np.asarray(value, dtype="float64")
    if result.shape != (length,) or not np.isfinite(result).all():
        raise BindingError(f"{name} must be a finite vector of length {length}")
    return result


def _finite_bounds(value: Any, name: str) -> np.ndarray:
    result = np.asarray(value, dtype="float64")
    if result.shape != (3, 2) or not np.isfinite(result).all() or not (result[:, 1] > result[:, 0]).all():
        raise BindingError(f"{name} must be a finite nonempty 3D box")
    return result


def _same_file_stat(path: Path, expected: Mapping[str, Any], label: str) -> None:
    if not path.is_file():
        raise BindingError(f"{label} is unavailable: {path}")
    stat = path.stat()
    if "bytes" in expected and int(expected["bytes"]) != stat.st_size:
        raise BindingError(f"{label} byte count differs from CURRENT: {path}")
    if "mtime_ns" in expected and int(expected["mtime_ns"]) != stat.st_mtime_ns:
        raise BindingError(f"{label} mtime differs from CURRENT: {path}")


class PathMapper:
    """Resolve absolute paths stored in a catalog after moving a data bundle.

    Mapping is longest-prefix first and never searches a directory.  This is
    what makes a catalog portable while retaining strict byte/hash bindings.
    """

    def __init__(self, base: Path, path_map: Mapping[str, str] | None = None):
        self.base = base.resolve()
        pairs = []
        for source, destination in (path_map or {}).items():
            pairs.append((Path(source).expanduser().resolve(), Path(destination).expanduser().resolve()))
        self.pairs = tuple(sorted(pairs, key=lambda pair: len(str(pair[0])), reverse=True))

    def resolve(self, raw: str | Path) -> Path:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = self.base / path
        path = path.resolve()
        for source, destination in self.pairs:
            try:
                relative = path.relative_to(source)
            except ValueError:
                continue
            return (destination / relative).resolve()
        return path


@dataclass(frozen=True)
class CurrentCase:
    catalog: "Current336Catalog"
    row: Mapping[str, Any]

    @property
    def physical_case_id(self) -> str:
        return str(self.row["physical_case_id"])

    @property
    def family_id(self) -> str:
        return str(self.row["family_id"])

    @property
    def row_sha256(self) -> str:
        return canonical_sha256(self.row)

    @property
    def is_accepted_alias(self) -> bool:
        return is_accepted_alias_row(self.row)

    @property
    def accepted_alias_evidence(self) -> Mapping[str, Any] | None:
        evidence = _alias_evidence(self.row)
        return evidence if isinstance(evidence, Mapping) else None

    def path(self, spec: Mapping[str, Any] | str | Path) -> Path:
        raw = spec if isinstance(spec, (str, Path)) else spec.get("path")
        if not raw:
            raise BindingError(f"{self.physical_case_id}: missing bound path")
        return self.catalog.mapper.resolve(str(raw))

    def trajectory_path(self) -> Path:
        return self.path(self.row["trajectory"])

    def _check_small_binding(self, name: str, spec: Mapping[str, Any]) -> dict[str, Any]:
        path = self.path(spec)
        if not path.is_file():
            raise BindingError(f"{self.physical_case_id}: {name} is unavailable: {path}")
        expected = spec.get("recomputed_sha256") or spec.get("sha256")
        actual = sha256(path)
        if expected and actual != expected:
            raise BindingError(f"{self.physical_case_id}: {name} hash differs from CURRENT")
        return {"path": str(path), "sha256": actual}

    def inspect(self, *, verify_source_hash: bool = False) -> dict[str, Any]:
        """Verify the selected CURRENT row and HDF5 header without scanning frames."""
        trajectory = self.trajectory_path()
        _same_file_stat(trajectory, self.row["trajectory"], "trajectory")

        # These are small source anchors.  Verifying them prevents a migrated
        # bundle from silently pairing a trajectory with another recipe.
        small_bindings = {}
        manifest_identity = None
        for name in ("manifest", "xmf", "conversion_report"):
            spec = self.row.get(name)
            if isinstance(spec, Mapping):
                small_bindings[name] = self._check_small_binding(name, spec)
                if name == "manifest":
                    manifest_path = Path(small_bindings[name]["path"])
                    manifest_payload = read_json(manifest_path)
                    if not isinstance(manifest_payload, Mapping):
                        raise BindingError(f"{self.physical_case_id}: manifest is not an object")
                    manifest_schema = manifest_payload.get("schema")
                    if not isinstance(manifest_schema, str) or not manifest_schema:
                        raise BindingError(f"{self.physical_case_id}: manifest schema is missing")
                    expected_manifest_id = self.row.get("manifest_physical_case_id") or self.physical_case_id
                    if manifest_payload.get("physical_case_id") != expected_manifest_id:
                        raise BindingError(
                            f"{self.physical_case_id}: manifest identity differs from its CURRENT binding")
                    if (manifest_payload.get("family_id") is not None
                            and manifest_payload.get("family_id") != self.family_id):
                        raise BindingError(f"{self.physical_case_id}: manifest family differs from CURRENT")
                    manifest_identity = {
                        "schema": manifest_schema,
                        "physical_case_id": manifest_payload.get("physical_case_id"),
                        "family_id": manifest_payload.get("family_id"),
                        "top_level_keys": sorted(str(key) for key in manifest_payload),
                    }

        expected_header = self.row.get("header")
        if not isinstance(expected_header, Mapping):
            raise BindingError(f"{self.physical_case_id}: CURRENT header is missing")
        with h5py.File(trajectory, "r") as handle:
            attrs = handle.attrs
            schema = _as_text(attrs.get("schema", ""))
            if schema != TRAJECTORY_SCHEMA:
                raise BindingError(f"{self.physical_case_id}: unsupported HDF5 schema {schema!r}")
            identity_key = _as_text(attrs.get("identity_key", ""))
            if identity_key != "(Zone,Idp)":
                raise BindingError(f"{self.physical_case_id}: identity key is not (Zone,Idp)")
            try:
                units = json.loads(_as_text(attrs["units_json"]))
            except (KeyError, TypeError, json.JSONDecodeError) as error:
                raise BindingError(f"{self.physical_case_id}: invalid units_json") from error
            if units != expected_header.get("units"):
                raise BindingError(f"{self.physical_case_id}: HDF5 units differ from CURRENT")
            coordinate_frame = _as_text(attrs.get("coordinate_frame", ""))
            if coordinate_frame != expected_header.get("coordinate_frame"):
                raise BindingError(f"{self.physical_case_id}: coordinate frame differs from CURRENT")

            expected_fields = expected_header.get("fields", {})
            if not REQUIRED_FIELDS.issubset(expected_fields):
                raise BindingError(f"{self.physical_case_id}: CURRENT header lacks required fields")
            for field, descriptor in expected_fields.items():
                if field not in handle:
                    raise BindingError(f"{self.physical_case_id}: missing HDF5 field {field}")
                dataset = handle[field]
                actual_shape = list(dataset.shape)
                if actual_shape != descriptor.get("shape"):
                    raise BindingError(f"{self.physical_case_id}: shape differs for {field}")
                if str(dataset.dtype) != descriptor.get("dtype"):
                    raise BindingError(f"{self.physical_case_id}: dtype differs for {field}")
                expected_chunks = descriptor.get("chunks")
                actual_chunks = list(dataset.chunks) if dataset.chunks is not None else None
                if actual_chunks != expected_chunks:
                    raise BindingError(f"{self.physical_case_id}: chunks differ for {field}")

            times = np.asarray(handle["time"][:], dtype="float64")
            if times.shape != (int(self.row["frames"]),) or not np.isfinite(times).all() or not (np.diff(times) > 0).all():
                raise BindingError(f"{self.physical_case_id}: time axis is invalid")
            window = self.row.get("actual_time_window_s")
            if not isinstance(window, Sequence) or len(window) != 2:
                raise BindingError(f"{self.physical_case_id}: CURRENT time window is invalid")
            if not (math.isclose(float(times[0]), float(window[0]), rel_tol=0.0, abs_tol=1e-12)
                    and math.isclose(float(times[-1]), float(window[1]), rel_tol=0.0, abs_tol=1e-12)):
                raise BindingError(f"{self.physical_case_id}: time window differs from CURRENT")

            ids = np.asarray(handle["particle_id"][:])
            zones = np.asarray(handle["particle_zone"][:])
            if ids.dtype.kind not in "iu" or zones.dtype.kind not in "iu":
                raise BindingError(f"{self.physical_case_id}: noninteger typed identity axis")
            keys = np.empty(len(ids), dtype=[("zone", zones.dtype), ("idp", ids.dtype)])
            keys["zone"], keys["idp"] = zones, ids
            if len(np.unique(keys)) != len(keys):
                raise BindingError(f"{self.physical_case_id}: duplicate (Zone,Idp) identity")
            initial_type = np.asarray(handle["initial_type"][:])
            if initial_type.dtype.kind not in "iu" or not np.isin(initial_type, list(KNOWN_TYPES)).all():
                raise BindingError(f"{self.physical_case_id}: invalid initial type axis")

            observed_header = {"fields": expected_fields, "units": units,
                               "identity_key": identity_key, "coordinate_frame": coordinate_frame}

        source_hash = None
        if verify_source_hash:
            source_hash = sha256(trajectory)
            producer = self.row["trajectory"].get("producer_declared_sha256")
            if producer and source_hash != producer:
                raise BindingError(f"{self.physical_case_id}: HDF5 hash differs from producer declaration")
            recomputed = self.row["trajectory"].get("recomputed_sha256")
            if recomputed and source_hash != recomputed:
                raise BindingError(f"{self.physical_case_id}: HDF5 hash differs from CURRENT recomputation")
        return {
            "schema": "ds02.stage2.current-case-binding.v1",
            "catalog_path": str(self.catalog.path),
            "catalog_sha256": self.catalog.sha256,
            "physical_case_id": self.physical_case_id,
            "family_id": self.family_id,
            # Keep canonical inventory identity and the manifest identity as
            # separate fields.  Four CURRENT rows are accepted aliases whose
            # converter scope is explicitly distinct from canonical scope.
            "manifest_physical_case_id": self.row.get("manifest_physical_case_id"),
            "accepted_alias_evidence": self.row.get("accepted_alias_evidence"),
            "accepted_alias_provenance": self.row.get("accepted_alias_provenance"),
            "physical_condition_scopes": self._physical_condition_scopes(source_hash=source_hash),
            "case_row_sha256": self.row_sha256,
            "trajectory": {"path": str(trajectory),
                           "producer_declared_sha256": self.row["trajectory"].get("producer_declared_sha256"),
                           "recomputed_sha256": source_hash,
                           "bytes": trajectory.stat().st_size,
                           "mtime_ns": trajectory.stat().st_mtime_ns},
            "manifest": small_bindings.get("manifest"),
            "manifest_identity": manifest_identity,
            "xmf": small_bindings.get("xmf"),
            "conversion_report": small_bindings.get("conversion_report"),
            "header": observed_header,
            "frames": int(self.row["frames"]),
            "particles": int(self.row["particles"]),
            "actual_time_window_s": [float(value) for value in self.row["actual_time_window_s"]],
            "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        }

    def _physical_condition_scopes(self, *, source_hash: str | None = None) -> dict[str, Any]:
        alias = self.accepted_alias_evidence
        hdf5_scope = {
            "path": str(self.trajectory_path()),
            "scope_semantics": "CURRENT-bound trajectory artifact; HDF5 hash is not a canonical physical-condition hash",
            "producer_declared_sha256": self.row["trajectory"].get("producer_declared_sha256"),
            "recomputed_sha256": source_hash,
        }
        if not isinstance(alias, Mapping):
            return {"canonical": None, "actual_converter": None, "hdf5": hdf5_scope,
                    "equality_claim": "NOT_APPLICABLE"}
        canonical = alias.get("canonical_physical_case")
        actual = alias.get("actual_converter_scope")
        return {
            "canonical": dict(canonical) if isinstance(canonical, Mapping) else None,
            "actual_converter": dict(actual) if isinstance(actual, Mapping) else None,
            "hdf5": hdf5_scope,
            "equality_claim": "NOT_ASSERTED",
        }


class Current336Catalog:
    """An immutable view of the 336-row CURRENT manifest."""

    def __init__(self, path: Path, payload: Mapping[str, Any], digest_value: str,
                 mapper: PathMapper):
        self.path = path
        self.payload = payload
        self.sha256 = digest_value
        self.mapper = mapper
        self._cases = {row["physical_case_id"]: CurrentCase(self, row) for row in payload["cases"]}

    def case(self, physical_case_id: str) -> CurrentCase:
        if physical_case_id not in self._cases:
            raise BindingError(f"physical_case_id is not bound by CURRENT: {physical_case_id}")
        return self._cases[physical_case_id]

    def cases(self) -> tuple[CurrentCase, ...]:
        return tuple(self._cases[key] for key in sorted(self._cases))

    def resolve_case(self, physical_case_id: str) -> CurrentCase:
        return self.case(physical_case_id)


def _xml_float(element: ET.Element | None, attribute: str, label: str) -> float:
    if element is None or attribute not in element.attrib:
        raise BindingError(f"{label} is missing {attribute}")
    try:
        value = float(element.attrib[attribute])
    except (TypeError, ValueError) as error:
        raise BindingError(f"{label}.{attribute} is not numeric") from error
    if not math.isfinite(value):
        raise BindingError(f"{label}.{attribute} is not finite")
    return value


def read_rigid_body_semantics(case: CurrentCase) -> dict[str, Any]:
    """Read explicit rigid-body and SPH support-mass declarations from XML.

    A floating particle's ``masspart`` is a solver support-particle weight.  A
    rigid body's ``massbody`` is a physical body mass.  The two are returned in
    separate scopes and are never inferred from a trajectory particle sum.  No
    HDF5 state is read here, so pose and velocity remain UNKNOWN.
    """
    if not isinstance(case, CurrentCase):
        raise TypeError("read_rigid_body_semantics requires a CURRENT-bound CurrentCase")
    bindings = case.row.get("source_bindings")
    generated = bindings.get("generated_xml") if isinstance(bindings, Mapping) else None
    if not isinstance(generated, Mapping):
        raise BindingError(f"{case.physical_case_id}: CURRENT has no generated XML binding")
    xml_path = case.path(generated)
    if not xml_path.is_file():
        raise BindingError(f"{case.physical_case_id}: generated XML is unavailable: {xml_path}")
    expected_hash = generated.get("recomputed_sha256") or generated.get("sha256")
    actual_hash = sha256(xml_path)
    if expected_hash and actual_hash != expected_hash:
        raise BindingError(f"{case.physical_case_id}: generated XML hash differs from CURRENT")
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError as error:
        raise BindingError(f"{case.physical_case_id}: generated XML is malformed") from error

    body_nodes = root.findall(".//casedef/floatings/floating")
    particle_nodes = root.findall(".//execution/particles/floating")
    if len(body_nodes) != 1 or len(particle_nodes) != 1:
        raise BindingError(f"{case.physical_case_id}: XML must contain one body and one particle floating declaration")
    body_node, particle_node = body_nodes[0], particle_nodes[0]
    body_mass = _xml_float(body_node.find("massbody"), "value", "casedef.floatings.floating.massbody")
    particle_massbody = _xml_float(particle_node.find("massbody"), "value",
                                   "execution.parameters.particles.floating.massbody")
    particle_masspart = _xml_float(particle_node.find("masspart"), "value",
                                   "execution.parameters.particles.floating.masspart")
    try:
        particle_count = int(particle_node.attrib["count"])
        body_mkbound = int(body_node.attrib["mkbound"])
        particle_mkbound = int(particle_node.attrib["mkbound"])
    except (KeyError, TypeError, ValueError) as error:
        raise BindingError(f"{case.physical_case_id}: floating XML counts or mkbound are invalid") from error
    if particle_count <= 0 or particle_masspart <= 0 or body_mass <= 0 or particle_massbody <= 0:
        raise BindingError(f"{case.physical_case_id}: floating XML masses/count must be positive")
    if body_mkbound != particle_mkbound:
        raise BindingError(f"{case.physical_case_id}: body and particle mkbound differ")
    if not math.isclose(body_mass, particle_massbody, rel_tol=0.0, abs_tol=1e-9):
        raise BindingError(f"{case.physical_case_id}: body mass declarations differ")
    inertia_node = body_node.find("inertia")
    inertia = [_xml_float(inertia_node, axis, "casedef.floatings.floating.inertia") for axis in ("x", "y", "z")]
    support_weight = float(particle_count * particle_masspart)
    return {
        "schema": "ds02.stage2.rigid-body-semantics.v1",
        "physical_case_id": case.physical_case_id,
        "family_id": case.family_id,
        "source": {"kind": "generated_xml", "path": str(xml_path),
                    "sha256": actual_hash, "current_declared_sha256": expected_hash},
        "physical_rigid_body": {
            "source_xpath": "casedef/floatings/floating/massbody",
            "mkbound": body_mkbound,
            "massbody_kg": body_mass,
            "inertia_kg_m2": inertia,
            "meaning": "physical rigid-body mass from XML; never inferred from HDF5 particle sums",
        },
        "particle_support_representation": {
            "source_xpath": "execution/particles/floating",
            "mkbound": particle_mkbound,
            "count": particle_count,
            "massbody_kg_declaration": particle_massbody,
            "masspart_kg": particle_masspart,
            "support_particle_weight_kg": support_weight,
            "meaning": "SPH floating-boundary particle weight; not physical rigid-body mass",
        },
        "state": {
            "pose": "UNKNOWN",
            "linear_velocity": "UNKNOWN",
            "angular_velocity": "UNKNOWN",
            "source": "HDF5 trajectory state was not read by this metadata interface",
        },
        "mass_policy": {
            "fluid_observation_labels": "use CURRENT-bound HDF5 initial_mass for initial_type==3",
            "rigid_body_observables": "use physical_rigid_body.massbody_kg only when a body observable is requested",
            "forbidden_inference": "do not sum floating HDF5 initial_mass to replace XML massbody",
        },
        "qualification_status": "UNKNOWN",
    }


def load_current_catalog(path: Path | str, *, expected_sha256: str | None = None,
                         path_map: Mapping[str, str] | None = None,
                         expected_case_count: int = 336,
                         verify_source_catalog: bool = True) -> Current336Catalog:
    """Load CURRENT336 and reject stale/partial/ambiguous catalogs.

    ``expected_case_count`` is configurable only for isolated manufactured
    fixtures.  Production callers leave it at 336 and keep
    ``verify_source_catalog=True``.
    """
    current_path = Path(path).expanduser().resolve()
    if current_path.name != "CURRENT336.json":
        raise BindingError("Stage 2 consumers require a file named CURRENT336.json")
    if not current_path.is_file():
        raise BindingError(f"CURRENT manifest is unavailable: {current_path}")
    digest_value = sha256(current_path)
    if expected_sha256 and digest_value != expected_sha256:
        raise BindingError("CURRENT manifest hash differs from the requested binding")
    payload = read_json(current_path)
    if not isinstance(payload, Mapping) or payload.get("schema") != CURRENT_SCHEMA:
        raise BindingError("unsupported CURRENT schema")
    rows = payload.get("cases")
    if not isinstance(rows, list) or len(rows) != expected_case_count:
        raise BindingError(f"CURRENT must contain exactly {expected_case_count} cases")
    ids = [row.get("physical_case_id") if isinstance(row, Mapping) else None for row in rows]
    if any(not isinstance(case_id, str) or not case_id for case_id in ids) or len(set(ids)) != len(ids):
        raise BindingError("CURRENT physical_case_id axis is not unique")
    if payload.get("unresolved") != 0:
        raise BindingError("CURRENT has unresolved source rows")
    mapper = PathMapper(current_path.parent, path_map)
    source_catalog_raw = payload.get("source_catalog")
    source_digest = payload.get("source_catalog_sha256")
    if verify_source_catalog:
        if not isinstance(source_catalog_raw, str) or not _HEX64.fullmatch(str(source_digest or "")):
            raise BindingError("CURRENT source catalog binding is incomplete")
        source_catalog = mapper.resolve(source_catalog_raw)
        if source_catalog.name != "CASES_336.json" or not source_catalog.is_file():
            raise BindingError(f"CURRENT source catalog is unavailable: {source_catalog}")
        if sha256(source_catalog) != source_digest:
            raise BindingError("CURRENT source catalog hash differs")
    trajectory_total = 0
    for row in rows:
        if not isinstance(row, Mapping):
            raise BindingError("CURRENT contains a non-object case row")
        trajectory = row.get("trajectory")
        if not isinstance(trajectory, Mapping) or not _HEX64.fullmatch(str(trajectory.get("producer_declared_sha256", ""))):
            raise BindingError(f"{row.get('physical_case_id')}: producer HDF5 hash is missing")
        if not isinstance(row.get("frames"), int) or not isinstance(row.get("particles"), int):
            raise BindingError(f"{row.get('physical_case_id')}: invalid dimensions")
        manifest_case_id = row.get("manifest_physical_case_id")
        if manifest_case_id is not None:
            if not isinstance(manifest_case_id, str):
                raise BindingError(f"{row.get('physical_case_id')}: manifest physical case id is invalid")
            alias = _alias_evidence(row)
            if manifest_case_id == row.get("physical_case_id"):
                # A complete CURRENT rebuild may record the manifest ID on
                # canonical rows too.  Equal IDs are canonical; contradictory
                # alias evidence is rejected instead of silently counted.
                if alias is not None:
                    raise BindingError(f"{row.get('physical_case_id')}: equal IDs carry alias evidence")
            else:
                canonical = alias.get("canonical_physical_case") if isinstance(alias, Mapping) else None
                actual = alias.get("actual_converter_scope") if isinstance(alias, Mapping) else None
                scopes_separate = (isinstance(actual, Mapping)
                                   and (actual.get("separate_from_canonical_source_scope") is True
                                        or "not asserted" in str(actual.get("scope_equality_claim", "")).lower()))
                canonical_manifest = canonical.get("manifest_physical_case_id") if isinstance(canonical, Mapping) else None
                if (not isinstance(alias, Mapping)
                        or not isinstance(canonical, Mapping)
                        or canonical.get("inventory_physical_case_id") != row.get("physical_case_id")
                        # Some accepted aliases preserve only the canonical
                        # inventory identity; a missing canonical manifest id is
                        # retained as unknown rather than invented or equated.
                        or (canonical_manifest is not None and canonical_manifest != manifest_case_id)
                        or not isinstance(actual, Mapping)
                        or not scopes_separate):
                    raise BindingError(f"{row.get('physical_case_id')}: malformed accepted alias evidence")
        trajectory_total += int(trajectory.get("bytes", 0))
        header = row.get("header")
        if not isinstance(header, Mapping) or not isinstance(header.get("fields"), Mapping):
            raise BindingError(f"{row.get('physical_case_id')}: header is incomplete")
    if payload.get("total_hdf5_bytes") != trajectory_total:
        raise BindingError("CURRENT total_hdf5_bytes does not match rows")
    return Current336Catalog(current_path, payload, digest_value, mapper)


def read_case_window(case: CurrentCase | Current336Catalog | Path | str, physical_case_id: str | None = None,
                     *, frame_start: int = 0, frame_stop: int | None = None,
                     particle_start: int = 0, particle_stop: int | None = None,
                     fields: Iterable[str] | None = None) -> dict[str, Any]:
    """Read a bounded frame/particle window from the bound HDF5 source."""
    if isinstance(case, CurrentCase):
        selected = case
    else:
        catalog = case if isinstance(case, Current336Catalog) else load_current_catalog(case)
        if not physical_case_id:
            raise BindingError("physical_case_id is required when a catalog is supplied")
        selected = catalog.case(physical_case_id)
    binding = selected.inspect()
    total_frames, total_particles = binding["frames"], binding["particles"]
    stop_frame = total_frames if frame_stop is None else frame_stop
    stop_particle = total_particles if particle_stop is None else particle_stop
    if not (0 <= frame_start < stop_frame <= total_frames and 0 <= particle_start < stop_particle <= total_particles):
        raise BindingError("requested HDF5 window is outside the bound dimensions")
    requested = tuple(fields or FRAME_FIELDS)
    unknown = set(requested) - REQUIRED_FIELDS
    if unknown:
        raise BindingError(f"unknown HDF5 fields requested: {sorted(unknown)}")
    result: dict[str, Any] = {"binding": binding, "physical_case_id": selected.physical_case_id,
                              "family_id": selected.family_id}
    with h5py.File(selected.trajectory_path(), "r") as handle:
        for field in requested:
            if field == "time":
                result[field] = handle[field][frame_start:stop_frame]
            elif field in STATIC_FIELDS:
                result[field] = handle[field][particle_start:stop_particle]
            else:
                result[field] = handle[field][frame_start:stop_frame, particle_start:stop_particle]
    return result


def _locate(points: np.ndarray, regions: Sequence[Mapping[str, Any]]) -> np.ndarray:
    labels = np.zeros(len(points), dtype=np.int16)
    for code, region in enumerate(regions, 1):
        bounds = np.asarray(region["bounds"], dtype="float64")
        selected = ((points >= bounds[:, 0]) & (points < bounds[:, 1])).all(axis=1)
        if np.any(selected & (labels != 0)):
            raise BindingError("destination/source regions overlap at an observed particle")
        labels[selected] = code
    return labels


def _chord_box_fraction(p0: np.ndarray, p1: np.ndarray, bounds: np.ndarray) -> np.ndarray:
    lower, upper = np.zeros(len(p0)), np.ones(len(p0))
    for axis, (lo, hi) in enumerate(bounds):
        delta = p1[:, axis] - p0[:, axis]
        moving = delta != 0
        a = np.divide(lo - p0[:, axis], delta, out=np.zeros(len(p0)), where=moving)
        b = np.divide(hi - p0[:, axis], delta, out=np.ones(len(p0)), where=moving)
        lower = np.maximum(lower, np.where(moving, np.minimum(a, b), 0))
        upper = np.minimum(upper, np.where(moving, np.maximum(a, b), 1))
        outside = ~moving & ((p0[:, axis] < lo) | (p0[:, axis] >= hi))
        upper[outside] = -1
    return np.maximum(0, upper - lower)


def validate_label_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a JSON-safe copy of an observation operator."""
    try:
        normalized = json.loads(canonical_json(config))
    except (TypeError, ValueError) as error:
        raise BindingError("label configuration must be finite JSON") from error
    if normalized.get("schema") not in (None, "ds02.stage2.observation-config.v2"):
        raise BindingError("unsupported observation configuration schema")
    if normalized.get("frame_kind") != "fixed_solver_frame":
        raise BindingError("trajectory frame must be explicitly fixed_solver_frame")
    if not isinstance(normalized.get("coordinate_frame"), str) or not normalized["coordinate_frame"]:
        raise BindingError("coordinate_frame is required")
    assignment = normalized.get("source_assignment", "initial_regions")
    if assignment not in ("initial_regions", "native_initial_mk"):
        raise BindingError("unsupported source_assignment")
    source_regions = normalized.get("source_regions")
    destination_regions = normalized.get("destination_regions")
    if not isinstance(source_regions, list) or not source_regions or not isinstance(destination_regions, list) or not destination_regions:
        raise BindingError("finite source_regions and destination_regions are required")
    for name, regions in (("source_regions", source_regions), ("destination_regions", destination_regions)):
        ids = [row.get("id") if isinstance(row, Mapping) else None for row in regions]
        if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
            raise BindingError(f"{name} ids must be unique nonempty strings")
        for row in regions:
            if not isinstance(row, Mapping):
                raise BindingError(f"{name} rows must be objects")
            row["bounds"] = _finite_bounds(row.get("bounds"), f"{name}.bounds").tolist()
        for index, left in enumerate(regions):
            a = np.asarray(left["bounds"])
            for right in regions[index + 1:]:
                b = np.asarray(right["bounds"])
                if (np.minimum(a[:, 1], b[:, 1]) > np.maximum(a[:, 0], b[:, 0])).all():
                    raise BindingError(f"{name} boxes overlap")
    if assignment == "native_initial_mk":
        mks = [row.get("native_mk") for row in source_regions]
        if any(isinstance(mk, bool) or not isinstance(mk, int) or mk < 0 for mk in mks) or len(set(mks)) != len(mks):
            raise BindingError("native_initial_mk sources require unique nonnegative integers")
    events = normalized.get("events", [])
    if not isinstance(events, list):
        raise BindingError("events must be a list")
    event_ids = [row.get("id") if isinstance(row, Mapping) else None for row in events]
    if any(not isinstance(value, str) or not value for value in event_ids) or len(set(event_ids)) != len(event_ids):
        raise BindingError("event ids must be unique nonempty strings")
    for event in events:
        surface = event.get("surface")
        if not isinstance(surface, Mapping):
            raise BindingError("each event requires an explicit surface object")
        kind = surface.get("kind")
        if kind not in ("fixed_plane", "translating_plane"):
            raise BindingError("surface kind must be fixed_plane or translating_plane")
        point = _finite_vector(surface.get("point_m"), 3, "surface.point_m")
        normal = _finite_vector(surface.get("normal_m"), 3, "surface.normal_m")
        norm = float(np.linalg.norm(normal))
        if norm <= 0:
            raise BindingError("surface normal must be nonzero")
        normal /= norm
        axis = int(np.argmax(np.abs(normal)))
        if abs(abs(normal[axis]) - 1.0) > 1e-12 or np.any(np.abs(np.delete(normal, axis)) > 1e-12):
            raise BindingError("v2 surface operator requires an axis-aligned plane")
        aperture_axes = surface.get("aperture_axes", [index for index in range(3) if index != axis])
        if sorted(aperture_axes) != [index for index in range(3) if index != axis]:
            raise BindingError("aperture_axes must be the two axes transverse to the plane")
        bounds = np.asarray(surface.get("aperture_bounds"), dtype="float64")
        if bounds.shape != (2, 2) or not np.isfinite(bounds).all() or not (bounds[:, 1] > bounds[:, 0]).all():
            raise BindingError("surface aperture must contain two finite nonempty bounds")
        frame = surface.get("aperture_frame", "surface_local")
        if frame not in ("surface_local", "world"):
            raise BindingError("surface.aperture_frame must be surface_local or world")
        velocity = surface.get("velocity_m_s", [0.0, 0.0, 0.0])
        if kind == "translating_plane":
            _finite_vector(velocity, 3, "surface.velocity_m_s")
        elif np.linalg.norm(_finite_vector(velocity, 3, "surface.velocity_m_s")) > 0:
            raise BindingError("fixed_plane cannot carry nonzero velocity")
        reference_time = surface.get("reference_time_s", 0.0)
        if isinstance(reference_time, bool) or not isinstance(reference_time, (int, float)) or not math.isfinite(reference_time):
            raise BindingError("surface.reference_time_s must be finite")
        # Keep normalized values in the output config so the operator hash is
        # independent of whether a caller used [1,0,0] or [2,0,0].
        surface["point_m"] = point.tolist()
        surface["normal_m"] = normal.tolist()
        surface["aperture_axes"] = list(aperture_axes)
        surface["aperture_bounds"] = bounds.tolist()
        surface["velocity_m_s"] = _finite_vector(velocity, 3, "surface.velocity_m_s").tolist()
        surface["reference_time_s"] = float(reference_time)
        surface["aperture_frame"] = frame
    normalized["schema"] = "ds02.stage2.observation-config.v2"
    normalized["source_assignment"] = assignment
    return normalized


def _surface_event(p0: np.ndarray, p1: np.ndarray, t0: float, t1: float,
                   velocity0: np.ndarray, velocity1: np.ndarray,
                   surface: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    point = np.asarray(surface["point_m"], dtype="float64")
    normal = np.asarray(surface["normal_m"], dtype="float64")
    velocity = np.asarray(surface["velocity_m_s"], dtype="float64")
    reference_time = float(surface["reference_time_s"])
    point0 = point + velocity * (t0 - reference_time)
    point1 = point + velocity * (t1 - reference_time)
    signed0 = np.sum((p0 - point0) * normal, axis=1)
    signed1 = np.sum((p1 - point1) * normal, axis=1)
    forward = (signed0 < 0) & (signed1 >= 0)
    backward = (signed0 >= 0) & (signed1 < 0)
    denominator = signed1 - signed0
    tau = np.divide(-signed0, denominator, out=np.zeros(len(p0)), where=denominator != 0)
    crossing = p0 + tau[:, None] * (p1 - p0)
    crossing_time = t0 + tau * (t1 - t0)
    crossing_surface = point + (crossing_time - reference_time)[:, None] * velocity
    axes = list(surface["aperture_axes"])
    if surface.get("aperture_frame") == "surface_local":
        coordinates = crossing[:, axes] - crossing_surface[:, axes]
    else:
        coordinates = crossing[:, axes]
    bounds = np.asarray(surface["aperture_bounds"], dtype="float64")
    inside = ((coordinates >= bounds[:, 0]) & (coordinates < bounds[:, 1])).all(axis=1)
    relative_velocity = velocity0 + tau[:, None] * (velocity1 - velocity0) - velocity
    relative_normal_speed = np.sum(relative_velocity * normal, axis=1)
    return forward & inside, backward & inside, tau, relative_normal_speed


def materialize_labels(catalog: Current336Catalog | Path | str, physical_case_id: str | None,
                       output: Path | str, config: Mapping[str, Any], *, particle_chunk: int = 65536,
                       path_map: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Materialize a versioned, model-free observation sidecar.

    The source is always selected by ``physical_case_id`` in CURRENT.  A full
    source hash is computed after the read and compared with the producer hash;
    a mismatch leaves the ``.partial`` artifact for inspection and is never
    published as a label.
    """
    if isinstance(catalog, Current336Catalog):
        current = catalog
    else:
        current = load_current_catalog(catalog, path_map=path_map)
    if not physical_case_id:
        raise BindingError("physical_case_id is required for label materialization")
    case = current.case(physical_case_id)
    normalized_config = validate_label_config(config)
    if (isinstance(particle_chunk, bool) or not isinstance(particle_chunk, int)
            or particle_chunk < 1):
        raise BindingError("particle_chunk must be a positive integer")
    output_path = Path(output).expanduser().resolve()
    source = case.trajectory_path()
    if output_path == source:
        raise BindingError("labels must be a new sidecar artifact")
    if output_path.exists():
        raise FileExistsError(f"preserve existing label artifact: {output_path}")
    partial = output_path.with_suffix(output_path.suffix + ".partial")
    if partial.exists():
        raise FileExistsError(f"preserve unfinished label artifact: {partial}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    binding = case.inspect()
    expected_frame = binding["header"]["coordinate_frame"]
    if expected_frame != normalized_config["coordinate_frame"]:
        raise BindingError("label coordinate frame differs from CURRENT trajectory")
    regions = normalized_config["destination_regions"]
    sources_config = normalized_config["source_regions"]
    events = normalized_config["events"]
    nr, ne = len(regions), len(events)
    config_digest = canonical_sha256(normalized_config)
    source_stat = source.stat()

    with h5py.File(source, "r") as handle, h5py.File(partial, "x") as out:
        times = np.asarray(handle["time"][:], dtype="float64")
        nt, n_particles = len(times), int(handle["particle_id"].shape[0])
        if nt != binding["frames"] or n_particles != binding["particles"]:
            raise BindingError("source dimensions changed between CURRENT header and label read")
        # Positions/velocities are promoted to float64 for the operator.  The
        # bound reserves space for the five frame arrays plus masks and event
        # work vectors; its chunk therefore shrinks as the saved timeline
        # grows instead of allocating several GiB for a long case.
        estimated_bytes_per_frame_particle = 128
        effective_chunk = max(
            1,
            min(particle_chunk, LABEL_WORKING_SET_BOUND_BYTES
                // max(1, nt * estimated_bytes_per_frame_particle)),
        )
        working_set_estimate = int(nt * effective_chunk * estimated_bytes_per_frame_particle)
        ids = np.asarray(handle["particle_id"][:])
        zones = np.asarray(handle["particle_zone"][:])
        initial_type = np.asarray(handle["initial_type"][:])
        initial_mass = np.asarray(handle["initial_mass"][:], dtype="float64")
        if not np.isfinite(initial_mass[initial_type == TYPE_FLUID]).all() or np.any(initial_mass[initial_type == TYPE_FLUID] <= 0):
            raise BindingError("initial fluid masses must be finite and positive")
        fluid_total_mask = initial_type == TYPE_FLUID
        total_initial_mass = float(initial_mass[fluid_total_mask].sum(dtype="float64"))
        if total_initial_mass <= 0:
            raise BindingError("trajectory has no initial fluid mass")
        if normalized_config.get("source_assignment", "initial_regions") == "native_initial_mk":
            initial_mk = np.asarray(handle["initial_mk"][:])
        else:
            initial_mk = None

        out.attrs.update(
            schema=LABEL_SCHEMA,
            current_manifest_sha256=current.sha256,
            current_source_catalog_sha256=current.payload.get("source_catalog_sha256"),
            current_case_id=case.physical_case_id,
            current_case_row_sha256=case.row_sha256,
            source_hdf5=str(source),
            source_hdf5_sha256="PENDING",
            source_hdf5_producer_sha256=case.row["trajectory"]["producer_declared_sha256"],
            config_sha256=config_digest,
            config_json=canonical_json(normalized_config),
            coordinate_frame=expected_frame,
            identity_key="(Zone,Idp)",
            mass_denominator_semantics="sum(initial_mass where initial_type==3), including initially invalid identities",
            nan_invalid_semantics="valid=0 is missing; valid=1 with nonfinite position/mass is invalid_state; no zero imputation",
            event_surface_semantics="signed distance to saved surface pose; direction uses (u-u_surface) dot n",
            event_time_semantics="saved-frame bracket plus linear signed-distance chord estimate; hidden recrossings unresolved",
            lineage_semantics="fixed (Zone,Idp) typed axis; births, revival after valid=false, and adaptive mass are rejected",
            model_invoked=False,
            q_i_status="UNKNOWN",
            q_n_status="NOT_ASSESSED",
            q_e_status="NOT_ASSESSED",
            qualification_status="UNKNOWN",
            complete=False,
            particle_chunk_requested=particle_chunk,
            particle_chunk_effective=effective_chunk,
            label_working_set_bound_bytes=LABEL_WORKING_SET_BOUND_BYTES,
            label_working_set_estimate_bytes=working_set_estimate,
        )
        out.create_dataset("time", data=times)
        out.create_dataset("particle_id", data=ids)
        out.create_dataset("particle_zone", data=zones)

        def create(name: str, shape: tuple[int, ...], dtype: str, fillvalue: Any = 0):
            kwargs = {"fillvalue": fillvalue}
            if all(shape):
                kwargs["compression"] = "gzip"
            return out.create_dataset(name, shape=shape, dtype=dtype, **kwargs)

        source_labels_ds = create("source_label", (n_particles,), "i2")
        initial_active_ds = create("initially_active", (n_particles,), "bool")
        origin_mass_ds = create("initial_fluid_mass_kg", (n_particles,), "f8")
        dest_ds = create("destination_time_series", (nt, n_particles), "i2")
        final_ds = create("final_category", (n_particles,), "i2")
        failure_ds = create("failure_reason", (n_particles,), "i1")
        first_interval_ds = create("first_passage_interval", (n_particles, ne, 2), "f8", np.nan)
        first_time_ds = create("first_passage_chord_time", (n_particles, ne), "f8", np.nan)
        first_speed_ds = create("first_passage_relative_normal_speed_m_s", (n_particles, ne), "f8", np.nan)
        censor_ds = create("first_passage_censor", (n_particles, ne), "i1", 1)
        crossing_count_ds = create("crossing_count", (n_particles, ne), "i4")
        residence_ds = create("residence_time_s", (n_particles, nr), "f8")
        unresolved_ds = create("unresolved_interval_time_s", (n_particles,), "f8")

        forward_backward = np.zeros((nt, ne, 2), dtype="float64")
        cumulative_crossings = np.zeros((nt, ne), dtype="int64")
        missing_mass = np.zeros(nt, dtype="float64")
        invalid_mass = np.zeros(nt, dtype="float64")
        unknown_mass = np.zeros(nt, dtype="float64")
        source_final = np.zeros((len(sources_config) + 1, nr + 3), dtype="float64")
        initial_source_unknown_mass = 0.0

        for begin in range(0, n_particles, effective_chunk):
            end = min(n_particles, begin + effective_chunk)
            sl = slice(begin, end)
            valid_values = np.asarray(handle["valid"][:, sl], dtype=bool)
            frame_types = np.asarray(handle["type"][:, sl])
            positions = np.asarray(handle["position"][:, sl], dtype="float64")
            velocities = np.asarray(handle["velocity"][:, sl], dtype="float64")
            masses = np.asarray(handle["mass"][:, sl], dtype="float64")
            cohort = fluid_total_mask[sl]
            mass = np.where(cohort, initial_mass[sl], 0.0)
            initially_active = cohort & valid_values[0] & np.isfinite(positions[0]).all(axis=1) & np.isfinite(masses[0]) & (masses[0] > 0)
            source_labels = np.zeros(end - begin, dtype="int16")
            if normalized_config.get("source_assignment", "initial_regions") == "native_initial_mk":
                local_mk = initial_mk[sl]
                for code, source_region in enumerate(sources_config, 1):
                    source_labels[local_mk == source_region["native_mk"]] = code
                if np.any(cohort & (source_labels == 0)):
                    raise BindingError("an initial fluid identity has no registered native_mk source")
            else:
                source_labels[initially_active] = _locate(positions[0][initially_active], sources_config)
            source_labels[~cohort] = 0
            source_labels_ds[sl] = source_labels
            initial_active_ds[sl] = initially_active
            origin_mass_ds[sl] = mass
            total_initial_source_unknown = mass[cohort & (source_labels == 0)].sum(dtype="float64")
            initial_source_unknown_mass += float(total_initial_source_unknown)

            destination_series = np.zeros((nt, end - begin), dtype="int16")
            residence = np.zeros((end - begin, nr), dtype="float64")
            unresolved = np.zeros(end - begin, dtype="float64")
            first_interval = np.full((end - begin, ne, 2), np.nan, dtype="float64")
            first_time = np.full((end - begin, ne), np.nan, dtype="float64")
            first_speed = np.full((end - begin, ne), np.nan, dtype="float64")
            censor = np.ones((end - begin, ne), dtype="int8")
            crossing_count = np.zeros((end - begin, ne), dtype="int32")
            chunk_cumulative_crossings = np.zeros((nt, ne), dtype="int64")
            disappeared = np.zeros(end - begin, dtype=bool)
            previous_good = None
            previous_position = None
            previous_velocity = None
            final_destination = np.zeros(end - begin, dtype="int16")
            for frame, timestamp in enumerate(times):
                valid = valid_values[frame]
                current_type = frame_types[frame]
                if current_type.dtype.kind not in "iu":
                    raise BindingError("per-frame type axis is not integer")
                if not np.isin(current_type, list(KNOWN_TYPES)).all():
                    raise BindingError("per-frame type axis contains an unknown typed identity")
                if np.any(~cohort & valid & (current_type == TYPE_FLUID)):
                    raise LifecycleError("fluid birth on a fixed typed axis requires explicit lineage")
                if np.any(cohort & valid & (current_type != TYPE_FLUID)):
                    raise LifecycleError("fluid identity changed type")
                if np.any(disappeared & cohort & valid):
                    raise LifecycleError("identity revived after valid=false without lineage")
                finite_velocity = np.isfinite(velocities[frame]).all(axis=1)
                if np.any(cohort & valid & ~finite_velocity):
                    raise BindingError("active fluid velocity is nonfinite; event speed is unobserved")
                disappeared |= cohort & ~valid
                current_mass = masses[frame]
                finite_position = np.isfinite(positions[frame]).all(axis=1)
                finite_mass = np.isfinite(current_mass) & (current_mass > 0)
                good = cohort & valid & finite_position & finite_mass & finite_velocity
                if np.any(good & ~np.isclose(current_mass, mass, rtol=1e-5, atol=0.0)):
                    raise LifecycleError("variable fluid mass requires adaptive lifecycle support")
                destination = _locate(positions[frame], regions)
                destination[~cohort] = -3
                destination[cohort & ~valid] = -1
                destination[cohort & valid & ~good] = -2
                destination_series[frame] = destination
                final_destination = destination
                missing_mass[frame] += float(mass[cohort & ~valid].sum(dtype="float64"))
                invalid_mass[frame] += float(mass[cohort & valid & ~good].sum(dtype="float64"))
                unknown_mass[frame] += float(mass[good & (destination == 0)].sum(dtype="float64"))
                if frame:
                    paired = previous_good & good
                    dt = float(timestamp - times[frame - 1])
                    unresolved += np.where(cohort & ~paired, dt, 0.0)
                    for region_index, region in enumerate(regions):
                        residence[:, region_index] += np.where(
                            paired,
                            _chord_box_fraction(previous_position, positions[frame], np.asarray(region["bounds"])) * dt,
                            0.0,
                        )
                    for event_index, event in enumerate(events):
                        forward, backward, tau, relative_speed = _surface_event(
                            previous_position, positions[frame], float(times[frame - 1]), float(timestamp),
                            previous_velocity, velocities[frame], event["surface"])
                        forward &= paired
                        backward &= paired
                        crossed = forward | backward
                        forward_backward[frame, event_index, 0] += float(mass[forward].sum(dtype="float64"))
                        forward_backward[frame, event_index, 1] += float(mass[backward].sum(dtype="float64"))
                        crossing_count[:, event_index] += crossed.astype("int32")
                        selected = crossed & np.isnan(first_interval[:, event_index, 0])
                        first_interval[selected, event_index] = np.column_stack((times[frame - 1], timestamp))
                        first_time[selected, event_index] = times[frame - 1] + tau[selected] * dt
                        first_speed[selected, event_index] = relative_speed[selected]
                        censor[selected, event_index] = 0
                previous_position = positions[frame]
                previous_velocity = velocities[frame]
                previous_good = good
                chunk_cumulative_crossings[frame] = crossing_count.sum(axis=0)

            dest_ds[:, sl] = destination_series
            final_ds[sl] = final_destination
            first_interval_ds[sl] = first_interval
            first_time_ds[sl] = first_time
            first_speed_ds[sl] = first_speed
            censor_ds[sl] = censor
            crossing_count_ds[sl] = crossing_count
            residence_ds[sl] = residence
            unresolved_ds[sl] = unresolved
            # ``crossing_count`` is local to this particle chunk.  Add its
            # saved-frame cumulative history after the chunk completes so a
            # later chunk cannot overwrite earlier particles' counts.
            cumulative_crossings += chunk_cumulative_crossings
            failure_ds[sl] = np.where(~cohort, 4, np.where(final_destination == -1, 1,
                np.where(final_destination == -2, 2, np.where(final_destination == 0, 3, 0))))
            # Columns: missing, invalid_state, unknown, then destination regions.
            for source_code in range(len(sources_config) + 1):
                selected_source = source_labels == source_code
                source_final[source_code, 0] += float(mass[selected_source & (final_destination == -1)].sum(dtype="float64"))
                source_final[source_code, 1] += float(mass[selected_source & (final_destination == -2)].sum(dtype="float64"))
                source_final[source_code, 2] += float(mass[selected_source & (final_destination == 0)].sum(dtype="float64"))
                for destination_code in range(1, nr + 1):
                    source_final[source_code, 2 + destination_code] += float(
                        mass[selected_source & (final_destination == destination_code)].sum(dtype="float64"))

        if source.stat().st_size != source_stat.st_size or source.stat().st_mtime_ns != source_stat.st_mtime_ns:
            raise BindingError("source trajectory changed during label materialization")
        source_hash = sha256(source)
        producer_hash = case.row["trajectory"]["producer_declared_sha256"]
        if source_hash != producer_hash:
            raise BindingError("source trajectory hash differs from CURRENT producer declaration")
        out.create_dataset("forward_backward_mass_kg", data=np.cumsum(forward_backward, axis=0))
        out.create_dataset("cumulative_net_flux_kg", data=np.cumsum(forward_backward[:, :, 0] - forward_backward[:, :, 1], axis=0))
        out.create_dataset("cumulative_crossing_count", data=cumulative_crossings)
        out.create_dataset("missing_mass_kg", data=missing_mass)
        out.create_dataset("invalid_state_mass_kg", data=invalid_mass)
        out.create_dataset("unknown_mass_kg", data=unknown_mass)
        out.create_dataset("source_final_mass_kg", data=source_final)
        out.attrs.update(
            initial_fluid_mass_kg=total_initial_mass,
            initial_source_unknown_mass_kg=initial_source_unknown_mass,
            source_final_columns="missing,invalid_state,unknown,then destination_regions",
            destination_codes=json.dumps({"-3": "noninitial_fluid", "-2": "invalid_state", "-1": "missing", "0": "unknown",
                                           **{str(index): region["id"] for index, region in enumerate(regions, 1)}}),
            first_passage_censor_codes="0=observed_saved_chord;1=not_observed_or_censored",
            failure_reason_codes="0=none;1=missing;2=invalid_state;3=unknown_destination;4=noninitial_fluid",
            source_hdf5_sha256=source_hash,
            complete=True,
        )
    os.replace(partial, output_path)
    return {
        "schema": LABEL_SCHEMA,
        "path": str(output_path),
        "sha256": sha256(output_path),
        "current_manifest_sha256": current.sha256,
        "current_source_catalog_sha256": current.payload.get("source_catalog_sha256"),
        "current_case_id": case.physical_case_id,
        "source_hdf5_sha256": source_hash,
        "initial_fluid_mass_kg": total_initial_mass,
        "frames": nt,
        "identities": n_particles,
        "q_i_status": "UNKNOWN",
        "q_n_status": "NOT_ASSESSED",
        "q_e_status": "NOT_ASSESSED",
        "qualification_status": "UNKNOWN",
        "model_invoked": False,
        "particle_chunk_requested": particle_chunk,
        "particle_chunk_effective": effective_chunk,
        "label_working_set_bound_bytes": LABEL_WORKING_SET_BOUND_BYTES,
        "label_working_set_estimate_bytes": working_set_estimate,
    }


def _json_array_with_nulls(value: Any) -> np.ndarray:
    """Convert a JSON expectation array, mapping null to an expected NaN."""
    def convert(item: Any) -> Any:
        if item is None:
            return np.nan
        if isinstance(item, list):
            return [convert(child) for child in item]
        return item
    return np.asarray(convert(value))


def _numeric_check(actual: Any, expected: Any, name: str,
                   *, absolute: float, relative: float) -> dict[str, Any]:
    """Compare one independently authored expectation with explicit NaN rules."""
    if expected is None:
        return {"status": "FAIL", "name": name, "reason": "missing_expected_value"}
    actual_array = np.asarray(actual)
    expected_array = _json_array_with_nulls(expected)
    if actual_array.shape != expected_array.shape:
        return {"status": "FAIL", "name": name, "reason": "shape",
                "actual_shape": list(actual_array.shape), "expected_shape": list(expected_array.shape)}
    if actual_array.dtype.kind in "biu" and expected_array.dtype.kind in "biu":
        equal = np.array_equal(actual_array, expected_array)
        return {"status": "PASS" if equal else "FAIL", "name": name,
                "max_absolute_error": 0.0 if equal else None, "tolerance": "exact"}
    actual_float = np.asarray(actual_array, dtype="float64")
    expected_float = np.asarray(expected_array, dtype="float64")
    expected_nan = np.isnan(expected_float)
    actual_nan = np.isnan(actual_float)
    if np.any(expected_nan != actual_nan):
        return {"status": "FAIL", "name": name, "reason": "nan_mismatch",
                "actual_nan_count": int(actual_nan.sum()), "expected_nan_count": int(expected_nan.sum())}
    finite = ~expected_nan
    if not np.any(finite):
        return {"status": "PASS", "name": name, "max_absolute_error": 0.0,
                "tolerance": {"absolute": absolute, "relative": relative}}
    difference = np.abs(actual_float[finite] - expected_float[finite])
    allowed = absolute + relative * np.maximum(1.0, np.abs(expected_float[finite]))
    maximum = float(np.max(difference))
    passed = bool(np.all(difference <= allowed))
    return {"status": "PASS" if passed else "FAIL", "name": name,
            "max_absolute_error": maximum,
            "tolerance": {"absolute": absolute, "relative": relative}}


def _require_replay_domain(expected: Mapping[str, Any]) -> None:
    """Reject real or otherwise unqualified subdomains before reading labels."""
    eligibility = expected.get("evaluation_domain")
    if not isinstance(eligibility, Mapping):
        raise BindingError("operator evaluator requires an explicit evaluation_domain")
    if eligibility.get("kind") != "MANUFACTURED_ANALYTIC_OPERATOR_REPLAY":
        raise BindingError("operator evaluator refuses an unqualified subdomain")
    if eligibility.get("status") != "ELIGIBLE_OPERATOR_REPLAY_ONLY":
        raise BindingError("operator evaluator refuses an unqualified subdomain")
    if eligibility.get("scientific_qualification") != "UNKNOWN":
        raise BindingError("operator replay cannot carry scientific qualification")
    if eligibility.get("hidden_test") is not False:
        raise BindingError("operator evaluator cannot consume a hidden-test claim")


def evaluate_observation_labels(labels: Path | str, expected: Path | str | Mapping[str, Any], *,
                               tolerance_profile: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate a label sidecar against an independent analytic expectation bundle.

    The expectation bundle contains hand-authored particle weights and analytic
    saved-frame results.  This function derives mass-weighted coverage, event
    totals, net flux, repeated crossing mass, censoring mass, and residence
    mass-time from the label, then compares those values to the independent
    expectation.  It does not read the source trajectory, run a model, or
    assign Q-I/Q-N/Q-E qualification.
    """
    label_path = Path(labels).expanduser().resolve()
    if not label_path.is_file():
        raise BindingError(f"label sidecar is unavailable: {label_path}")
    expected_payload = read_json(expected) if isinstance(expected, (Path, str)) else expected
    if not isinstance(expected_payload, Mapping) or expected_payload.get("schema") != (
            "ds02.stage2.manufactured-analytic-expectations.v1"):
        raise BindingError("unsupported analytic expectation bundle")
    _require_replay_domain(expected_payload)

    registered_profile = expected_payload.get("tolerance_profile_sha256")
    expected_profile_digest = canonical_sha256(EVALUATOR_TOLERANCE_PROFILE)
    if registered_profile != expected_profile_digest:
        raise BindingError("analytic expectation tolerance profile is not the registered profile")
    supplied_profile = dict(tolerance_profile or EVALUATOR_TOLERANCE_PROFILE)
    if canonical_sha256(supplied_profile) != expected_profile_digest:
        raise BindingError("tolerance profile differs from the pre-registered profile")
    absolute = float(EVALUATOR_TOLERANCE_PROFILE["absolute"])
    relative = float(EVALUATOR_TOLERANCE_PROFILE["relative"])

    checks: list[dict[str, Any]] = []
    failures: list[str] = []

    particles = expected_payload.get("particles")
    if not isinstance(particles, list) or not particles:
        raise BindingError("analytic expectations require particle weights")
    if any(not isinstance(row, Mapping) or isinstance(row.get("zone"), bool)
           or isinstance(row.get("idp"), bool)
           or not isinstance(row.get("zone"), int) or not isinstance(row.get("idp"), int)
           for row in particles):
        raise BindingError("analytic expectations require typed (Zone,Idp) identities")
    expected_identities = [(int(row["zone"]), int(row["idp"])) for row in particles]
    if len(set(expected_identities)) != len(expected_identities):
        raise BindingError("analytic expectation identities are not unique")
    weights = np.asarray([row.get("initial_mass_kg") if isinstance(row, Mapping) else np.nan
                          for row in particles], dtype="float64")
    initially_active = np.asarray([row.get("initially_active") if isinstance(row, Mapping) else False
                                   for row in particles], dtype=bool)
    if (not np.isfinite(weights).all() or np.any(weights <= 0)
            or len(weights) != len(initially_active)):
        raise BindingError("analytic particle weights must be finite and positive")
    total_mass = float(weights.sum())
    observed_mass = float(weights[initially_active].sum())
    quality_expected = expected_payload.get("quality_weights")
    if not isinstance(quality_expected, Mapping):
        raise BindingError("analytic expectations require quality_weights")
    checks.append(_numeric_check(total_mass, quality_expected.get("initial_fluid_mass_kg"),
                                 "initial_fluid_mass_kg", absolute=absolute, relative=relative))
    checks.append(_numeric_check(observed_mass, quality_expected.get("initially_observed_mass_kg"),
                                 "initially_observed_mass_kg", absolute=absolute, relative=relative))
    checks.append(_numeric_check(observed_mass / total_mass,
                                 quality_expected.get("initially_observed_mass_fraction"),
                                 "initially_observed_mass_fraction", absolute=absolute, relative=relative))
    checks.append(_numeric_check(float(weights[~initially_active].sum()),
                                 quality_expected.get("initially_inactive_mass_kg"),
                                 "initially_inactive_mass_kg", absolute=absolute, relative=relative))

    bindings = expected_payload.get("bindings")
    operator_config = expected_payload.get("operator_config")
    if not isinstance(bindings, Mapping) or not isinstance(operator_config, Mapping):
        raise BindingError("analytic expectations require catalog/source/config bindings")
    binding_names = ("catalog_sha256", "source_catalog_sha256", "source_hdf5_sha256", "case_row_sha256")
    if any(not isinstance(bindings.get(name), str) or not _HEX64.fullmatch(bindings[name]) for name in binding_names):
        raise BindingError("analytic expectation bindings are incomplete")
    normalized_config = validate_label_config(operator_config)
    expected_config_sha256 = canonical_sha256(normalized_config)

    with h5py.File(label_path, "r") as handle:
        expected_attrs = {
            "schema": LABEL_SCHEMA,
            "current_case_id": expected_payload.get("case_id"),
            "current_manifest_sha256": bindings["catalog_sha256"],
            "current_source_catalog_sha256": bindings["source_catalog_sha256"],
            "current_case_row_sha256": bindings["case_row_sha256"],
            "source_hdf5_sha256": bindings["source_hdf5_sha256"],
            "source_hdf5_producer_sha256": bindings["source_hdf5_sha256"],
            "config_sha256": expected_config_sha256,
            "model_invoked": False,
            "qualification_status": "UNKNOWN",
            "q_i_status": "UNKNOWN",
            "q_n_status": "NOT_ASSESSED",
            "q_e_status": "NOT_ASSESSED",
            "complete": True,
        }
        for name, value in expected_attrs.items():
            actual = handle.attrs.get(name)
            if isinstance(actual, bytes):
                actual = actual.decode("utf-8")
            equal = bool(actual == value)
            check = {"status": "PASS" if equal else "FAIL", "name": f"attr.{name}"}
            if not equal:
                check.update(actual=actual, expected=value)
            checks.append(check)

        attr_total = handle.attrs.get("initial_fluid_mass_kg")
        checks.append(_numeric_check(attr_total, quality_expected.get("initial_fluid_mass_kg"),
                                     "attr.initial_fluid_mass_kg", absolute=absolute, relative=relative))
        attr_unknown = handle.attrs.get("initial_source_unknown_mass_kg")
        checks.append(_numeric_check(attr_unknown, quality_expected.get("initial_source_unknown_mass_kg"),
                                     "attr.initial_source_unknown_mass_kg", absolute=absolute, relative=relative))
        if "particle_zone" not in handle or "particle_id" not in handle:
            failures.extend(("missing:particle_zone", "missing:particle_id"))
        else:
            actual_identities = list(zip(np.asarray(handle["particle_zone"][:]).tolist(),
                                         np.asarray(handle["particle_id"][:]).tolist()))
            checks.append(_numeric_check(np.asarray(actual_identities, dtype="int64"),
                                         [list(identity) for identity in expected_identities],
                                         "typed_identity_axis", absolute=absolute, relative=relative))
        if "initial_fluid_mass_kg" in handle:
            checks.append(_numeric_check(handle["initial_fluid_mass_kg"][:], weights.tolist(),
                                         "initial_fluid_mass_kg_by_identity", absolute=absolute, relative=relative))
        else:
            failures.append("missing:initial_fluid_mass_kg")

        datasets = expected_payload.get("datasets")
        if not isinstance(datasets, Mapping):
            raise BindingError("analytic expectations require dataset values")
        for name, expected_value in datasets.items():
            if name not in handle:
                failures.append(f"missing:{name}")
                continue
            checks.append(_numeric_check(handle[name][:], expected_value, name,
                                         absolute=absolute, relative=relative))

        required_names = ("forward_backward_mass_kg", "cumulative_net_flux_kg",
                          "crossing_count", "first_passage_censor", "residence_time_s")
        missing_required = [name for name in required_names if name not in handle]
        if missing_required:
            failures.extend(f"missing:{name}" for name in missing_required)
        else:
            forward_backward = np.asarray(handle["forward_backward_mass_kg"][:], dtype="float64")
            aggregate_expected = expected_payload.get("aggregates")
            if not isinstance(aggregate_expected, Mapping):
                raise BindingError("analytic expectations require aggregate values")
            if forward_backward.ndim != 3 or forward_backward.shape[2] != 2:
                failures.append("forward_backward_event_shape")
                event_count = 0
            else:
                event_count = forward_backward.shape[1]
                if event_count == 0:
                    for name in ("event_forward_backward_mass_kg", "final_net_flux_kg"):
                        value = aggregate_expected.get(name)
                        passed = isinstance(value, list) and not value
                        checks.append({"status": "PASS" if passed else "FAIL",
                                       "name": f"{name}.no_event_scope",
                                       "reason": None if passed else "nonempty_expectation"})
                else:
                    increments = np.diff(np.concatenate((np.zeros_like(forward_backward[:1]), forward_backward), axis=0), axis=0)
                    event_totals = increments.sum(axis=0)
                    checks.append(_numeric_check(event_totals,
                                                 aggregate_expected.get("event_forward_backward_mass_kg"),
                                                 "event_forward_backward_mass_kg", absolute=absolute, relative=relative))
                    net = np.asarray(handle["cumulative_net_flux_kg"][-1], dtype="float64")
                    checks.append(_numeric_check(net, aggregate_expected.get("final_net_flux_kg"),
                                                 "final_net_flux_kg", absolute=absolute, relative=relative))

            crossings = np.asarray(handle["crossing_count"][:], dtype="int64")
            if crossings.ndim != 2:
                failures.append("crossing_event_shape")
                event_count = 0
                crossing_event_count = 0
            else:
                crossing_event_count = crossings.shape[1]
                if crossings.shape[0] != len(weights):
                    failures.append("crossing_identity_axis_shape")
            if crossing_event_count != event_count:
                failures.append("event_axis_mismatch")
            repeated_counts = ((crossings > 1).sum(axis=0).astype("int64")
                               if crossings.ndim == 2 and crossings.shape[0] == len(weights)
                               else np.zeros(0, dtype="int64"))
            repeated_masses = np.asarray([
                float(weights[crossings[:, event_index] > 1].sum())
                for event_index in range(crossing_event_count)
            ], dtype="float64") if crossings.ndim == 2 and crossings.shape[0] == len(weights) else np.zeros(0, dtype="float64")
            checks.append(_numeric_check(repeated_counts,
                                         aggregate_expected.get("repeated_identity_count_by_event"),
                                         "repeated_identity_count_by_event", absolute=absolute, relative=relative))
            checks.append(_numeric_check(repeated_masses,
                                         aggregate_expected.get("repeated_crossing_mass_kg_by_event"),
                                         "repeated_crossing_mass_kg_by_event", absolute=absolute, relative=relative))

            censor_matrix = np.asarray(handle["first_passage_censor"][:], dtype="int64")
            censor_event_count = censor_matrix.shape[1] if censor_matrix.ndim == 2 else 0
            if censor_matrix.ndim == 2 and censor_matrix.shape[0] != len(weights):
                failures.append("censor_identity_axis_shape")
            if censor_event_count != event_count:
                failures.append("censor_event_axis_mismatch")
            observed_masses = np.asarray([
                float(weights[censor_matrix[:, event_index] == 0].sum())
                for event_index in range(censor_event_count)
            ], dtype="float64") if censor_matrix.ndim == 2 and censor_matrix.shape[0] == len(weights) else np.zeros(0, dtype="float64")
            censored_masses = np.asarray([
                float(weights[censor_matrix[:, event_index] != 0].sum())
                for event_index in range(censor_event_count)
            ], dtype="float64") if censor_matrix.ndim == 2 and censor_matrix.shape[0] == len(weights) else np.zeros(0, dtype="float64")
            checks.append(_numeric_check(observed_masses,
                                         aggregate_expected.get("first_passage_observed_mass_kg_by_event"),
                                         "first_passage_observed_mass_kg_by_event", absolute=absolute, relative=relative))
            checks.append(_numeric_check(censored_masses,
                                         aggregate_expected.get("first_passage_censored_mass_kg_by_event"),
                                         "first_passage_censored_mass_kg_by_event", absolute=absolute, relative=relative))

            residence = np.asarray(handle["residence_time_s"][:], dtype="float64")
            if residence.ndim != 2 or residence.shape[0] != len(weights):
                failures.append("residence_identity_axis_shape")
                weighted_residence = np.zeros(0, dtype="float64")
            else:
                weighted_residence = (weights[:, None] * residence).sum(axis=0)
            checks.append(_numeric_check(weighted_residence,
                                         aggregate_expected.get("mass_weighted_residence_kg_s"),
                                         "mass_weighted_residence_kg_s", absolute=absolute, relative=relative))

    for check in checks:
        if check["status"] != "PASS":
            failures.append(check["name"])
    return {
        "schema": EVALUATOR_SCHEMA,
        "status": "PASS_MANUFACTURED_OPERATOR" if not failures else "FAIL_MANUFACTURED_OPERATOR",
        "failures": sorted(set(failures)),
        "label_path": str(label_path),
        "label_sha256": sha256(label_path),
        "expectation_case_id": expected_payload.get("case_id"),
        "tolerance_profile_sha256": expected_profile_digest,
        "checks": checks,
        "model_invoked": False,
        "hidden_test": False,
        "scientific_calibration_status": "UNKNOWN",
        "qualification_status": "UNKNOWN",
        "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "scope": "manufactured analytic operator replay only; no scientific calibration or self-comparison claim",
    }


def _lineage_group_key(row: Mapping[str, Any], evidence: Mapping[str, Any] | None = None) -> str:
    """Return a group key from physical-condition evidence only.

    Generated XML, numerical parameters, particle resolution, and rerun
    attempt hashes are intentionally excluded: they can vary while the same
    physical condition remains in the data lineage.  An empty evidence set is
    a family-wide provisional closure, so unknown cases cannot be separated
    into apparently safe roles.
    """
    evidence = evidence or {}
    tokens = sorted(str(token) for token in evidence.get("tokens", []) if token)
    key = {"family_id": row.get("family_id", "UNKNOWN")}
    key["physical_lineage_tokens"] = tokens or ["PROVISIONAL_UNKNOWN_FAMILY_CLOSURE"]
    return canonical_sha256(key)


def _digest_text(value: Any) -> str | None:
    return str(value) if isinstance(value, str) and _HEX64.fullmatch(value) else None


def _lineage_evidence(case: CurrentCase) -> dict[str, Any]:
    """Read only small CURRENT/manifest provenance for split construction."""
    row = case.row
    family = case.family_id
    tokens: set[str] = set()
    sources: list[str] = []
    direct = row.get("physical_condition_sha256")
    if _digest_text(direct):
        tokens.add(f"{family}:row:physical_condition_sha256:{direct}")
        sources.append("CURRENT.row.physical_condition_sha256")
    header = row.get("header") if isinstance(row.get("header"), Mapping) else {}
    for name in ("physical_condition_sha256", "canonical_physical_condition_sha256",
                 "source_plan_condition_sha256"):
        value = _digest_text(header.get(name))
        if value:
            tokens.add(f"{family}:CURRENT.header:{name}:{value}")
            sources.append(f"CURRENT.header.{name}")

    manifest_spec = row.get("manifest")
    if isinstance(manifest_spec, Mapping):
        manifest_path = case.path(manifest_spec)
        expected = manifest_spec.get("recomputed_sha256") or manifest_spec.get("sha256")
        actual = sha256(manifest_path)
        if expected and actual != expected:
            raise BindingError(f"{case.physical_case_id}: manifest hash differs while building split")
        payload = read_json(manifest_path)
        if (not isinstance(payload, Mapping)
                or (payload.get("family_id") is not None and payload.get("family_id") != family)):
            raise BindingError(f"{case.physical_case_id}: manifest lineage payload is invalid")
        for name in ("physical_condition_sha256", "canonical_physical_condition_sha256",
                     "source_plan_physical_condition_sha256", "classified_physical_condition_sha256"):
            value = _digest_text(payload.get(name))
            if value:
                tokens.add(f"{family}:manifest:{name}:{value}")
                sources.append(f"manifest.{name}")
        condition_id = payload.get("condition_id")
        if isinstance(condition_id, str) and condition_id:
            tokens.add(f"{family}:manifest:condition_id:{condition_id}")
            sources.append("manifest.condition_id")
        # ``case_id`` is the producer's common physical-lineage identifier.
        # It intentionally connects resolution/rerun variants whose
        # per-product condition hashes differ.  It is provenance evidence,
        # not a claim that those products have identical HDF5 contents.
        case_id = payload.get("case_id")
        if isinstance(case_id, str) and case_id:
            tokens.add(f"{family}:manifest:case_id:{case_id}")
            sources.append("manifest.case_id")

    alias = case.accepted_alias_evidence
    canonical = alias.get("canonical_physical_case") if isinstance(alias, Mapping) else None
    if isinstance(canonical, Mapping):
        for name in ("physical_condition_sha256", "source_plan_condition_sha256"):
            value = _digest_text(canonical.get(name))
            if value:
                tokens.add(f"{family}:canonical_alias:{name}:{value}")
                sources.append(f"accepted_alias_evidence.canonical_physical_case.{name}")

    return {
        "status": "EVIDENCE_BOUND" if tokens else "PROVISIONAL_UNKNOWN",
        "tokens": sorted(tokens),
        "sources": sorted(set(sources)),
    }


def _lineage_components(current: Current336Catalog) -> dict[str, dict[str, Any]]:
    """Connect cases sharing physical evidence, closing unknowns by family."""
    cases = list(current.cases())
    parent = {case.physical_case_id: case.physical_case_id for case in cases}
    evidence = {case.physical_case_id: _lineage_evidence(case) for case in cases}

    def root(case_id: str) -> str:
        while parent[case_id] != case_id:
            parent[case_id] = parent[parent[case_id]]
            case_id = parent[case_id]
        return case_id

    def union(left: str, right: str) -> None:
        left_root, right_root = root(left), root(right)
        if left_root != right_root:
            parent[right_root] = left_root

    token_owner: dict[str, str] = {}
    for case in cases:
        for token in evidence[case.physical_case_id]["tokens"]:
            previous = token_owner.get(token)
            if previous is not None:
                union(previous, case.physical_case_id)
            else:
                token_owner[token] = case.physical_case_id

    family_cases: dict[str, list[CurrentCase]] = {}
    for case in cases:
        family_cases.setdefault(case.family_id, []).append(case)
    for family, members in family_cases.items():
        if any(evidence[case.physical_case_id]["status"] != "EVIDENCE_BOUND" for case in members):
            # Unknown lineage is kept with every same-family case.  This is
            # conservative and explicitly provisional rather than leakage-safe.
            first = members[0].physical_case_id
            for case in members[1:]:
                union(first, case.physical_case_id)

    components: dict[str, list[CurrentCase]] = {}
    for case in cases:
        components.setdefault(root(case.physical_case_id), []).append(case)
    result: dict[str, dict[str, Any]] = {}
    for members in components.values():
        family = members[0].family_id
        tokens = sorted({token for case in members for token in evidence[case.physical_case_id]["tokens"]})
        status = ("EVIDENCE_BOUND" if all(evidence[case.physical_case_id]["status"] == "EVIDENCE_BOUND"
                                            for case in members) else "PROVISIONAL_FAMILY_CLOSURE")
        group = _lineage_group_key(members[0].row, {"tokens": tokens if status == "EVIDENCE_BOUND" else []})
        for case in members:
            result[case.physical_case_id] = {
                "group": group,
                "status": status,
                "tokens": tokens,
                "sources": sorted({source for member in members
                                    for source in evidence[member.physical_case_id]["sources"]}),
            }
    return result


def build_prospective_split(catalog: Current336Catalog | Path | str, *, role_by_group: Mapping[str, str] | None = None,
                            output: Path | str | None = None) -> dict[str, Any]:
    """Create a physical-lineage split, provisional when evidence is missing."""
    current = catalog if isinstance(catalog, Current336Catalog) else load_current_catalog(catalog)
    allowed = ("development_train", "development_validation", "development_test")
    overrides = dict(role_by_group or {})
    lineage = _lineage_components(current)
    unknown_override = set(overrides) - {record["group"] for record in lineage.values()}
    if unknown_override:
        raise BindingError("role_by_group contains an unknown lineage group")
    groups: dict[str, str] = {}
    records = []
    for case in current.cases():
        lineage_record = lineage[case.physical_case_id]
        group = lineage_record["group"]
        role = overrides.get(group)
        if role is None:
            bucket = int(group[:8], 16) % 20
            role = allowed[0] if bucket < 14 else allowed[1] if bucket < 17 else allowed[2]
        if role not in allowed:
            raise BindingError(f"unsupported prospective role {role!r}")
        if group in groups and groups[group] != role:
            raise BindingError("one lineage group was assigned to multiple split roles")
        groups[group] = role
        records.append({
            "physical_case_id": case.physical_case_id,
            "family_id": case.family_id,
            "lineage_group": group,
            "lineage_status": lineage_record["status"],
            "lineage_evidence_sources": lineage_record["sources"],
            "role": role,
            "stage1_seen": True,
            "hidden_test": False,
            "task_eligibility": {"observation_labels": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        })
    result = {
        "schema": SPLIT_SCHEMA,
        "current_manifest_sha256": current.sha256,
        "scope": "prospective development roles for the already-seen Stage 1 336; no hidden-test claim",
        "hidden_test": False,
        "lineage_group_count": len(groups),
        "roles": list(allowed),
        "cases": records,
        "split_safety": ("EVIDENCE_BOUND" if all(record["lineage_status"] == "EVIDENCE_BOUND"
                                                   for record in records) else "PROVISIONAL"),
        "leakage_policy": "connect cases through explicit physical-condition/common-lineage evidence; exclude generated XML and numerical hashes; if any family member lacks evidence, close that family into one PROVISIONAL group",
    }
    if output is not None:
        target = Path(output).expanduser().resolve()
        if target.exists():
            raise FileExistsError(f"preserve existing split: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return result


def prepare_sentinel_observation_plan(catalog: Current336Catalog | Path | str, matrix: Path | str,
                                      *, output: Path | str | None = None) -> dict[str, Any]:
    """Bind the 14 sentinel IDs to CURRENT without claiming labels or QN/QE."""
    current = catalog if isinstance(catalog, Current336Catalog) else load_current_catalog(catalog)
    payload = read_json(matrix)
    sentinels = payload.get("sentinels") if isinstance(payload, Mapping) else None
    if not isinstance(sentinels, list) or len(sentinels) != 14:
        raise BindingError("the Stage 2 sentinel matrix must contain exactly 14 entries")
    seen = set()
    records = []
    for sentinel in sentinels:
        sid = sentinel.get("sentinel_id")
        case_id = sentinel.get("source_physical_case_id")
        if sid in seen:
            raise BindingError(f"duplicate sentinel_id {sid}")
        seen.add(sid)
        case = current.case(case_id)
        records.append({
            "sentinel_id": sid,
            "family_id": case.family_id,
            "physical_case_id": case.physical_case_id,
            "current_case_row_sha256": case.row_sha256,
            "trajectory_producer_sha256": case.row["trajectory"]["producer_declared_sha256"],
            "status": "READY_TO_CONFIGURE",
            "label_status": "NOT_MATERIALIZED",
            "observation_role": "development_observation_only",
            "stage1_seen": True,
            "hidden_test": False,
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "must_not_infer": sentinel.get("must_not_infer"),
        })
    result = {"schema": SENTINEL_SCHEMA, "current_manifest_sha256": current.sha256,
              "matrix_status": payload.get("status"), "sentinels": records,
              "scope": "14 sentinel observation bindings only; no batch precision qualification"}
    if output is not None:
        target = Path(output).expanduser().resolve()
        if target.exists():
            raise FileExistsError(f"preserve existing sentinel plan: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return result


LEGACY_CONSUMER_PATHS = (
    "scripts/ds_data02_f1_stage8_labels.py",
    "scripts/ds_data02_f2_stage8_labels.py",
    "scripts/ds_data02_f3_stage8_labels.py",
    "scripts/ds_data02_f3_stage8_audit.py",
    "scripts/ds_data02_f5_stage8_labels.py",
    "scripts/ds_data02_f6_stage8_labels.py",
    "scripts/ds_data02_f7_stage8_labels.py",
)


def audit_legacy_consumers(repo_root: Path | str) -> dict[str, Any]:
    """Report historical discovery/fallback patterns for migration review."""
    root = Path(repo_root).expanduser().resolve()
    lab_root = root / "lagrangian-fluid-lab" if (root / "lagrangian-fluid-lab").is_dir() else root
    rows = []
    for relative in LEGACY_CONSUMER_PATHS:
        path = lab_root / relative
        if not path.is_file():
            rows.append({"path": relative, "status": "MISSING"})
            continue
        text = path.read_text(encoding="utf-8")
        findings = []
        if ".glob(" in text or ".rglob(" in text:
            findings.append("latest_or_glob_discovery")
        if "Run.out" in text:
            findings.append("solver_log_dependency")
        if "STAGE8_CASES" in text or "CASES = [" in text:
            findings.append("fixed_case_list")
        rows.append({"path": relative, "status": "HISTORICAL_DRAFT", "findings": findings,
                     "replacement": "Current336Catalog.case(physical_case_id) and bound execution receipt"})
    return {"schema": "ds02.stage2.legacy-consumer-audit.v1", "rows": rows,
            "policy": "historical scripts remain preserved; Stage 2 consumers never glob, choose arbitrary Run.out, or silently substitute fixed case lists"}


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inspect_parser = sub.add_parser("inspect")
    inspect_parser.add_argument("--catalog", type=Path, required=True)
    inspect_parser.add_argument("--case-id", required=True)
    inspect_parser.add_argument("--verify-source-hash", action="store_true")
    split_parser = sub.add_parser("split")
    split_parser.add_argument("--catalog", type=Path, required=True)
    split_parser.add_argument("--output", type=Path, required=True)
    sentinel_parser = sub.add_parser("sentinels")
    sentinel_parser.add_argument("--catalog", type=Path, required=True)
    sentinel_parser.add_argument("--matrix", type=Path, required=True)
    sentinel_parser.add_argument("--output", type=Path, required=True)
    legacy_parser = sub.add_parser("legacy-audit")
    legacy_parser.add_argument("--repo-root", type=Path, required=True)
    evaluate_parser = sub.add_parser("evaluate")
    evaluate_parser.add_argument("--labels", type=Path, required=True)
    evaluate_parser.add_argument("--expected", type=Path, required=True)
    evaluate_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "inspect":
        current = load_current_catalog(args.catalog)
        print(json.dumps(current.case(args.case_id).inspect(verify_source_hash=args.verify_source_hash), indent=2, ensure_ascii=False))
    elif args.command == "split":
        print(json.dumps(build_prospective_split(args.catalog, output=args.output), indent=2, ensure_ascii=False))
    elif args.command == "sentinels":
        print(json.dumps(prepare_sentinel_observation_plan(args.catalog, args.matrix, output=args.output), indent=2, ensure_ascii=False))
    elif args.command == "evaluate":
        result = evaluate_observation_labels(args.labels, args.expected)
        target = args.output.expanduser().resolve()
        if target.exists():
            raise FileExistsError(f"preserve existing evaluator report: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(audit_legacy_consumers(args.repo_root), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
