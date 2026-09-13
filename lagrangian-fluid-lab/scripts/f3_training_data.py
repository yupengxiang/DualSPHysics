"""Qualified independent development sources and bounded F3 training reads.

Publishing validates actual completed runs, not the existence of candidate CSVs.
Source qualification here does not qualify a learned model or material task.
Canonical states are offline numerical-reference reconstructions. Their right
native bracket can be later than the requested time; no reference reader is
returned to an autonomous rollout, which receives only a copied initial state.
"""

import argparse
from collections import OrderedDict
import copy
import json
import math
import os
from pathlib import Path

import numpy as np

from scripts import f3_nopen_development as development
from scripts.f3_control import AccelerationControl
from scripts.f3_nopen_stage_score import CachedSource, TIME_ALIGNMENT, target_grid
from scripts.f3_timestep_evidence import evidence as timestep_evidence
from scripts.l1r_continuation_evidence import LAB, OUT
from scripts.l1r_q2_mdbc_bridge import atomic_json, sha256, utc_now

SCHEMA = "f3.training.development_data.v1"
CONTRACTS = {"pilot": "F3-TRAINING-DEVELOPMENT-PILOT.json",
             "full": "F3-TRAINING-DEVELOPMENT-FULL.json"}
INTERVAL = .01
HORIZON = 8.35
PROGRAMS = ("f3_training_data.py", "f3_nopen_development.py", "f3_nopen_qualification.py",
            "f3_control.py", "f3_nopen_stage_score.py", "f3_reference_score.py",
            "f3_timestep_evidence.py")

# The ref0081818 worker can opt into a bounded in-memory cache for its complete
# canonical frame axis.  The cache is process-local and keyed by the immutable
# source path, so it never changes the source contract or crosses attempts.
# Keeping the switch behind an environment variable leaves contract publishing
# and the small CPU fixtures on the original two-frame HDF5 cache.
_PREFETCH_CACHE: dict[str, dict[str, object]] = {}
_PREFETCH_ACTIVE = False
_GPU_CACHE_ACTIVE = True


def enable_training_prefetch() -> None:
    """Enable the ref0081818 frame cache after its contract has been checked."""
    global _PREFETCH_ACTIVE
    _PREFETCH_ACTIVE = True


def disable_training_gpu_cache() -> None:
    """Disable CUDA batches before the independent NumPy scorer runs.

    The complete frame cache remains available for audit/replay, but evaluation
    must receive host arrays so that it cannot accidentally use training tensors
    or pass CUDA tensors into NumPy metrics.
    """
    global _GPU_CACHE_ACTIVE
    _GPU_CACHE_ACTIVE = False


def install_training_loader_cache(loader) -> None:
    """Keep revision-bound source handles alive across shuffled transitions."""
    if os.environ.get("F3_TRAINING_PREFETCH") != "1" or not hasattr(loader, "_sources"):
        return
    from types import MethodType
    from scripts.f3_control import AccelerationControl
    from scripts import f3_ref0081818_training_data as revision

    references = {}

    def cached_open(self, case_id):
        if self._closed:
            raise ValueError("loader is closed")
        if case_id not in self._rows:
            raise ValueError("case is not present in the verified development contract")
        source = self._sources[case_id]
        for path in (source["hdf5_path"], source["control_path"]):
            if legacy_token(path) != self._tokens[path]:
                raise ValueError("verified source changed after loader was opened")
        if case_id not in references:
            reference = revision._Reference(source)
            try:
                control = AccelerationControl.from_csv(source["control_path"])
                control.values.setflags(write=False)
                control.integrated.setflags(write=False)
            except BaseException:
                reference.close()
                raise
            references[case_id] = (reference, control)
        self._reference, self._control = references[case_id]
        self._reference_case = case_id
        return self._reference

    def cached_close(self):
        for reference, _ in references.values():
            reference.close()
        references.clear()
        self._reference = self._reference_case = self._control = None
        self._closed = True

    # Keep the token helper local to avoid changing the revision contract's
    # module imports while still checking every immutable source on each use.
    def legacy_token(path):
        stat = Path(path).stat()
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns

    loader._open = MethodType(cached_open, loader)
    loader.close = MethodType(cached_close, loader)


