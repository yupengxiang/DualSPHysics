#!/usr/bin/env python3
"""Budget and prepare a read-only F4 domain-extension diagnostic.

The laminar F4 matrix already contains two distinct fine-grid failures.  The
q=.75 failure has native position exclusions at the registered domain floor;
the q=.25 failure is a finite-container top-edge event with no native loss.
This module keeps those mechanisms separate.  It projects only the ten native
excluded q=.75 particles, computes the DualSPHysics cell allocation for a
domain large enough to contain that projection through 4.34 s, and can build
one fresh CPU-prepared q=.75 extension candidate.  It never edits an existing
prepared case and never launches a solver.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

import h5py
import numpy as np


SCHEMA = "core.f4.domain_extension.v1"
HORIZON_S = 4.34
GRAVITY_Z_M_S2 = -9.81
DOMAIN_MARGIN_M = {"x": 0.0, "y": 0.16, "z": 0.20}
LAB = Path(__file__).resolve().parents[1]
Q025_PREPARED = LAB / "campaigns/core-v1/cfd/prepared/F4_resting_pool_laminar_qualification_v1/cell-10/prepared.json"
Q075_PREPARED = LAB / "campaigns/core-v1/cfd/prepared/F4_resting_pool_laminar_qualification_v1/cell-12/prepared.json"
Q025_AUDIT = LAB / "campaigns/core-v1/runtime/attempts/f4-laminar-qualification-cell-10/20260919T195624-08f5d07ea433/product/audit.json"
Q075_AUDIT = LAB / "campaigns/core-v1/runtime/attempts/f4-laminar-qualification-cell-12/20260919T195625-d02c9bebf080/product/audit.json"
Q075_NATIVE = LAB / "campaigns/core-v1/cfd/f4-laminar-q075-native-exclusions-v1/evidence.json"
Q075_LOSS_PATHS = LAB / "campaigns/core-v1/cfd/f4-laminar-q075-fine-loss-paths-v1.json"
Q025_FORENSICS = LAB / "campaigns/core-v1/cfd/f4-laminar-q025-inward-chord-probe-v1.json"
Q025_ENDPOINT = LAB / "campaigns/core-v1/cfd/f4-laminar-q025-fine-endpoint-forensics-v1.json"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def element_digest(path: Path, expression: str) -> str:
    """Hash a parsed XML subtree independent of indentation and XML headers."""
    node = ET.parse(path).getroot().find(expression)
    if node is None:
        raise ValueError(f"missing XML subtree {expression} in {path}")
    return hashlib.sha256(ET.tostring(node, encoding="utf-8")).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _float(text: str) -> float:
    return float(str(text).strip().replace("E", "e"))


def generated_xml(prepared: dict) -> Path:
    return Path(prepared["generated_prefix"] + ".xml").resolve()


def parse_domain_and_cell(prepared: dict) -> dict:
    path = generated_xml(prepared)
    root = ET.parse(path).getroot()
    domain = root.find(".//simulationdomain")
    if domain is None:
        raise ValueError(f"missing simulationdomain in {path}")
    low = [float(domain.find("posmin").get(axis)) for axis in "xyz"]
    high = [float(domain.find("posmax").get(axis)) for axis in "xyz"]
    constants = root.find(".//constants")
    dp = float(constants.find("dp").get("value"))
    h = float(constants.find("h").get("value"))
    fluid = root.findall(".//particles/fluid")
    fixed = root.findall(".//particles/fixed")
    return dict(
        generated_xml=str(path),
        generated_xml_sha256=digest(path),
        domain_low_m=low,
        domain_high_m=high,
        dp_m=dp,
        h_m=h,
        cell_size_m=2.0 * h,
        fluid_particles=sum(int(node.get("count")) for node in fluid),
        boundary_particles=sum(int(node.get("count")) for node in fixed),
        total_particles=int(root.find(".//particles").get("np")),
    )


def cell_allocation(domain_low: list[float], domain_high: list[float], cell_size_m: float) -> dict:
    low = np.asarray(domain_low, dtype=float)
    high = np.asarray(domain_high, dtype=float)
    if low.shape != (3,) or high.shape != (3,) or not np.isfinite(np.r_[low, high]).all():
        raise ValueError("domain bounds must be three finite coordinates")
    if np.any(high <= low) or not math.isfinite(cell_size_m) or cell_size_m <= 0:
        raise ValueError("invalid domain or cell size")
    counts = np.ceil((high - low) / float(cell_size_m)).astype(np.int64)
    return dict(
        low_m=low.tolist(), high_m=high.tolist(), span_m=(high - low).tolist(),
        cell_size_m=float(cell_size_m), counts=counts.tolist(),
        allocated_cells=int(np.prod(counts, dtype=np.int64)),
    )


def _csv_memory(product: Path) -> dict:
    path = Path(product) / "solver/RunPARTs.csv"
    rows = []
    with path.open(newline="") as stream:
        for row in csv.DictReader(stream, delimiter=";"):
            if row.get("Part", "").isdigit():
                rows.append(row)
    if not rows:
        raise ValueError(f"no numeric RunPARTs rows in {path}")

    def number(row: dict, key: str) -> float:
        return float(row[key].replace(",", ""))

    peak = max(rows, key=lambda row: number(row, "MemGPU [MiB]"))
    first = rows[0]
    return dict(
        source=str(path), source_sha256=digest(path), rows=len(rows),
        baseline_initial=dict(
            gpu_mib=number(first, "MemGPU [MiB]"),
            gpu_cells_mib=number(first, "MemGPU_Cells [MiB]"),
            cpu_mib=number(first, "MemCPU [MiB]"),
            allocated_particles=int(number(first, "NpAlloc")),
            allocated_cells=int(number(first, "NctAlloc")),
        ),
        peak=dict(
            gpu_mib=number(peak, "MemGPU [MiB]"),
            gpu_cells_mib=number(peak, "MemGPU_Cells [MiB]"),
            cpu_mib=number(peak, "MemCPU [MiB]"),
            allocated_particles=int(number(peak, "NpAlloc")),
            allocated_cells=int(number(peak, "NctAlloc")),
            time_s=number(peak, "TimeStep [s]"),
        ),
    )


def _partout_rows(evidence: dict) -> list[dict]:
    rows = []
    for row in evidence["rows"]:
        rows.append(dict(
            particle_id=int(row["Idp"]),
            position_m=[_float(row[f"Pos.{axis} [m]"]) for axis in "xyz"],
            velocity_mps=[_float(row[f"Vel.{axis} [m/s]"]) for axis in "xyz"],
            motive=int(row["Motive"]),
            rhop_kg_m3=_float(row["Rhop [kg/m^3]"]),
        ))
    return rows


def ballistic_projection(rows: list[dict], source_time_s: float, horizon_s: float,
                         gravity_z_m_s2: float = GRAVITY_Z_M_S2) -> dict:
    dt = float(horizon_s) - float(source_time_s)
    if dt <= 0 or not math.isfinite(dt):
        raise ValueError("horizon must follow the source time")
    projected = []
    for row in rows:
        p = np.asarray(row["position_m"], dtype=float)
        v = np.asarray(row["velocity_mps"], dtype=float)
        q = p + v * dt
        q[2] += 0.5 * float(gravity_z_m_s2) * dt * dt
        projected.append(dict(row, projected_position_m=q.tolist(), projection_dt_s=dt))
    positions = np.asarray([row["projected_position_m"] for row in projected], dtype=float)
    return dict(
        source_time_s=float(source_time_s), horizon_s=float(horizon_s), dt_s=dt,
        gravity_z_m_s2=float(gravity_z_m_s2), particle_count=len(projected),
        projected_bbox_m=dict(min=positions.min(axis=0).tolist(), max=positions.max(axis=0).tolist()),
        particles=projected,
    )


def _energy_tail(native: dict, native_rows: list[dict], prepared: dict) -> dict:
    product = Path(prepared["generated_prefix"]).parents[2]
    # The prepared case's generated path is under .../cell-12/generated/name.
    # Locate its immutable trajectory from the registered attempt instead of
    # inferring a new solver result.
    trajectory = LAB / "campaigns/core-v1/runtime/attempts/f4-laminar-qualification-cell-12/20260919T195625-d02c9bebf080/product/trajectory.h5"
    with h5py.File(trajectory, "r") as handle:
        mass = float(handle["mass"][0, 0])
        initial_mass = float(np.sum(handle["mass"][0].astype(float)))
        p0 = handle["position"][0].astype(float)
        v0 = handle["velocity"][0].astype(float)
        initial_energy = float(np.sum(handle["mass"][0].astype(float) *
                                      (9.81 * p0[:, 2] + .5 * np.sum(v0 * v0, axis=1))))
    speeds2 = np.asarray([np.dot(row["velocity_mps"], row["velocity_mps"]) for row in native_rows])
    tail_ke = .5 * mass * float(np.sum(speeds2))
    return dict(
        particle_mass_kg=mass, escaped_mass_kg=float(len(native_rows) * mass),
        initial_fluid_mass_kg=initial_mass,
        escaped_mass_fraction=float(len(native_rows) * mass / initial_mass),
        escaped_kinetic_energy_j=tail_ke,
        initial_potential_plus_kinetic_energy_j=initial_energy,
        escaped_kinetic_over_initial_energy=float(tail_ke / initial_energy),
        source_trajectory=str(trajectory), source_trajectory_sha256=digest(trajectory),
    )


def _q025_diagnostic() -> dict:
    audit = json.loads(Q025_AUDIT.read_text())
    result = dict(
        prepared=str(Q025_PREPARED), prepared_sha256=digest(Q025_PREPARED),
        audit=str(Q025_AUDIT), audit_sha256=digest(Q025_AUDIT),
        hard_integrity_pass=bool(audit.get("hard_integrity_pass")),
        native_loss_count=int(audit.get("structural", {}).get("death_count", 0)),
        endpoint_violation_particle_frames=int(audit.get("endpoint_violation_particle_frames", 0)),
        first_wall_violation=audit.get("first_wall_violation"),
        extension_effect="none_expected_for_q025_top_edge_event",
        control_policy="retain q=.25 fine failure; domain extension is not a repair for this case",
    )
    for path in (Q025_FORENSICS, Q025_ENDPOINT):
        if path.exists():
            result[path.stem] = {"path": str(path), "sha256": digest(path)}
    return result


def budget(output: Path) -> dict:
    q025 = json.loads(Q025_PREPARED.read_text())
    q075 = json.loads(Q075_PREPARED.read_text())
    domain = parse_domain_and_cell(q075)
    baseline = cell_allocation(domain["domain_low_m"], domain["domain_high_m"], domain["cell_size_m"])
    q075_product = LAB / "campaigns/core-v1/runtime/attempts/f4-laminar-qualification-cell-12/20260919T195625-d02c9bebf080/product"
    q025_product = LAB / "campaigns/core-v1/runtime/attempts/f4-laminar-qualification-cell-10/20260919T195624-08f5d07ea433/product"
    memory = _csv_memory(q075_product)
    memory_q025 = _csv_memory(q025_product)
    native = json.loads(Q075_NATIVE.read_text())
    loss_paths = json.loads(Q075_LOSS_PATHS.read_text())
    loss_times = sorted(float(row["first_missing_s"]) for row in loss_paths["records"])
    source_time = float(loss_times[0])
    native_rows = _partout_rows(native)
    projection = ballistic_projection(native_rows, source_time, HORIZON_S)
    bbox_min = np.asarray(projection["projected_bbox_m"]["min"], dtype=float)
    current_low = np.asarray(domain["domain_low_m"], dtype=float)
    current_high = np.asarray(domain["domain_high_m"], dtype=float)
    # Only the dimensions crossed by the measured spill are extended.  x and
    # the upper bounds remain bit-for-bit the registered computational range.
    proposed_low = current_low.copy()
    # Publish round, reproducible bounds rather than binding a solver input to
    # the last decimal of one native PartOut record.  They leave 0.1616 m in
    # y and 0.2066 m in z below the measured projected minima.
    proposed_low[1] = -1.8
    proposed_low[2] = -72.0
    extended = cell_allocation(proposed_low.tolist(), current_high.tolist(), domain["cell_size_m"])
    base_cells = int(baseline["allocated_cells"])
    cell_mib = float(memory["peak"]["gpu_cells_mib"] / base_cells)
    delta_cells = int(extended["allocated_cells"] - base_cells)
    extension_memory = dict(
        cell_mib_per_cell=cell_mib,
        projected_gpu_cells_mib=float(extended["allocated_cells"] * cell_mib),
        projected_gpu_peak_mib=float(memory["peak"]["gpu_mib"] + delta_cells * cell_mib),
        projected_gpu_peak_mib_initial=float(memory["baseline_initial"]["gpu_mib"] + delta_cells * cell_mib),
        baseline_peak_gpu_mib=memory["peak"]["gpu_mib"],
        baseline_peak_cpu_mib=memory["peak"]["cpu_mib"],
        baseline_allocated_particles=memory["peak"]["allocated_particles"],
        baseline_allocated_cells=base_cells,
        cell_factor=float(extended["allocated_cells"] / base_cells),
        additional_cells=delta_cells,
        resource_request=dict(cpu_cores=2, ram_mib=32768, gpu_peak_mib=4096, io_weight=0.5),
    )
    # A concrete attached front receiver is used only for the alternative
    # budget.  Its CPU GenCase counts were measured from the design XML kept
    # beside this report; it leaves the registered simulation domain intact.
    catchment = dict(
        design_id="F4_external_front_receiver_floor_v1",
        continuous_geometry=dict(
            floor_fluid_facing_z_m=-0.595,
            floor_x_m=[0.0, 1.2], floor_y_m=[-0.3, 0.0],
            front_wall_y_m=-0.3, side_wall_x_m=[-0.1, 1.3],
            wall_top_m=0.0, top_open=True,
        ),
        physical_change="new finite floor and side/front walls below/in front of the original open vessel; independent scope",
        computational_domain_unchanged=True,
        cell_allocation=baseline,
        gencase=dict(
            definition_xml=str(output.parent / "f4-domain-extension-budget-v1/catchment_Def.xml"),
            generated_xml=str(output.parent / "f4-domain-extension-budget-v1/catchment.xml"),
            definition_xml_sha256=(digest(output.parent / "f4-domain-extension-budget-v1/catchment_Def.xml")
                                   if (output.parent / "f4-domain-extension-budget-v1/catchment_Def.xml").exists() else None),
            generated_xml_sha256=(digest(output.parent / "f4-domain-extension-budget-v1/catchment.xml")
                                 if (output.parent / "f4-domain-extension-budget-v1/catchment.xml").exists() else None),
            gencase_log_sha256=(digest(output.parent / "f4-domain-extension-budget-v1/gencase.log")
                                if (output.parent / "f4-domain-extension-budget-v1/gencase.log").exists() else None),
            boundary_particles=321527,
            added_boundary_particles=21383,
            fluid_particles=737792,
            zero_boundary_normals=3362,
            preflight_pass=False,
            failure="new catchment boundary has zero mDBC normals; this is a budget/design result, not a launchable job",
        ),
        projected_memory=dict(
            gpu_peak_mib=float(memory["peak"]["gpu_mib"] + 21383 *
                              ((memory["peak"]["gpu_mib"] - memory["peak"]["gpu_cells_mib"]) /
                               memory["peak"]["allocated_particles"])),
            resource_request=dict(cpu_cores=2, ram_mib=32768, gpu_peak_mib=4096, io_weight=0.5),
        ),
        qualification_policy="do not inherit F4 qualification; retain spill/native and q=.25 top-edge gates",
    )
    report = dict(
        schema=SCHEMA, created_at=stamp(), horizon_s=HORIZON_S,
        source_scope="F4_resting_pool_laminar_nu1e6_x_v1",
        qualification_claim="none; this is a CPU budget and repair-canary proposal",
        evidence=dict(
            q025=_q025_diagnostic(),
            q075_native_exclusions={"path": str(Q075_NATIVE), "sha256": digest(Q075_NATIVE)},
            q075_loss_paths={"path": str(Q075_LOSS_PATHS), "sha256": digest(Q075_LOSS_PATHS)},
            q075_exclusion_motive_counts=native["motive_counts"],
            q075_exclusion_z_range_m=native["native_exclusion_z_range_m"],
            q075_exact_id_join=bool(native["exact_id_join"]),
        ),
        q075_ballistic_projection=projection,
        q075_tail_energy=_energy_tail(native, native_rows, q075),
        current_domain=domain,
        current_cell_allocation=baseline,
        q025_control_budget=dict(
            generated_case=parse_domain_and_cell(q025),
            cell_allocation=cell_allocation(
                parse_domain_and_cell(q025)["domain_low_m"],
                parse_domain_and_cell(q025)["domain_high_m"],
                parse_domain_and_cell(q025)["cell_size_m"],
            ),
            runparts_memory=memory_q025,
            extension_effect="same 66.25x cell allocation would leave the q=.25 top-edge endpoint/inward-chord failure unchanged",
        ),
        proposed_physical_preserving_extension=dict(
            domain_low_m=proposed_low.tolist(), domain_high_m=current_high.tolist(),
            reason="contain every measured native-excluded q=.75 ID through 4.34 s under constant-gravity continuation with explicit y/z margins",
            physical_geometry_unchanged=True,
            cell_allocation=extended,
            memory=extension_memory,
            limits=[
                "The q=.75 particles have already crossed the registered finite vessel wall; extension recovers domain identity only and cannot make the unchanged wall audit pass.",
                "The q=.25 fine failure has no native loss and includes an inward saved chord at the top/front edge; this extension is not a q=.25 repair.",
                "Ballistic continuation is an envelope assumption after the last native exclusion; it is not a predicted SPH trajectory.",
            ],
        ),
        external_catchment=catchment,
        recommendation=dict(
            candidate="proposed_physical_preserving_extension",
            launchable_after_root_review=True,
            solver_run="one q=.75, dp=.005, 4.34 s repair_canary only; no matrix or qualification claim",
            expected_readout=["native exclusion count", "finite/wall endpoint count", "event completion", "peak memory"],
            q025_policy="retain original q=.25 fine result and bidirectional-chord evidence; do not relabel it as a domain failure",
        ),
    )
    write_json(output, report)
    return report


def _replace_domain(root: ET.Element, low: list[float], high: list[float]) -> None:
    domain = root.find(".//simulationdomain")
    if domain is None:
        raise ValueError("source XML has no simulationdomain")
    domain.find("posmin").attrib.update(dict(zip("xyz", [f"{x:.17g}" for x in low])))
    domain.find("posmax").attrib.update(dict(zip("xyz", [f"{x:.17g}" for x in high])))


def _native_initial(prepared: dict, generated_prefix: Path, lab: Path) -> dict:
    decoder = Path(prepared["decoder"]).resolve()
    with tempfile.TemporaryDirectory(prefix="f4-extension-native-") as folder:
        temporary = Path(folder) / "frame"
        subprocess.run([str(decoder), str(generated_prefix.with_suffix(".bi4")), str(temporary)], check=True,
                       stdout=subprocess.DEVNULL)
        metadata_root = ET.parse(str(temporary) + ".xml").getroot()
        parent = metadata_root.find("item")
        node = parent.find("item")
        metadata = {e.get("name"): e.get("v") for e in parent if e.tag != "item"}
        arrays = temporary / node.get("name")
        normals_path = arrays / "BoundNor.bin"
        normals = np.fromfile(normals_path, np.float32).reshape(-1, 3) if normals_path.exists() else np.empty((0, 3))
        zero = int(np.sum(np.linalg.norm(normals, axis=1) <= 1e-10))
        boundary = int(metadata["CaseNfixed"])
        return dict(
            total_particles=int(metadata["CaseNfixed"]) + int(metadata["CaseNfluid"]),
            boundary_particles=boundary,
            fluid_particles=int(metadata["CaseNfluid"]),
            normal_count=len(normals), zero_boundary_normals=zero,
            native_initial_mass_kg=float(metadata["MassFluid"]) * int(metadata["CaseNfluid"]),
            initial_state_pass=bool(len(normals) == boundary and zero == 0 and np.isfinite(normals).all()),
        )


def prepare_extension(output_dir: Path, *, lab: Path = LAB) -> dict:
    """Create one fresh CPU-prepared q=.75 domain extension candidate."""
    output_dir = Path(output_dir).resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"candidate output must be fresh: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    source = json.loads(Q075_PREPARED.read_text())
    source_xml = generated_xml(source).parent.parent / (Path(source["generated_prefix"]).name + "_Def.xml")
    # The prepared case keeps the Def XML beside generated/, so use the
    # registered source directly rather than reconstructing physical geometry.
    source_xml = Q075_PREPARED.parent / "LAMINAR_RESTING_CORE_F4_mdbc_native_q0p75000000_dp0p005000000000_qualification_Def.xml"
    if not source_xml.exists():
        raise FileNotFoundError(source_xml)
    domain = parse_domain_and_cell(source)
    native = json.loads(Q075_NATIVE.read_text())
    projection = ballistic_projection(_partout_rows(native), 1.0400008445907, HORIZON_S)
    low = np.asarray(domain["domain_low_m"], dtype=float)
    high = np.asarray(domain["domain_high_m"], dtype=float)
    low[1] = -1.8
    low[2] = -72.0
    case_id = "F4_LAMINAR_DOMAIN_EXTENSION_Q075_DP005_REPAIR_CANARY"
    definition_path = output_dir / (case_id + "_Def.xml")
    tree = ET.parse(source_xml)
    _replace_domain(tree.getroot(), low.tolist(), high.tolist())
    ET.indent(tree, space="  ")
    tree.write(definition_path, encoding="utf-8", xml_declaration=True)
    binaries = lab / "vendor/official/DualSPHysics_v5.4/bin/linux"
    prefix = output_dir / "generated" / case_id
    prefix.parent.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "gencase.log"
    command = [str(binaries / "GenCase_linux64"), str(definition_path.with_suffix("")), str(prefix), "-save:all"]
    with log_path.open("w") as log:
        process = subprocess.run(command, cwd=output_dir, env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT)
    if process.returncode:
        raise RuntimeError(f"GenCase failed; see {log_path}")
    generated = ET.parse(prefix.with_suffix(".xml")).getroot()
    fluid = generated.findall(".//particles/fluid")
    fixed = generated.findall(".//particles/fixed")
    expected_fluid = int(source["sampling"]["expected_fluid_particles"])
    generated_fluid = sum(int(node.get("count")) for node in fluid)
    if generated_fluid != expected_fluid:
        raise ValueError(f"extension changed fluid particle count: {generated_fluid} != {expected_fluid}")
    prepared = dict(source)
    config = dict(source["config"])
    config.update(case_id=case_id, stage="repair_canary", qualification_claim="none", qualified=False,
                  qualification_only=True, domain_extension=dict(low_m=low.tolist(), high_m=high.tolist(),
                  physical_geometry_unchanged=True, source_case_id=source["config"]["case_id"]))
    prepared.update(config=config, generated_prefix=str(prefix.resolve()), created_at=stamp(), qualification_claim="none; repair diagnostic only")
    prepared["native_initial"] = _native_initial(prepared, prefix, lab)
    prepared["preflight_pass"] = bool(prepared["native_initial"]["initial_state_pass"] and
                                       prepared["mass_preflight"]["mass_gate_pass"])
    # The input manifest is deliberately rebuilt after GenCase and excludes
    # prepared.json itself, which the worker writes into its product.
    prepared["inputs"] = {str(path.resolve()): digest(path) for path in sorted(output_dir.rglob("*"))
                           if path.is_file() and path.name != "prepared.json"}
    prepared["source_template"] = str(source_xml.resolve())
    prepared["source_template_sha256"] = digest(source_xml)
    prepared["geometry_identity"] = dict(
        source_casedef_sha256=element_digest(source_xml, "casedef"),
        candidate_casedef_sha256=element_digest(definition_path, "casedef"),
        unchanged=(element_digest(source_xml, "casedef") == element_digest(definition_path, "casedef")),
    )
    prepared["solver_binary"] = str((binaries / "DualSPHysics5.4_linux64").resolve())
    prepared["solver_sha256"] = digest(Path(prepared["solver_binary"]))
    prepared["decoder"] = str((lab / "campaigns/l1-resume/artifacts/bi4_dump").resolve())
    prepared["decoder_sha256"] = digest(Path(prepared["decoder"]))
    write_json(output_dir / "prepared.json", prepared)
    return prepared


def make_job(prepared_path: Path, output: Path, *, lab: Path = LAB) -> dict:
    prepared = json.loads(Path(prepared_path).read_text())
    spec = dict(
        schema="core.cfd.job.v1", job_id="f4-laminar-domain-extension-q075-dp005-canary-001",
        logical_id="f4-laminar-domain-extension-q075-dp005-canary-001", attempt_role="repair_canary",
        category="repair_canary", host="h200", source_lab=str(lab.resolve()), cwd=str(lab.resolve()),
        # Keep the venv symlink path in the worker spec.  Resolving it to the
        # host interpreter would bypass the declared environment on H200.
        argv=[str(lab / ".venv/bin/python"),
              str((lab / "scripts/core_cfd.py").resolve()), "--lab-root", str(lab.resolve()), "run",
              "--prepared", str(Path(prepared_path).resolve()), "--output", "{attempt_dir}/product"],
        required_outputs=["product/result.json", "product/trajectory.h5", "product/audit.json", "product/observations.json"],
        resources=dict(cpu_cores=2, ram_mib=32768, gpu_peak_mib=4096, io_weight=.5),
        timeout_seconds=21600, depends_on=[], qualification_claim="none",
        prepared_case_id=prepared["config"]["case_id"], registered_window_s=prepared["config"]["time_max_s"],
        input_files=[dict(path=str(Path(prepared_path).resolve()), sha256=digest(Path(prepared_path))),
                     dict(path=prepared["solver_binary"], sha256=prepared["solver_sha256"])],
        worker_contract="core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0",
        scientific_role="diagnose native domain exclusion only; unchanged finite-wall and event gates remain active",
    )
    write_json(output, spec)
    return spec


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("budget"); b.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("prepare"); p.add_argument("--output", type=Path, required=True)
    j = sub.add_parser("job"); j.add_argument("--prepared", type=Path, required=True); j.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "budget":
        budget(args.output.resolve())
    elif args.command == "prepare":
        prepare_extension(args.output.resolve())
    else:
        make_job(args.prepared.resolve(), args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
