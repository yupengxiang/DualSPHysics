#!/usr/bin/env python3
"""Prepare bounded F1-S2 interval GenCase information-gain candidates.

Each derived Def changes only the exact CURRENT preflight Def's dp attribute.
This creates new input files and launch-disabled shared-v4 CPU requests; it
never invokes GenCase and never modifies historical inputs or receipts.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
INPUT_ROOT = REFERENCE / "stage2_infogain_gencase_inputs_v2"
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-infogain-gencase-v2"
QUEUE_PATH = REFERENCE / "stage2_infogain_gencase_queue_v2.json"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
DISPATCH = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py")
STRICT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py")
RUNTIME = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py")
CURRENT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json")
MATRIX = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/SENTINEL_MATRIX.json"
QUALITY = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/QUALITY_LABEL_SPLIT_ZH.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256(path)}


def atomic_bytes(path: Path, data: bytes, *, replace: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not replace:
        raise FileExistsError(path)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def atomic_json(path: Path, value: object, *, replace: bool = False) -> None:
    atomic_bytes(path, (json.dumps(value, indent=2, ensure_ascii=False) + chr(10)).encode("utf-8"), replace=replace)


def replace_definition_dp(text: str, dp: str) -> tuple[str, str, str]:
    marker = "<definition"
    starts = [m.start() for m in re.finditer(re.escape(marker), text)]
    if len(starts) != 1:
        raise ValueError(f"expected one geometry definition, found {len(starts)}")
    start = starts[0]
    end = text.find(">", start)
    if end < 0:
        raise ValueError("unterminated definition tag")
    tag = text[start:end + 1]
    attr = re.search(r'dp="[^"]+"', tag)
    if attr is None:
        raise ValueError("definition has no dp attribute")
    old_tag = tag
    new_tag = tag[:attr.start()] + f'dp="{dp}"' + tag[attr.end():]
    replacement = text[:start] + new_tag + text[end + 1:]
    normalizer = re.compile(r'dp="[^"]+"')
    normalized_old = text[:start] + normalizer.sub('dp="<DP>"', tag) + text[end + 1:]
    normalized_new = text[:start] + normalizer.sub('dp="<DP>"', new_tag) + text[end + 1:]
    return replacement, normalized_old, normalized_new


def derive_dp(source_def: Path, target: Path, dp: str) -> dict[str, object]:
    text = source_def.read_text(encoding="utf-8")
    replacement, old_normal, new_normal = replace_definition_dp(text, dp)
    if replacement == text:
        raise ValueError(f"dp replacement did not change {source_def}")
    if target.exists():
        if target.read_text(encoding="utf-8") != replacement:
            raise ValueError(f"existing derived Def differs from deterministic candidate: {target}")
    else:
        atomic_bytes(target, replacement.encode("utf-8"))
    return {
        "source_def": record(source_def),
        "derived_def": record(target),
        "source_normalized_sha256": hashlib.sha256(old_normal.encode()).hexdigest(),
        "derived_normalized_sha256": hashlib.sha256(new_normal.encode()).hexdigest(),
        "continuous_definition_equal": old_normal == new_normal,
        "intentional_change": "definition dp only; geometry/control/initial/motion bytes preserved",
    }


def copy_motion(source: Path, target: Path) -> dict[str, object]:
    if target.exists():
        if sha256(target) != sha256(source):
            raise ValueError(f"existing motion dependency differs: {target}")
    else:
        atomic_bytes(target, source.read_bytes())
    return {"source": record(source), "copied_dependency": record(target), "bytes_identical": sha256(source) == sha256(target)}


def make_candidate(spec: dict[str, object]) -> tuple[dict[str, object], Path]:
    base_def = Path(str(spec["base_def"]))
    out_dir = INPUT_ROOT / str(spec["sentinel_id"]).replace("-", "_") / f"dp{str(spec['dp']).replace('.', 'p')}"
    candidate_def = out_dir / f"{spec['case_id']}_Def.xml"
    definition_meta = derive_dp(base_def, candidate_def, str(spec["dp"]))
    motion_meta = None
    if spec.get("motion_source"):
        motion_source = Path(str(spec["motion_source"]))
        motion_meta = copy_motion(motion_source, out_dir / motion_source.name)
    source_inputs = [Path(str(path)) for path in spec["source_inputs"]]
    base_request = Path(str(spec["base_request"]))
    input_files = [DISPATCH, STRICT, RUNTIME, PYTHON, GENCASE, CURRENT, MATRIX, QUALITY, Path(__file__), base_request, base_def, candidate_def, *source_inputs]
    if motion_meta:
        input_files.append(Path(str(motion_meta["copied_dependency"]["path"])))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in input_files:
        path = path.resolve()
        if str(path) not in seen:
            seen.add(str(path))
            unique.append(path)
    output_root = Path(str(spec["output_root"]))
    if output_root.exists():
        raise FileExistsError(f"future attempt root already exists: {output_root}")
    request = {
        "schema": "ds02.request.v1",
        "family_id": spec["family_id"], "case_id": spec["case_id"], "sentinel_id": spec["sentinel_id"],
        "physical_case_id": spec["physical_case_id"], "attempt_id": spec["attempt_id"], "kind": "cpu",
        "qualification_stage": "stage2_infogain_gencase_preflight_pending_parent_v4_dispatch",
        "cpu_task_kind": "gencase", "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 600,
        "estimated_storage_bytes": int(spec["estimated_storage_bytes"]), "estimated_peak_memory_bytes": 268435456,
        "worktree_root": str(REPO), "cwd": str(candidate_def.parent),
        "command": [str(GENCASE), str(candidate_def.with_suffix("")), f"{output_root}/generated", "-save:all"],
        "input_files": [str(path) for path in unique], "input_hashes": {str(path): sha256(path) for path in unique},
        "source_binding": {
            "schema": "ds02.stage2.infogain-gencase-binding.v1", "sentinel_id": spec["sentinel_id"], "family_id": spec["family_id"], "physical_case_id": spec["physical_case_id"],
            "grid_role": spec["grid_role"], "candidate_dp_m": float(spec["dp"]),
            "baseline_spacing_dp_m": 0.020,
            "spacing_separation_fraction": (0.020 - float(spec["dp"])) / 0.020,
            "spacing_relation": spec["spacing_relation"],
            "continuous_source_xml": [record(Path(str(path))) for path in spec["source_xmls"]],
            "current_source_def": record(Path(str(spec["current_source_def"]))), "base_preflight_def": record(base_def), "candidate_def": record(candidate_def),
            "definition_semantics": definition_meta, "motion_dependency": motion_meta or {"status": "NONE"},
            "prior_grid_evidence": spec["prior_grid_evidence"],
            "mass_gate": {"whole_initial_target": "1% target; 2% hard upper", "candidate_status": "UNKNOWN_UNTIL_TERMINAL_GENERATED_XML", "particle_mass_rescale": False, "threshold_widening": False},
            "information_gain": spec["information_gain"],
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "cpu_parent_binding": "required",
            "gpu": "none", "gpu_uuid": "none", "solver_launch": "forbidden", "hdf5_read": "forbidden", "launch_disabled": True, "new_solver": False, "parent_v4_review_required": True,
        },
        "output_protection": {"refuse_overwrite": True, "attempt_root_must_not_exist_at_dispatch": True},
        "solver_followup": "not included; any CFD requires separate source-bound review after terminal XML mass/geometry/motion audit",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    request_path = REQUEST_ROOT / f"{str(spec['sentinel_id']).lower().replace('-', '_')}_dp{str(spec['dp']).replace('.', 'p')}.json"
    if request_path.exists():
        existing = json.loads(request_path.read_text(encoding="utf-8"))
        existing_hashes = existing.get("input_hashes", {})
        expected_hashes = request.get("input_hashes", {})
        mismatches = {key for key in set(existing_hashes) | set(expected_hashes) if existing_hashes.get(key) != expected_hashes.get(key)}
        builder_path = str(Path(__file__).resolve())
        if mismatches == {builder_path} and existing.get("command") == request.get("command"):
            atomic_json(request_path, request, replace=True)
            return request, request_path
        if mismatches or existing.get("command") != request.get("command"):
            raise ValueError(f"existing request differs from deterministic candidate: {request_path}")
        return existing, request_path
    atomic_json(request_path, request)
    return request, request_path


def build() -> Path:
    f1_base = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_sentinel_spatial_preflight_inputs_v1/F1_S2/original/F1_S2_SPATIAL_ORIGINAL_DP0p020000_Def.xml"
    source_def = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_STAGE1_DUAL_H340_DP020/root-stage1-dual-h340-actual-gencase-027/prepared/F1_STAGE1_DUAL_H340_DP020_Def.xml")
    source_xml = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_STAGE1_DUAL_H340_DP020/root-stage1-dual-h340-actual-gencase-027/prepared/F1_STAGE1_DUAL_H340_DP020.xml")
    source_receipt = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_STAGE1_DUAL_H340_DP020/root-stage1-dual-h340-actual-gencase-027/execution-receipt.json")
    specs = []
    for dp, relation in (("0.017", "15% finer than CURRENT dp=0.020"), ("0.0165", "17.5% finer than CURRENT dp=0.020"), ("0.016", "20% finer than CURRENT dp=0.020")):
        token = f"{float(dp):.6f}".replace(".", "p")
        specs.append({
            "sentinel_id": "F1-S2", "family_id": "F1",
            "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
            "grid_role": "interval_information_gain_ge10pct_spacing",
            "dp": dp, "case_id": f"F1_S2_SPATIAL_INTERVAL_DP{token}",
            "attempt_id": f"f1-s2-spatial-interval-dp{token}-v2-root-001",
            "output_root": f"/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_S2_SPATIAL_INTERVAL_DP{token}/f1-s2-spatial-interval-dp{token}-v2-root-001",
            "base_def": str(f1_base), "current_source_def": str(source_def),
            "source_xmls": [str(source_xml)], "source_inputs": [str(source_receipt)],
            "base_request": str(REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-sentinel-spatial-preflight-v1/f1_s2_spatial_original_dp0p020000.json"),
            "estimated_storage_bytes": 67108864,
            "prior_grid_evidence": {"source_mass_kg": 340.0, "current_dp_m": 0.020, "coarse_dp_m": 0.025, "coarse_relative_error_pct": 2.9412, "fine_dp_m": 0.016, "fine_relative_error_pct": -1.1828, "meaning": "new interval probes are deliberately >=10% spacing-separated from CURRENT; generated XML must decide count/lattice phase and whole-initial mass"},
            "spacing_relation": relation,
            "information_gain": "bounded interval probes test lattice phase/count at materially distinct spacing while preserving exact continuous dual-head geometry, fill and controls; not a mass-only acceptance search",
        })
    entries = []
    request_paths = []
    for spec in specs:
        request, path = make_candidate(spec)
        request_paths.append(str(path))
        entries.append({"sentinel_id": spec["sentinel_id"], "case_id": spec["case_id"], "request": str(path), "candidate_def": request["source_binding"]["candidate_def"], "source_identity": request["source_binding"]["continuous_source_xml"], "dp_m": spec["dp"], "spacing_separation_fraction": request["source_binding"]["spacing_separation_fraction"], "spacing_relation": spec["spacing_relation"], "status": "PREPARED_LAUNCH_DISABLED", "mass_status": "UNKNOWN_UNTIL_TERMINAL_GENERATED_XML", "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}})
    queue = {"schema": "ds02.stage2.infogain-gencase-queue.v2", "status": "PREPARED_LAUNCH_DISABLED", "source_scope": "F1-S2 exact CURRENT identity; three interval candidates only; no family extrapolation", "candidate_count": len(entries), "candidates": entries, "request_paths": request_paths, "guard": {"runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden", "hdf5_read": "forbidden"}, "mass_gate": {"whole_initial_target_pct": 1.0, "explicit_exception_upper_pct": 2.0, "above_upper": "HARD_FAIL", "particle_mass_rescale": False, "threshold_widening": False}, "notes": ["Candidates change only dp in new Def inputs; generated XML mass/count/phase remains UNKNOWN until parent runs GenCase.", "The 1-2% interval is a pre-registered marginal review exception only; it does not grant matched/scientific status.", "No CFD request is implied. Any follow-up must retain continuous geometry/control and independently audit mass, material blocks and phase."]}
    atomic_json(QUEUE_PATH, queue, replace=True)
    return QUEUE_PATH


if __name__ == "__main__":
    print(json.dumps({"queue": str(build())}, indent=2))