def _read(path):
    return json.loads(Path(path).read_text())


def _relative(path):
    return str(Path(path).resolve().relative_to(LAB.resolve()))


def _path(relative):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError("source evidence must use LAB-relative paths")
    result = (LAB / relative).resolve()
    result.relative_to(LAB.resolve())
    return result


def _contract_path(path):
    result = Path(path)
    if not result.is_absolute():
        result = LAB / result
    result = result.resolve()
    result.relative_to(LAB.resolve())
    return result


def _bind(bindings, path, expected=None):
    digest = sha256(Path(path))
    if expected is not None and digest != expected:
        raise ValueError("changed source evidence: " + _relative(path))
    relative = _relative(path)
    if relative in bindings and bindings[relative] != digest:
        raise ValueError("source changed during contract verification: " + relative)
    bindings[relative] = digest
    return dict(path=relative, sha256=digest)


def _bind_json(bindings, path, value):
    item = _bind(bindings, path)
    if _read(path) != value:
        raise ValueError("verified source JSON changed during contract construction")
    return item


def _verify_bindings(bindings):
    if not isinstance(bindings, dict) or not bindings:
        raise ValueError("development contract requires bound source evidence")
    for relative, digest in bindings.items():
        if not isinstance(digest, str) or sha256(_path(relative)) != digest:
            raise ValueError("contract source evidence changed: " + relative)


def _selected(scope, context):
    if scope not in CONTRACTS:
        raise ValueError("contract scope must be pilot or full")
    rows = context["manifest"]["cases"]
    selected = rows if scope == "full" else [r for r in rows if r["pilot"]]
    expected = 32 if scope == "full" else 8
    if len(selected) != expected or len({r["case_id"] for r in selected}) != expected:
        raise ValueError("all original manifest cases in the selected scope are required")
    return selected


def _source(row, context, bindings):
    name = row["case_id"]
    # The shared context validates the entire domain/registry exactly once.
    # This is the same complete per-case guard as verified_development().
    record, audit, solver = development._verified_development(name, context)
    sources = {}
    for suffix, value in (("PREPARED", record), ("AUDIT", audit), ("SOLVER", solver)):
        sources[suffix.lower()] = _bind_json(bindings, OUT / f"{name}-{suffix}.json", value)
    preflight_path = OUT / f"{name}-INPUT-PREFLIGHT.json"
    preflight = _read(preflight_path)
    prefix = _path(record["generated_prefix"])
    control_path = prefix.parent / "CaseSloshingAccData.csv"
    parser = preflight.get("native_reader", {})
    nominal = context["nominal"]
    if (preflight.get("status") != "passed"
            or _path(preflight["asset"]["path"]) != control_path.resolve()
            or preflight["asset"]["sha256"] != row["control_file_sha256"]
            or preflight["asset"]["sha256"] != record["drive_sha256"]
            or preflight["source"]["sha256"] != context["manifest"]["source_drive_sha256"]
            or parser.get("first_time_s") != 0 or parser.get("last_time_s") != HORIZON
            or parser.get("rows") != len(nominal)):
        raise ValueError("development input preflight does not verify the exact complete control")
    sources["input_preflight"] = _bind_json(bindings, preflight_path, preflight)
    sources["control"] = _bind(bindings, control_path, record["drive_sha256"])
    sources["registered_control"] = _bind(bindings, _path(row["control_path"]), row["control_file_sha256"])
    _bind(bindings, _path(preflight["source"]["path"]), preflight["source"]["sha256"])
    # The complete hard source guard has already hashed this HDF5 and all assets.
    # Preserve those checked bytes; the publisher rechecks bindings before write.
    sources["hdf5"] = dict(path=_relative(_path(audit["hdf5"])), sha256=audit["hdf5_sha256"])
    bindings[sources["hdf5"]["path"]] = audit["hdf5_sha256"]
    for filename, digest in record["input_assets"].items():
        bindings[_relative(prefix.parent / filename)] = digest
    sources["native_log"] = _bind(bindings, Path(solver["attempt_directory"]) / "Run.out")
    native = timestep_evidence(name)
    if (native.get("case") != name or native.get("total_steps", 0) <= 0
            or not all(math.isfinite(native[k]) and native[k] > 0 for k in ("dt_min_s", "dt_max_s"))
            or native["dt_min_s"] > native["dt_max_s"]):
        raise ValueError("actual native timestep evidence is required for canonical reconstruction")
    sources["native_timestep"] = _bind(bindings, _path(native["csv_path"]), native["csv_sha256"])
    summary = copy.deepcopy(row)
    summary.update(hard_audit_passed=True, sources=sources, native_timestep=native,
                   native_frames=audit["frames"], particle_axis_count=audit["particle_axis_count"],
                   initial_fluid_mass_kg=audit["initial_fluid_mass_kg"], native_time_end_s=audit["time_end_s"])
    source = dict(case_id=name, record=record, audit=audit, solver=solver,
                  native_timestep=native, hdf5_path=_path(audit["hdf5"]),
                  entry={"output_interval_s": INTERVAL}, control_path=control_path)
    # Inspect only the initial native state plus all scalar/identity axes here.
    # Integrity of the full run is bound by its complete hard audit/HDF5 digest.
    with _Reference(source):
        pass
    return summary, source


