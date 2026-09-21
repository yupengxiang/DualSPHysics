"""Read-only diagnosis of the completed F4 repair canaries.

The script reads existing native CFD/material H5 files and samples the fixed
support gate at selected saved frames.  It does not launch a worker, solver,
GPU, or ledger operation.  The two future paths in the receipt are designs
only; this module does not implement or run them.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import h5py
import numpy as np

from scripts.core_material import (
    GATE,
    MAXIMUM_SUPPORT_DISTANCE_M,
    REGULARIZATION_M,
    ReferenceFrames,
    f4_walls,
)


LAB = Path(__file__).resolve().parents[1]
EVIDENCE = LAB / "campaigns/core-v1/material/evidence"
ATTEMPTS = LAB / "campaigns/core-v1/runtime/attempts"
SOURCE = ATTEMPTS / (
    "f4-resting-pool-native-dense-002-canary-s0p3-center-q0p5/"
    "20260919T185855-d91665790347/product/trajectory.h5"
)
FRAMES_TO_PROBE = (0, 80, 81, 82, 90, 120, 150)
VARIANTS = {
    "f4_ess32_v2": (32, "local_residual"),
    "f4_affine_bound_v2": (24, "residual_plus_local_affine_query_bias"),
}
CANARIES = {
    "f4_ess32_v2": "f4-material-repair-ess32-v2-canary-s0p3-center-q0p5",
    "f4_affine_bound_v2": "f4-material-repair-affine-bound-v2-canary-s0p3-center-q0p5",
}


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            value.update(block)
    return value.hexdigest()


def file_record(path: Path, **extra):
    result = {"path": str(path.resolve()), "sha256": sha256(path)}
    result.update(extra)
    return result


def result_path(variant):
    return EVIDENCE / f"{CANARIES[variant]}-result.json"


def execution_path(variant):
    return EVIDENCE / f"{CANARIES[variant]}-execution.json"


def material_path(variant):
    return next(ATTEMPTS.glob(f"{CANARIES[variant]}/*/material.h5"))


def native_contact_provenance():
    """Bind the saved-frame contact proxy to its actual source semantics.

    ``core_cfd.physical_observations`` calls a frame ``contact`` when at least
    5% of the initial drop label mass is below the pool surface.  It is an
    overlay mass CDF, not a geometric first-contact detector.  This read-only
    calculation also records the first native saved frame at which any drop
    mass crosses the plane and the simple initial ballistic crossing band.
    """
    pool_level = 0.18
    gravity = 9.81
    with h5py.File(SOURCE, "r") as handle:
        times = np.asarray(handle["time"], dtype=np.float64)
        labels = np.asarray(handle["source_label_initial_mk"], dtype=np.int16)
        drop = labels == np.max(labels)
        initial_position = np.asarray(handle["position"][0, drop], dtype=np.float64)
        initial_velocity = np.asarray(handle["velocity"][0, drop], dtype=np.float64)
        z_min = float(np.min(initial_position[:, 2]))
        z_max = float(np.max(initial_position[:, 2]))
        vz_min = float(np.min(initial_velocity[:, 2]))
        vz_max = float(np.max(initial_velocity[:, 2]))
        below_fraction = []
        for frame in range(len(times)):
            z = np.asarray(handle["position"][frame, :, 2], dtype=np.float64)[drop]
            below_fraction.append(float(np.mean(z < pool_level)))
    below_fraction = np.asarray(below_fraction, dtype=np.float64)
    any_crossing = np.flatnonzero(below_fraction > 0.0)
    proxy_crossing = np.flatnonzero(below_fraction >= 0.05)
    # z(t)=z0+vz*t-0.5*g*t^2.  The positive root is the first ballistic
    # crossing for each initial particle under the registered gravity.
    discriminant = initial_velocity[:, 2] ** 2 + 2.0 * gravity * (initial_position[:, 2] - pool_level)
    ballistic = (initial_velocity[:, 2] + np.sqrt(np.maximum(discriminant, 0.0))) / gravity
    return {
        "source": file_record(SOURCE, role="native dense .002 s F4 source"),
        "pool_surface_z_m": pool_level,
        "initial_drop_label": int(np.max(labels)),
        "initial_drop_count": int(drop.sum()),
        "initial_drop_z_range_m": [z_min, z_max],
        "initial_drop_vz_range_mps": [vz_min, vz_max],
        "gravity_m_s2": [0.0, 0.0, -gravity],
        "ballistic_first_crossing_band_s": [float(np.min(ballistic)), float(np.max(ballistic))],
        "physical_observations_contact_definition": "first saved frame where sum(initial_drop_mass[z < pool_surface]) / initial_drop_mass >= 0.05",
        "physical_observations_contact_semantics": "5% initial-drop source-mass-below-pool proxy; not first geometric contact",
        "native_saved_first_any_drop_mass_below": {
            "frame": int(any_crossing[0]) if len(any_crossing) else None,
            "time_s": float(times[any_crossing[0]]) if len(any_crossing) else None,
            "fraction": float(below_fraction[any_crossing[0]]) if len(any_crossing) else 0.0,
        },
        "native_saved_first_5pct_drop_mass_below": {
            "frame": int(proxy_crossing[0]) if len(proxy_crossing) else None,
            "time_s": float(times[proxy_crossing[0]]) if len(proxy_crossing) else None,
            "fraction": float(below_fraction[proxy_crossing[0]]) if len(proxy_crossing) else 0.0,
        },
        "interpretation": "The frame-81 failure at about .162 s lies before the first ballistic crossing band and before the first saved crossing (.170 s), but it is within the near-contact approach interval. It must not be described as before physical contact using the old .213 s overlay value.",
    }


def first_failure(material):
    reliable = np.asarray(material["reliable"][:], dtype=bool)
    time_axis = np.asarray(material["time"][:], dtype=np.float64)
    first = np.full(reliable.shape[1], -1, dtype=np.int64)
    for frame in range(len(time_axis)):
        newly_failed = (first < 0) & ~reliable[frame]
        first[newly_failed] = frame
    failed = first >= 0
    values, counts = np.unique(first[failed], return_counts=True)
    return {
        "seed_count": int(reliable.shape[1]),
        "final_unknown_count": int((~reliable[-1]).sum()),
        "final_reliable_count": int(reliable[-1].sum()),
        "final_unknown_fraction": float((~reliable[-1]).mean()),
        "first_failure_frame_min": int(first[failed].min()) if failed.any() else None,
        "first_failure_time_min_s": float(time_axis[first[failed].min()]) if failed.any() else None,
        "first_failure_time_median_s": float(np.median(time_axis[first[failed]])) if failed.any() else None,
        "first_failure_time_max_s": float(time_axis[first[failed].max()]) if failed.any() else None,
        "first_failure_frame_counts": {str(int(frame)): int(count) for frame, count in zip(values, counts)},
        "unknown_count_by_probe_frame": {
            str(frame): int((~reliable[frame]).sum()) for frame in FRAMES_TO_PROBE
        },
    }


def sample_gate(field, query, neighbours, estimator):
    velocity, support, passed, diagnostics = field.sample(
        query, f4_walls(), neighbours=neighbours, regularization=REGULARIZATION_M,
        gate=GATE, error_estimator=estimator, return_diagnostics=True,
    )
    estimated = np.asarray(diagnostics["estimated_interpolation_error_mps"], dtype=np.float64)
    support = np.asarray(support, dtype=np.float64)
    return {
        "sample_gate_fail_count": int((~passed).sum()),
        "effective_sample_size_fail_count": int((diagnostics["effective_sample_size"] < GATE["minimum_effective_sample_size"]).sum()),
        "geometry_rank_fail_count": int((diagnostics["geometry_rank"] < GATE["minimum_geometry_rank"]).sum()),
        "anisotropy_fail_count": int((diagnostics["anisotropy"] < GATE["minimum_anisotropy"]).sum()),
        "reconstruction_fail_count": int((estimated > GATE["maximum_reconstruction_error_mps"]).sum()),
        "support_distance_fail_count": int((support > MAXIMUM_SUPPORT_DISTANCE_M).sum()),
        "nonfinite_interpolated_velocity_count": int((~np.isfinite(velocity).all(axis=1)).sum()),
        "effective_sample_size_p05": float(np.percentile(diagnostics["effective_sample_size"], 5)),
        "geometry_rank_min": int(np.min(diagnostics["geometry_rank"])),
        "anisotropy_p05": float(np.percentile(diagnostics["anisotropy"], 5)),
        "estimated_error_p95_mps": float(np.percentile(estimated, 95)),
        "estimated_error_max_mps": float(np.max(estimated)),
        "support_distance_p95_m": float(np.percentile(support, 95)),
        "support_distance_max_m": float(np.max(support)),
    }


def read_only_probe():
    outputs = {variant: material_path(variant) for variant in VARIANTS}
    positions = {}
    stored = {}
    for variant, path in outputs.items():
        with h5py.File(path, "r") as handle:
            positions[variant] = np.asarray(handle["position"][:], dtype=np.float64)
            stored[variant] = first_failure(handle)
    probes = []
    started = time.monotonic()
    with ReferenceFrames(SOURCE) as reference:
        times = np.asarray(reference.times, dtype=np.float64)
        for frame in FRAMES_TO_PROBE:
            field = reference.field(frame, 0.0)
            for variant, (neighbours, estimator) in VARIANTS.items():
                sampled = sample_gate(field, positions[variant][frame], neighbours, estimator)
                sampled.update({
                    "variant": variant, "frame": int(frame), "time_s": float(times[frame]),
                    "stored_unknown_count": stored[variant]["unknown_count_by_probe_frame"][str(frame)],
                })
                sampled["stored_unknown_matches_reconstruction_only"] = bool(
                    sampled["stored_unknown_count"] == sampled["reconstruction_fail_count"]
                    and sampled["support_distance_fail_count"] == 0
                    and sampled["effective_sample_size_fail_count"] == 0
                    and sampled["geometry_rank_fail_count"] == 0
                    and sampled["anisotropy_fail_count"] == 0
                )
                probes.append(sampled)
    return outputs, stored, probes, time.monotonic() - started


def research_design():
    return [
        {
            "id": "f4_native_kernel_mls_v1",
            "status": "design_only",
            "claim": "independent offline backend; no qualification",
            "principle": "Use the native SPH support radius and Wendland kernel from the prepared solver case, native fluid mass/density volume weights, and a weighted affine MLS/QR reconstruction. Do not retain a nearest-k Shepard cap or reuse the current local-residual estimator.",
            "native_bindings": {
                "prepared_case": "F4_RESTING_POOL_CENTER_NATIVE_DENSE_002_CANARY",
                "dp_m": 0.0075,
                "h_m": 0.011941277883,
                "kernel": "DualSPHysics Kernel=2 (Wendland)",
                "support_radius_policy": "solver-declared kernel support from h; no parameter sweep",
                "fluid_selection": "native type==3/particle_zone fluid mask",
                "weights": "native particle volume m/rho multiplied by the declared Wendland kernel",
            },
            "input_gap": "trajectory.h5 does not carry h or wall-normal fields; bind the prepared XML/hdp export hashes or extend the CFD decoder before any qualification run",
            "verification_stages": [
                "Held-out manufactured constant, affine, nonlinear, and interface fields with the same native h/kernel and fixed 1% denominator.",
                "One read-only real dense .002 s/.3 s q=.5 overlay against the current baseline, reporting support conditioning, cross-validation residual, unknown mass, and mass closure.",
                "Only if both pass, register the full F4 scope; no T2 claim from either short stage.",
            ],
            "acceptance": {
                "unknown_fraction_max_per_source": 0.01,
                "mass_closure_abs_error_max": 1e-12,
                "reconstruction_gate_mps": GATE["maximum_reconstruction_error_mps"],
                "false_safe_mass": 0.0,
                "denominator": "all 512 source seeds, including failed queries",
            },
            "estimated_cost": {
                "engineering": "3-5 engineer-days for native-kernel gather, MLS conditioning/validation, provenance, and restart-safe output",
                "postprocess_cpu": "planning estimate 2-4x the measured 110.5-127.4 s current material canary wall time; preflight required",
                "memory": "planning estimate 1-2 GiB with streaming frame batches; current canaries sampled about 640-760 MiB",
                "storage": "about 4.7 MiB per .3 s/512-seed material output; roughly 68 MiB for 4.34 s at the same saved cadence, excluding receipts",
                "cfd_rerun": "not required only if h/kernel/wall bindings are proven from the existing prepared case; otherwise one source export/CFD revision is required",
            },
        },
        {
            "id": "f4_native_solver_material_v1",
            "status": "design_only",
            "claim": "native solver-coupled passive-material path; no qualification",
            "principle": "Carry independent seed state inside the DualSPHysics time integrator. At every native internal step, use the solver's own fluid neighbor list, Wendland kernel, velocity, and boundary treatment to advect seeds; save seed/event state at the declared output cadence.",
            "coupling_policy": {
                "initial_scope": "one-way passive material state; seeds do not alter fluid momentum",
                "identity": "independent seed-XXXXXX ids; native particle ids remain fluid provenance only",
                "time_access": "current solver state only; no future-frame reconstruction",
                "events": "continuous segment crossing and residence inside the registered destination box",
                "output": "material H5 plus atomic checkpoint with support diagnostics, event state, solver/config/source hashes",
            },
            "verification_stages": [
                "Unit/analytic solver test with constant and manufactured velocity fields, including wall crossing and mass closure.",
                "Paired .3 s native dense q=.5 run against the existing trajectory lineage; compare first failure time, unknown mass, and event outputs without calling it qualification.",
                "Full F4 native source matrix only after the paired canary passes; retain the fixed 1% denominator and event right-censoring.",
            ],
            "acceptance": {
                "unknown_fraction_max_per_source": 0.01,
                "mass_closure_abs_error_max": 1e-12,
                "same_event_definition": True,
                "same_seed_count": 512,
                "denominator": "all source seeds; no renormalization after solver loss",
                "qualification": "forbidden until the registered full scope and event horizon are complete",
            },
            "estimated_cost": {
                "engineering": "5-10 engineer-days for solver state/output integration, restart semantics, decoder/receipt changes, and analytic tests",
                "solver_runtime": "measured dense .3 s case took 83.9 s solver time and 248.1 s total; linear 4.34 s extrapolation is about 20 min solver/60 min total per case, planning only",
                "cfd_storage": "the existing .3 s native trajectory is about 1.3 GiB; same cadence over 4.34 s is roughly 19 GiB per case by linear storage extrapolation",
                "material_storage": "about 68 MiB per 4.34 s/512-seed native material output; 4096-seed studies scale approximately 8x",
                "gpu_cpu": "requires a scheduler-admitted native CFD rerun and solver snapshot; this design launches neither",
            },
        },
    ]


def build_report():
    outputs, stored, probes, probe_seconds = read_only_probe()
    contact_provenance = native_contact_provenance()
    results = {variant: load(result_path(variant)) for variant in VARIANTS}
    executions = {variant: load(execution_path(variant)) for variant in VARIANTS}
    current_code = LAB / "scripts/core_material.py"
    neighbour = LAB / "scripts/f3_material_neighbors.py"
    passive = LAB / "scripts/passive_tracers.py"
    result_summary = {}
    for variant in VARIANTS:
        result = results[variant]
        execution = executions[variant]
        source = result["by_source"][0]
        result_summary[variant] = {
            "result": file_record(result_path(variant), schema=result["binding"]["schema"]),
            "execution": file_record(execution_path(variant), schema=execution["schema"]),
            "material_h5": file_record(outputs[variant]),
            "material_summary": {
                "status": result["status"], "unknown_fraction": source["unknown_fraction"],
                "reliable_path_coverage": source["reliable_path_coverage"],
                "mass_closed": result["mass_closed"], "unknown_gate_pass": result["unknown_gate_pass"],
                "qualified_T2_macro": result["qualified_T2_macro"], "qualified_T2_path": result["qualified_T2_path"],
                "event_window_status": result["event_window_status"],
                "first_contact_s": source["contact_cdf"]["time_s"][0] if source["contact_cdf"]["time_s"] else None,
                "contact_fraction": source["contact_fraction"],
                "right_censored_fraction": source["right_censored_fraction"],
                "elapsed_seconds": result["elapsed_seconds"], "max_rss_kib": result["max_rss_kib"],
                "binding": {key: result["binding"][key] for key in (
                    "backend", "neighbour_variant", "neighbours", "error_estimator", "source_sha256",
                    "code_sha256", "substeps", "regularization_m", "maximum_support_distance_m", "support_gate",
                )},
                "execution_usage": execution["usage"],
            },
        }
    return {
        "schema": "core.material.f4.repair_failure_diagnosis.v1",
        "revision_id": "F4_repair_failure_diagnosis_20260919",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "qualification_claim": "none",
        "scope_conclusion": {
            "statement": "baseline24, f4_ess32_v2, and f4_affine_bound_v2 are unavailable for F4 T2 qualification on this native dense center q=.5 scope under the fixed 1% unknown gate",
            "no_third_tuning": True,
            "no_gate_relaxation": True,
            "denominator": "512 independent source seeds for every canary; failed seeds remain in the denominator",
            "variants": {
                "baseline24": {"unknown_fraction": 0.896484375, "qualification": "unavailable; prior native dense baseline"},
                "f4_ess32_v2": {"unknown_fraction": results["f4_ess32_v2"]["by_source"][0]["unknown_fraction"], "qualification": "unavailable"},
                "f4_affine_bound_v2": {"unknown_fraction": results["f4_affine_bound_v2"]["by_source"][0]["unknown_fraction"], "qualification": "unavailable"},
            },
        },
        "inputs": {
            "native_dense_source": file_record(SOURCE, role="F4 center q=.5 native .002 s .3 s trajectory"),
            "current_material_code": file_record(current_code),
            "neighbour_code": file_record(neighbour),
            "passive_gate_code": file_record(passive),
            "manufactured_diagnosis": file_record(EVIDENCE / "f4-reconstruction-calibration-diagnosis-20260919.json"),
            "manufactured_v2_receipt": file_record(EVIDENCE / "f4-reconstruction-calibration-v2-20260919-result.json"),
            "prepared_dense_case": file_record(LAB / "campaigns/core-v1/cfd/prepared/F4_resting_pool_center_native_dense_002_canary/prepared.json"),
            "native_dense_result": file_record(SOURCE.parent / "result.json"),
            "diagnosis_script": file_record(Path(__file__)),
        },
        "canary_results": result_summary,
        "first_failure_and_gate_probe": {
            "probe_mode": "read-only existing H5; selected saved frames; no worker/solver/GPU/ledger",
            "frames": list(FRAMES_TO_PROBE),
            "records": probes,
            "probe_wall_seconds": probe_seconds,
            "interpretation": {
                "manufactured_ess_failure": "v1/v2 manufactured source false alarms were ESS-only with valid rank/anisotropy/reconstruction; fixed k=32 removed that synthetic false alarm",
                "real_first_failure": "on the native CFD field, both repair candidates first fail at frame 81 (0.1620038902 s). The saved source's initial-drop ballistic first-crossing band is approximately 0.16745-0.22331 s, and the first saved frame with any drop mass below z=.18 is frame 85 (0.1700054 s); frame 81 is therefore in the near-contact approach interval. The core_cfd contact field is a 5% initial-drop-mass-below-pool proxy, not first physical contact, so the prior .213 s wording is not a contact claim. At frame 81 the sampled ESS/rank/anisotropy/support metrics pass while reconstruction error exceeds the fixed cap",
                "real_later_failure": "after frame 120, support distance also exceeds 0.03 m for many frozen/escaped paths; at frame 150 both support and reconstruction failures contribute, and affine-bound has substantially more reconstruction failures",
                "physical_origin_limit": "the gate component is directly identified; the deeper SPH free-surface/interface cause is a research hypothesis, not proven by this saved-state probe",
            },
        },
        "contact_provenance_correction": contact_provenance,
        "research_paths_design_only": research_design(),
        "execution_limits": {
            "solver_started": False, "gpu_started": False, "central_ledger_mutation": 0,
            "new_job_submitted": False, "qualification_claim": "none",
            "actual_work": "read-only H5 gate probe and JSON/Markdown design report",
        },
    }


def load(path):
    return json.loads(path.read_text())


def main():
    report = build_report()
    output = EVIDENCE / "f4-material-repair-failure-diagnosis-20260919-amendment.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    markdown = EVIDENCE / "f4-material-repair-failure-diagnosis-20260919-amendment.md"
    markdown.write_text(
        "# F4 repair canary failure diagnosis (2026-09-19)\n\n"
        "Qualification claim: none. All fractions use the full 512-seed source denominator; the 1% unknown gate is unchanged.\n\n"
        "The prior baseline24 dense overlay had 89.6484375% unknown mass. The fixed-k ESS32 candidate has 92.3828125% unknown and the affine-bound candidate has 95.5078125%; both are mass-closed and unavailable for T2 qualification.\n\n"
        "The manufactured calibration and the native CFD failure are different mechanisms. Manufactured source failures were ESS-only false alarms: rank, anisotropy, and reconstruction passed, and k=32 removed those false alarms. In the real dense source, both candidates are reliable through frame 80 (.160015 s). At frame 81 (.162004 s), each loses 64 seeds while ESS, rank, anisotropy, and support distance still pass; the estimated reconstruction p95 is about .139/.133 m/s versus the fixed .0469814 m/s cap. This frame is in the initial-drop near-contact approach interval: the registered ballistic first-crossing band is about .16745-.22331 s, and the first saved frame with any drop mass below z=.18 is frame 85 (.1700054 s). The core_cfd .213-style contact value is a 5% initial-drop-mass-below-pool proxy, not first physical contact. At frame 82 the reconstruction failure count is 128. Support-distance failures become material later, from the frame-120 region onward.\n\n"
        "Two design-only paths are recorded in the JSON: an independent native-kernel MLS backend bound to the prepared h/Wendland case, and a solver-coupled passive-material implementation using the solver's internal neighbor list and time integrator. Neither path is implemented, launched, or qualified.\n"
    )
    print(json.dumps({"path": str(output), "sha256": sha256(output), "markdown": str(markdown), "markdown_sha256": sha256(markdown)}, indent=2))


if __name__ == "__main__":
    main()