def _collect(scope):
    context = development._context(register=False)
    rows = _selected(scope, context)
    gate = context["gate"]
    bindings = dict(gate["evidence_sha256"])
    gate_ref = _bind_json(bindings, OUT / development.DOMAIN_GATE, gate)
    registry_ref = _bind_json(bindings, OUT / development.REGISTRY, context["registry"])
    manifest_ref = _bind_json(bindings, OUT / development.MANIFEST, context["manifest"])
    for item in context["registry"]["evidence"]:
        _bind(bindings, _path(item["path"]), item["sha256"])
    initial = context["registry"]["initial_source"]
    prefix = _path(initial["prefix"])
    for filename, digest in initial["assets"].items():
        _bind(bindings, prefix.parent / filename, digest)
    for name in PROGRAMS:
        _bind(bindings, LAB / "scripts" / name)
    if bindings[_relative(LAB / "scripts/f3_training_data.py")] != sha256(Path(__file__)):
        raise ValueError("contract program differs from the executing loader")
    cases, sources = [], {}
    for row in rows:
        summary, source = _source(row, context, bindings)
        cases.append(summary)
        sources[row["case_id"]] = source
    result = dict(schema=SCHEMA, scope=scope, status="passed", recipe_id=development.RECIPE,
                  qualified_sources=True, completed_case_ids=[c["case_id"] for c in cases],
                  source_domain_gate=gate_ref, development_registry=registry_ref,
                  candidate_manifest=manifest_ref, cases=cases,
                  production_resolution_m=gate["production_resolution_m"],
                  time_window_s=gate["time_window_s"], scoring_interval_s=gate["scoring_interval_s"],
                  canonical_frame_count=len(target_grid(INTERVAL)), time_alignment=TIME_ALIGNMENT,
                  velocity_convention="Native initial velocity; thereafter previous canonical position difference divided by 0.01 s",
                  target_convention="Next canonical position minus current canonical position; supervision only",
                  split_semantics="Original manifest roles: train optimization, validation interpolation, test public development extrapolation",
                  identity_convention="Full immutable native particle IDs and per-ID masses; no survivor filtering",
                  model_qualified=False, material_layers_qualified=[], formal_release=False,
                  evidence_sha256=dict(sorted(bindings.items())))
    return result, sources


def publish_development_contract(scope="pilot", *, path=None):
    """Explicit publication entry point; never runs a solver, training or a ledger."""
    if scope not in CONTRACTS:
        raise ValueError("contract scope must be pilot or full")
    target = _contract_path(path if path is not None else OUT / CONTRACTS[scope])
    if target.exists():
        existing = validate_development_contract(target)
        if existing["scope"] != scope:
            raise ValueError("existing immutable development contract has another scope")
        return existing
    value, _ = _collect(scope)
    _verify_bindings(value["evidence_sha256"])
    value["recorded_at_utc"] = utc_now()
    if target.exists():
        raise ValueError("contract appeared during verification; refusing to replace it")
    atomic_json(target, value)
    return value


def _validated(path):
    path = _contract_path(path)
    raw = _read(path)
    if (not isinstance(raw, dict) or raw.get("schema") != SCHEMA or raw.get("scope") not in CONTRACTS
            or raw.get("status") != "passed" or raw.get("qualified_sources") is not True
            or not isinstance(raw.get("recorded_at_utc"), str) or not raw["recorded_at_utc"]):
        raise ValueError("an actually completed qualified development data contract is required")
    expected, sources = _collect(raw["scope"])
    saved = {k: v for k, v in raw.items() if k != "recorded_at_utc"}
    if saved != expected:
        raise ValueError("development contract differs from current actual runs, roles or source evidence")
    if _read(path) != raw:
        raise ValueError("development contract changed while being verified")
    return raw, sources


def validate_development_contract(path):
    """Read-only substantive verification, including all actual selected sources."""
    return _validated(path)[0]


def loader_for_contract(path, *, legacy_loader=None):
    """Dispatch a verified loader by the contract's immutable recipe identity.

    The historical loader remains the default for its own recipe.  The
    ref0081818 recipe is handed to its revision-bound adapter; an unknown
    recipe fails closed instead of silently reading data through the old
    ``f3_nopen_development`` gate.
    """
    # Read the recipe before constructing the loader.  The worker's isolated
    # CPU tests inject a manufactured legacy loader rooted outside LAB; keep
    # that test seam while the real loaders still enforce their own LAB-bound
    # contract path checks.
    contract_path = Path(path)
    if not contract_path.is_absolute():
        contract_path = LAB / contract_path
    contract_path = contract_path.resolve()
    raw = _read(contract_path)
    recipe = raw.get("recipe_id")
    if recipe == development.RECIPE:
        return (QualifiedF3Loader if legacy_loader is None else legacy_loader)(contract_path)
    # Only an explicitly injected test double may consume a manufactured
    # contract without a recipe.  The production worker passes the real class
    # object, so a missing identity still fails closed there.
    if recipe is None and legacy_loader is not None and legacy_loader is not QualifiedF3Loader:
        return legacy_loader(contract_path)
    from scripts import f3_ref0081818_training_data as revision
    if recipe == revision.RECIPE:
        return revision.QualifiedF3Loader(contract_path)
    raise ValueError("training contract recipe is not registered")


def _token(path):
    stat = Path(path).stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


class _Reference(CachedSource):
    """At most two native and two canonical states of one complete physical case."""

    def __init__(self, source):
        super().__init__(source)
        self.canonical = OrderedDict()
        self.grid = target_grid(INTERVAL)
        self._prefetched = None
        self._gpu_prefetched = None
        try:
            if not np.issubdtype(self.ids.dtype, np.integer):
                raise ValueError("native particle IDs must be integral")
            shape = (len(self.times), len(self.ids))
            for key in ("position", "velocity", "mass", "valid", "type"):
                if self.h5[key].shape != shape + ((3,) if key in ("position", "velocity") else ()):
                    raise ValueError("HDF5 must retain the entire complete native identity axis")
            for values in (self.ids, self.mass, self.times, self.grid):
                values.setflags(write=False)
            # Only the revision-bound ref0081818 subclass opts into this path.
            # It keeps all canonical states for a case in RAM after the first
            # sequential read, avoiding a full HDF5 frame read on every update.
            if (_PREFETCH_ACTIVE and os.environ.get("F3_TRAINING_PREFETCH") == "1"
                    and self.__class__.__module__.endswith("f3_ref0081818_training_data")):
                key = str(Path(source["hdf5_path"]).resolve())
                cached = _PREFETCH_CACHE.get(key)
                if cached is None:
                    # Read each native dataset once.  The original bounded
                    # reader is intentionally frame-by-frame; that is useful
                    # for audit code but turns a 16k-step training pass into
                    # thousands of random HDF5 reads.  This path performs the
                    # same validity and linear interpolation checks in chunks.
                    native_position = self.h5["position"][:].astype(float)
                    native_velocity = self.h5["velocity"][:].astype(float)
                    native_valid = self.h5["valid"][:]
                    native_type = self.h5["type"][:]
                    native_mass = self.h5["mass"][:].astype(float)
                    if (not native_valid.all() or not (native_type == 3).all()
                            or not np.isfinite(native_position).all()
                            or not np.isfinite(native_velocity).all()
                            or native_mass.shape != (len(self.times), len(self.ids))
                            or not np.isfinite(native_mass).all()
                            or not np.all(native_mass == self.mass[None, :])):
                        raise ValueError("prefetched source contains an invalid complete-axis state")
                    left = np.searchsorted(self.times, self.grid, side="right") - 1
                    left = np.clip(left, 0, len(self.times) - 1)
                    right = np.minimum(left + 1, len(self.times) - 1)
                    denominator = self.times[right] - self.times[left]
                    weight = np.divide(self.grid - self.times[left], denominator,
                                       out=np.zeros_like(self.grid), where=denominator != 0)
                    states = {}
                    for start in range(0, len(self.grid), 64):
                        stop = min(len(self.grid), start + 64)
                        w = weight[start:stop, None, None]
                        p = ((1.0 - w) * native_position[left[start:stop]]
                             + w * native_position[right[start:stop]])
                        v = ((1.0 - w) * native_velocity[left[start:stop]]
                             + w * native_velocity[right[start:stop]])
                        for offset, index in enumerate(range(start, stop)):
                            pi, vi = p[offset].copy(), v[offset].copy()
                            pi.setflags(write=False); vi.setflags(write=False)
                            states[index] = (pi, vi, self.mass,
                                             [float(self.times[left[index]]),
                                              float(self.times[right[index]])])
                    del native_position, native_velocity, native_valid, native_type, native_mass
                    cached = {"states": states, "gpu": None}
                    _PREFETCH_CACHE[key] = cached
                self._prefetched = cached["states"]
                if os.environ.get("F3_TRAINING_GPU_CACHE") == "1":
                    import torch
                    if torch.cuda.is_available():
                        gpu = cached.get("gpu")
                        if gpu is None:
                            # The worker uses one visible device (cuda:0). A
                            # GPU batch retains the complete axis while making
                            # each update independent of host-to-device copies.
                            gpu = {}
                            for index in range(len(self.grid) - 1):
                                p = self._prefetched[index][0]
                                if index == 0:
                                    velocity = self._prefetched[index][1]
                                else:
                                    velocity = (p - self._prefetched[index - 1][0]) / INTERVAL
                                target = self._prefetched[index + 1][0] - p
                                gpu[index] = (
                                    torch.as_tensor(p, dtype=torch.float32, device="cuda:0"),
                                    torch.as_tensor(velocity, dtype=torch.float32, device="cuda:0"),
                                    torch.as_tensor(target, dtype=torch.float32, device="cuda:0"),
                                )
                            cached["gpu"] = gpu
                        self._gpu_prefetched = gpu
        except BaseException:
            self.close()
            raise

    def canonical_state(self, index):
        if self._prefetched is not None:
            try:
                p, v, mass, bracket = self._prefetched[index]
            except KeyError as error:
                raise ValueError("canonical frame outside the fixed qualified grid") from error
            return dict(position=p, native_velocity=v, mass=mass,
                        native_bracket_s=list(bracket))
        if index in self.canonical:
            self.canonical.move_to_end(index)
            return self.canonical[index]
        if not isinstance(index, (int, np.integer)) or isinstance(index, (bool, np.bool_)) or not 0 <= index < len(self.grid):
            raise ValueError("canonical frame outside the fixed qualified grid")
        p, v, mass, bracket = self.state(float(self.grid[index]))
        for array in (p, v, mass):
            array.setflags(write=False)
        state = dict(position=p, native_velocity=v, mass=mass, native_bracket_s=bracket)
        self.canonical[index] = state
        while len(self.canonical) > 2:
            self.canonical.popitem(last=False)
        return state

    def gpu_batch(self, index):
        if (not _GPU_CACHE_ACTIVE or self._gpu_prefetched is None
                or index not in self._gpu_prefetched):
            return None
        return self._gpu_prefetched[index]


class QualifiedF3Loader:
    """Train-only optimization callable with explicit separate evaluation reads.

    Transition.frame is a canonical 0.01 s grid index, not a native output index.
    Batches contain complete NumPy particle axes; the core handles device/dtype
    conversion and target-row sampling. Reference caches are bounded to one case.
    """

    def __init__(self, contract_path=None):
        path = OUT / CONTRACTS["full"] if contract_path is None else contract_path
        self.contract_path = _contract_path(path)
        self.contract, self._sources = _validated(self.contract_path)
        self.contract_sha256 = sha256(self.contract_path)
        self._rows = {row["case_id"]: row for row in self.contract["cases"]}
        self._tokens = {path: _token(path) for source in self._sources.values()
                        for path in (source["hdf5_path"], source["control_path"])}
        self._reference = None
        self._reference_case = None
        self._control = None
        self._closed = False
        self.times = target_grid(INTERVAL)
        self.times.setflags(write=False)

    def case_ids(self, split):
        if split not in ("train", "validation", "test"):
            raise ValueError("split must be train, validation, or public development test")
        return tuple(row["case_id"] for row in self.contract["cases"] if row["split"] == split)

    def _case(self, case_id, *, optimization):
        if self._closed:
            raise ValueError("loader is closed")
        if case_id not in self._rows:
            raise ValueError("case is not completed in the verified development contract")
        if optimization and self._rows[case_id]["split"] != "train":
            raise ValueError("validation/public development test cannot enter optimization transitions")
        return self._rows[case_id]

    def _frame(self, frame):
        if (not isinstance(frame, (int, np.integer)) or isinstance(frame, (bool, np.bool_))
                or not 0 <= frame < len(self.times) - 1):
            raise ValueError("transition needs current and next canonical frames inside 0..8.35 s")
        return int(frame)

    def _clear_reference(self):
        if self._reference is not None:
            self._reference.close()
        self._reference = self._reference_case = self._control = None

    def _open(self, case_id):
        source = self._sources[case_id]
        for path in (source["hdf5_path"], source["control_path"]):
            if _token(path) != self._tokens[path]:
                raise ValueError("verified source changed after the loader was opened")
        if case_id != self._reference_case:
            self._clear_reference()
            reference = _Reference(source)
            try:
                control = AccelerationControl.from_csv(source["control_path"])
                control.values.setflags(write=False)
                control.integrated.setflags(write=False)
            except BaseException:
                reference.close()
                raise
            self._reference, self._control = reference, control
            self._reference_case = case_id
        return self._reference

    def _input(self, case_id, frame, *, optimization):
        row = self._case(case_id, optimization=optimization)
        frame = self._frame(frame)
        reference = self._open(case_id)
        gpu_batch = reference.gpu_batch(frame)
        if gpu_batch is not None:
            position, velocity, _ = gpu_batch
            return dict(position=position, velocity=velocity,
                        particle_id=reference.ids, time_s=float(self.times[frame]),
                        interval_s=INTERVAL, dp_m=self.contract["production_resolution_m"],
                        amplitude=row["drive_amplitude"], control=self._control)
        previous = reference.canonical_state(frame - 1) if frame else None
        current = reference.canonical_state(frame)
        velocity = (current["native_velocity"] if previous is None
                    else (current["position"] - previous["position"]) / INTERVAL)
        # Copies prevent a model/optimizer from mutating the reference cache.
        return dict(position=current["position"].copy(), velocity=velocity.copy(),
                    particle_id=reference.ids.copy(), time_s=float(self.times[frame]),
                    interval_s=INTERVAL, dp_m=self.contract["production_resolution_m"],
                    amplitude=row["drive_amplitude"], control=self._control)

    def current_input(self, case_id, frame):
        """Optimization input only; this method never requests the next target."""
        return self._input(case_id, frame, optimization=True)

    def _target(self, case_id, frame, *, optimization):
        self._case(case_id, optimization=optimization)
        frame = self._frame(frame)
        reference = self._open(case_id)
        gpu_batch = reference.gpu_batch(frame)
        if gpu_batch is not None:
            return gpu_batch[2]
        current = reference.canonical_state(frame)["position"]
        following = reference.canonical_state(frame + 1)["position"]
        return following - current

    def target_displacement(self, case_id, frame):
        """Read the separate supervised label; it is never a rollout input."""
        return self._target(case_id, frame, optimization=True)

    def _batch(self, transition, *, optimization):
        from scripts.f3_training_core import TransitionBatch

        fields = self._input(transition.case_id, transition.frame, optimization=optimization)
        target = self._target(transition.case_id, transition.frame, optimization=optimization)
        return TransitionBatch(**fields, target_displacement=target)

    def __call__(self, transition):
        return self._batch(transition, optimization=True)

    def evaluation_batch(self, transition):
        """Explicit reference-supervised evaluation; not an autonomous rollout."""
        if self._case(transition.case_id, optimization=False)["split"] not in ("validation", "test"):
            raise ValueError("evaluation_batch requires a validation or public development test case")
        return self._batch(transition, optimization=False)

    def _transitions(self, split, case_ids, frames, target_indices):
        from scripts.f3_training_core import Transition

        allowed = self.case_ids(split)
        selected = allowed if case_ids is None else tuple(case_ids)
        if len(set(selected)) != len(selected) or any(name not in allowed for name in selected):
            raise ValueError("transition catalog must retain the requested original split")
        indices = tuple(range(len(self.times) - 1)) if frames is None else tuple(self._frame(f) for f in frames)
        if len(set(indices)) != len(indices):
            raise ValueError("duplicate canonical transitions are not a distinct data catalog")
        targets = None if target_indices is None else tuple(target_indices)
        if targets is not None:
            if (not targets or len(set(targets)) != len(targets)
                    or any(not isinstance(i, (int, np.integer)) or isinstance(i, (bool, np.bool_)) for i in targets)
                    or any(i < 0 or i >= self._rows[name]["particle_axis_count"] for name in selected for i in targets)):
                raise ValueError("target_indices must be unique stable particle row indices")
            targets = tuple(int(i) for i in targets)
        return tuple(Transition(case_id=name, frame=frame, target_indices=targets)
                     for name in selected for frame in indices)

    def optimization_transitions(self, *, case_ids=None, frames=None, target_indices=None):
        return self._transitions("train", case_ids, frames, target_indices)

    def evaluation_transitions(self, split, *, case_ids=None, frames=None, target_indices=None):
        if split not in ("validation", "test"):
            raise ValueError("evaluation catalog must use validation or public development test")
        return self._transitions(split, case_ids, frames, target_indices)

    def rollout_initial(self, case_id):
        """Detach copied frame-zero data and known control, retaining no fluid cache.

        The caller constructs its autonomous model state from this dict. There is
        deliberately no returned loader, HDF5 handle, target or future fluid data.
        """
        row = self._case(case_id, optimization=False)
        self._clear_reference()
        reference = self._open(case_id)
        try:
            initial = reference.canonical_state(0)
            return dict(position=initial["position"].copy(), velocity=initial["native_velocity"].copy(),
                        particle_id=reference.ids.copy(), mass=reference.mass.copy(), time_s=0.,
                        interval_s=INTERVAL, dp_m=self.contract["production_resolution_m"],
                        amplitude=row["drive_amplitude"], control=self._control)
        finally:
            self._clear_reference()

    def close(self):
        self._clear_reference()
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    publish = commands.add_parser("publish")
    publish.add_argument("--scope", choices=tuple(CONTRACTS), required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("path")
    args = parser.parse_args(argv)
    result = (publish_development_contract(args.scope) if args.action == "publish"
              else validate_development_contract(args.path))
    print(json.dumps({key: result[key] for key in ("schema", "scope", "completed_case_ids", "qualified_sources", "model_qualified")}), flush=True)


if __name__ == "__main__":
    main()
