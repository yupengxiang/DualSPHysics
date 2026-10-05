#!/usr/bin/env python3
"""Build the F3 fresh078 actual-converter-scope typed/XMF/render handoff.

This is metadata-only.  It reads JSON/source metadata and producer-supplied
hashes, imports the converter solely to call _physical_condition_scope and
canonical_hash under a temporary sys.modules entry, and never opens BI4,
CSV, H5, HDF5, VTK, or numerical arrays.  It never launches a worker.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

F3_WORKTREE = Path("/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
BASE_LAB = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3")
F3_LAB = F3_WORKTREE / "lagrangian-fluid-lab"
OLD = F3_LAB / "campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_077_f3_remaining14_typed_xmf_source_v1"
HERE = F3_LAB / "campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_078_f3_actual_converter_scope_typed_xmf_v1"
ACTUAL_BINDINGS = OLD / "metadata/actual-native-bindings.json"
SELECTION = OLD / "metadata/selection.json"
CONVERTER = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py"
CONVERTER_PYTHON = INTEGRATION / "lagrangian-fluid-lab/.venv/bin/python"
RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
NVME_WRAPPER = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_nvme_convert_v1.py"
F3_AUDIT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_f3_nvme_input_audit_v1.py"
DS_CONVERT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_convert.py"
ROOT142_LAUNCH = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/launch.py"
ROOT142_POLICY = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/policy-check.json"
ROOT142_SOURCE = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/source-policy-contract.json"
RESOURCE_APPROVAL = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
ROOT134_POLICY = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py"
RENDERER = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_renderer_proxy_lifetime_diagnostic_023/render.py"
EXPORT_XMF = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_repair_a_short51_actual_typed_bed_pipeline_105/workers/export_xmf.py"
N3_SPEC = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_090_stage1_f4_root242_typed_xmf_render_bind_v1/render/n3-vector-spec.json"
DECODER = BASE_LAB / "campaigns/l1-resume/artifacts/bi4_dump"
PARTVTK = BASE_LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
DECODER_SHA = "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e"
PARTVTK_SHA = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
FRESH_ID = "fresh078"
SCOPE_ID = "F3_STAGE1_FIRST24_AY0250_AY0750_VISUAL_V1"
BAD_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".npy", ".npz", ".gif"}
MODULE_NAME = "_ds_data02_direct_convert_fresh078_scope_probe"


def load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    path = Path(path).resolve()
    if path.suffix.lower() in BAD_SUFFIXES:
        raise AssertionError(f"scientific payload hashing is forbidden: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(path: Path) -> Path:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def binding(path: Path, known_sha: str | None = None) -> dict[str, Any]:
    path = require(path)
    return {"path": str(path), "sha256": known_sha if known_sha is not None else sha256_file(path)}


def safe_converter_scope(owner: Mapping[str, Any]) -> tuple[dict[str, Any], str, str]:
    """Import the converter under a temporary module name and restore sys.modules."""
    source = require(CONVERTER)
    previous = sys.modules.get(MODULE_NAME)
    spec = importlib.util.spec_from_file_location(MODULE_NAME, source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load converter module spec: {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
        scope = module._physical_condition_scope(owner)
        digest = module.canonical_hash(scope)
    finally:
        if previous is None:
            sys.modules.pop(MODULE_NAME, None)
        else:
            sys.modules[MODULE_NAME] = previous
    if scope.get("schema") != "legacy-owner-scope.v0":
        raise AssertionError("fresh077 owner unexpectedly acquired an explicit physical_binding")
    return dict(scope), str(digest), sha256_file(source)


def replace_strings(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [replace_strings(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: replace_strings(item, old, new) for key, item in value.items()}
    return value


def ensure_input(request: dict[str, Any], path: Path, digest: str | None) -> None:
    path = Path(path).resolve()
    files = request.setdefault("input_files", [])
    if str(path) not in files:
        files.append(str(path))
    hashes = request.setdefault("input_sha256", {})
    hashes[str(path)] = digest


def remove_input(request: dict[str, Any], path: Path) -> None:
    stale = str(Path(path).resolve())
    request["input_files"] = [item for item in request.get("input_files", []) if str(item) != stale]
    request.setdefault("input_sha256", {}).pop(stale, None)


def set_arg(command: list[Any], flag: str, value: str) -> None:
    if flag in command:
        index = command.index(flag)
        if index + 1 >= len(command):
            raise AssertionError(f"missing value for {flag}")
        command[index + 1] = value
        return
    insert_at = command.index("--keep-validation-csv") if "--keep-validation-csv" in command else len(command)
    command[insert_at:insert_at] = [flag, value]


def actual_native(row: Mapping[str, Any]) -> dict[str, Any]:
    native = row["actual_native_binding"]["native_receipt"]
    quality = row["actual_native_binding"]["native_quality"]
    if native.get("status") != "completed" or native.get("returncode") != 0:
        raise AssertionError(f"native receipt is not completed/0: {row['case_id']}")
    expected = {"total_particles": 179208, "fixed_particles": 111708, "fluid_particles": 67500, "moving_particles": 0, "dimension": 3}
    for key, value in expected.items():
        if native.get(key) != value or quality.get(key) != value:
            raise AssertionError(f"actual native contract drift {row['case_id']} {key}: {native.get(key)!r}/{quality.get(key)!r}")
    if native.get("expected_saved_frames") != 836 or quality.get("saved_frames") != 836:
        raise AssertionError(f"actual native frame contract drift {row['case_id']}: {native.get('expected_saved_frames')!r}/{quality.get('saved_frames')!r}")
    if native.get("actual_3d") is not True or quality.get("actual_3d") is not True:
        raise AssertionError(f"native is not genuine 3-D: {row['case_id']}")
    return copy.deepcopy(row["actual_native_binding"])


def file_hash_or_known(path: Path, old_hashes: Mapping[str, Any], *, known: str | None = None) -> str | None:
    path = Path(path).resolve()
    if known is not None:
        return known
    prior = old_hashes.get(str(path))
    if prior is not None:
        return str(prior)
    if path.suffix.lower() in BAD_SUFFIXES:
        return None
    return sha256_file(path)


def update_input_hashes(request: dict[str, Any], old_hashes: Mapping[str, Any], replacements: Mapping[str, str]) -> None:
    updated: dict[str, Any] = {}
    for key, value in old_hashes.items():
        new_key = key
        for old, new in replacements.items():
            new_key = new_key.replace(old, new)
        updated[new_key] = value
    request["input_sha256"] = updated
    for path in request.get("input_files", []):
        request["input_sha256"].setdefault(str(path), None)


def make_owner(old_owner: Mapping[str, Any], scope: Mapping[str, Any], actual_hash: str, converter_sha: str, source_hash: str, source_tuple: Mapping[str, Any], native: Mapping[str, Any], new_path: Path) -> dict[str, Any]:
    owner = copy.deepcopy(old_owner)
    owner["fresh_id"] = FRESH_ID
    owner["physical_condition_sha256"] = actual_hash
    owner["source_physical_condition_sha256"] = source_hash
    owner["source_parameter_tuple"] = copy.deepcopy(source_tuple)
    owner["source_canonical_physical_binding"] = copy.deepcopy(old_owner["canonical_physical_binding"])
    owner["actual_converter_physical_condition_scope"] = copy.deepcopy(scope)
    owner["actual_converter_physical_condition_scope_sha256"] = actual_hash
    owner["physical_condition_hash_scope"] = "actual ds_data02_direct_convert._physical_condition_scope(owner), legacy-owner-scope.v0; source ds-data-02.v1 summary/hash retained separately"
    owner["actual_converter_provenance"] = {
        "module": str(CONVERTER.resolve()),
        "module_sha256": converter_sha,
        "import_method": "temporary sys.modules entry restored after _physical_condition_scope/canonical_hash call",
        "function": "_physical_condition_scope",
        "canonical_hash_function": "canonical_hash",
        "source_owner_had_explicit_physical_binding": False,
        "scope_hash_is_actual_conversion_identity": True,
    }
    owner["conversion_input_contract"] = {
        "decoder": binding(DECODER, DECODER_SHA),
        "partvtk": binding(PARTVTK, PARTVTK_SHA),
        "decoder_hash_source": "Root supplied fixed executable digest; fresh078 did not execute or rehash scientific payloads",
        "partvtk_hash_source": "Root supplied official executable digest; fresh078 did not execute PartVTK",
    }
    owner["source_plan_binding"]["source_plan_condition_sha256"] = source_hash
    owner["source_plan_binding"]["actual_converter_scope_sha256"] = actual_hash
    owner["source_plan_binding"]["actual_converter_scope_schema"] = scope["schema"]
    owner["status"] = "source_only_disabled_actual_native_bound_pending_typed_conversion_actual_scope"
    owner["typed_scope_provenance"] = {
        "scope_id": SCOPE_ID,
        "physical_condition_sha256_used_by_conversion": actual_hash,
        "source_physical_condition_sha256": source_hash,
        "source_parameter_tuple": copy.deepcopy(source_tuple),
        "typed_receipt_sha256": None,
        "conversion_report_sha256": None,
        "trajectory_h5_sha256": None,
        "xmf_sha256": None,
        "render_hashes": None,
    }
    owner["source_only"] = True
    owner["execution_allowed"] = False
    owner["native_full836_binding"] = copy.deepcopy(native["native_receipt"])
    owner["native_full836_binding"]["quality"] = copy.deepcopy(native["native_quality"])
    owner["actual_gencase_receipt"] = copy.deepcopy(native["genuine_gencase_receipt"])
    owner["provenance_semantics"] = "actual native/GenCase evidence is producer metadata; no typed/H5/XMF/render/Q-N/precision claim"
    return owner


def common_scope_fields(req: dict[str, Any], scope: Mapping[str, Any], actual_hash: str, source_hash: str, source_tuple: Mapping[str, Any]) -> None:
    req["fresh_id"] = FRESH_ID
    req["scope_id"] = SCOPE_ID
    req["physical_condition_sha256"] = actual_hash
    req["source_physical_condition_sha256"] = source_hash
    req["source_parameter_tuple"] = copy.deepcopy(source_tuple)
    req["actual_converter_physical_condition_scope"] = copy.deepcopy(scope)
    req["actual_converter_physical_condition_scope_sha256"] = actual_hash
    req["physical_condition_hash_scope"] = "actual ds_data02_direct_convert._physical_condition_scope(owner), legacy-owner-scope.v0; original source condition/hash is retained separately"
    req["source_canonical_physical_binding"] = copy.deepcopy(req.get("canonical_physical_binding")) if req.get("canonical_physical_binding") else None
    req["source_and_actual_scopes_are_distinct"] = True
    req["q_n"] = "not_granted"
    req["production_approval"] = "none"
    req["numerical_precision_status"] = "not_accepted"
    req["source_only"] = True
    req["execution_allowed"] = False
    req["launch_allowed"] = False
    req["launch_owner"] = "root"


def build() -> None:
    if not OLD.is_dir():
        raise FileNotFoundError(OLD)
    require(ACTUAL_BINDINGS)
    require(SELECTION)
    require(CONVERTER)
    require(CONVERTER_PYTHON)
    require(DECODER)
    require(PARTVTK)
    require(N3_SPEC)
    selection = load(SELECTION)
    actual_doc = load(ACTUAL_BINDINGS)
    rows_by_id = {str(row["case_id"]): row for row in selection["cases"]}
    actual_by_id = {str(row["case_id"]): row for row in actual_doc["cases"]}
    case_ids = [str(case_id) for case_id in selection["included_case_ids"]]
    if len(case_ids) != 14 or set(case_ids) != set(actual_by_id):
        raise AssertionError("fresh077 selection/actual binding case set is not the expected 14")
    converter_sha = sha256_file(CONVERTER)
    n3_sha = sha256_file(N3_SPEC)
    cases: list[dict[str, Any]] = []
    for case_id in case_ids:
        old_owner_path = OLD / "owners" / f"{case_id}.json"
        old_typed_path = OLD / "requests/typed" / f"{case_id}.json"
        old_owner = load(old_owner_path)
        old_typed = load(old_typed_path)
        if old_owner.get("physical_binding") is not None:
            raise AssertionError(f"fresh077 owner unexpectedly has physical_binding: {case_id}")
        source_binding = old_owner.get("canonical_physical_binding")
        if not isinstance(source_binding, Mapping):
            raise AssertionError(f"source canonical physical binding missing: {case_id}")
        source_hash = str(source_binding["physical_condition_sha256"])
        source_tuple = source_binding["parameter_tuple"]
        scope, actual_hash, _ = safe_converter_scope(old_owner)
        native = actual_native(actual_by_id[case_id])
        if rows_by_id[case_id]["physical_condition_sha256"] != source_hash:
            raise AssertionError(f"selection/source physical hash drift: {case_id}")
        cases.append({
            "case_id": case_id,
            "selection": rows_by_id[case_id],
            "actual": actual_by_id[case_id],
            "native": native,
            "old_owner_path": old_owner_path.resolve(),
            "old_owner": old_owner,
            "old_typed_path": old_typed_path.resolve(),
            "old_typed": old_typed,
            "source_hash": source_hash,
            "source_tuple": copy.deepcopy(source_tuple),
            "scope": scope,
            "actual_hash": actual_hash,
        })
    for sub in ("metadata", "owners", "requests/typed", "requests/xmf", "requests/render"):
        (HERE / sub).mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for case in cases:
        cid = case["case_id"]
        owner_path = HERE / "owners" / f"{cid}.actual-converter-scope.owner.json"
        owner = make_owner(case["old_owner"], case["scope"], case["actual_hash"], converter_sha, case["source_hash"], case["source_tuple"], case["native"], owner_path)
        dump(owner_path, owner)
        owner_sha = sha256_file(owner_path)
        old_pkg = str(OLD.resolve())
        new_pkg = str(HERE.resolve())
        stale_owner_in_new_pkg = HERE / "owners" / f"{cid}.json"
        old_typed = case["old_typed"]
        typed = replace_strings(copy.deepcopy(old_typed), old_pkg, new_pkg)
        typed = replace_strings(typed, "-077", "-078")
        typed = replace_strings(typed, str(stale_owner_in_new_pkg.resolve()), str(owner_path.resolve()))
        common_scope_fields(typed, case["scope"], case["actual_hash"], case["source_hash"], case["source_tuple"])
        typed["attempt_id"] = f"root-stage1-f3-{cid.lower().replace('_stage1_dp006_p1000_', '-')}-full836-typed-nvme-078"
        typed["owner_metadata"] = {"path": str(owner_path.resolve()), "sha256": owner_sha}
        typed["actual_converter_owner"] = {"path": str(owner_path.resolve()), "sha256": owner_sha, "physical_condition_sha256": case["actual_hash"]}
        typed["source_owner"] = copy.deepcopy(case["old_typed"].get("source_owner"))
        typed["source_owner_original_condition_sha256"] = case["source_hash"]
        typed["native_full836_binding"] = copy.deepcopy(case["native"])
        typed["actual_native_binding"] = copy.deepcopy(case["actual"] ["actual_native_binding"])
        typed["command"] = [str(x) for x in typed["command"]]
        set_arg(typed["command"], "--decoder", str(DECODER.resolve()))
        set_arg(typed["command"], "--partvtk", str(PARTVTK.resolve()))
        set_arg(typed["command"], "--validation-dir", "{attempt_root}/partvtk-validation")
        typed["decoder_binding"] = binding(DECODER, DECODER_SHA)
        typed["partvtk_binding"] = binding(PARTVTK, PARTVTK_SHA)
        old_hashes = dict(case["old_typed"].get("input_sha256", {}))
        replacements = {old_pkg: new_pkg, "-077": "-078"}
        update_input_hashes(typed, old_hashes, replacements)
        remove_input(typed, stale_owner_in_new_pkg)
        ensure_input(typed, DECODER, DECODER_SHA)
        ensure_input(typed, PARTVTK, PARTVTK_SHA)
        typed["input_sha256"][str(owner_path.resolve())] = owner_sha
        typed_path = HERE / "requests/typed" / f"{cid}.json"
        dump(typed_path, typed)
        typed_sha = sha256_file(typed_path)
        old_xmf_binding_path = OLD / "requests/xmf" / f"{case['old_typed']['physical_case_id']}-xmf-binding.json"
        old_xmf_req_path = OLD / "requests/xmf" / f"{case['old_typed']['physical_case_id']}-normal-xmf-request.json"
        if case["old_typed"]["physical_case_id"].endswith("AY0640_STAGE1_BATCH8"):
            old_xmf_binding_path = OLD / "requests/xmf" / f"{case['old_typed']['physical_case_id']}-xmf-binding.json"
            old_xmf_req_path = OLD / "requests/xmf" / f"{case['old_typed']['physical_case_id']}-normal-xmf-request.json"
        old_xmf_binding = load(old_xmf_binding_path)
        old_xmf_req = load(old_xmf_req_path)
        xmf_binding = replace_strings(copy.deepcopy(old_xmf_binding), old_pkg, new_pkg)
        xmf_binding = replace_strings(xmf_binding, "-077", "-078")
        xmf_binding = replace_strings(xmf_binding, str(stale_owner_in_new_pkg.resolve()), str(owner_path.resolve()))
        common_scope_fields(xmf_binding, case["scope"], case["actual_hash"], case["source_hash"], case["source_tuple"])
        xmf_binding["fresh_id"] = FRESH_ID
        xmf_binding["canonical_physical_binding"] = copy.deepcopy(case["old_owner"]["canonical_physical_binding"])
        xmf_binding["source_plan_condition_sha256"] = case["source_hash"]
        xmf_binding["actual_converter_physical_condition_scope"] = copy.deepcopy(case["scope"])
        xmf_binding["actual_converter_physical_condition_scope_sha256"] = case["actual_hash"]
        xmf_binding["owner_and_input_lineage"]["owner"] = binding(owner_path, owner_sha)
        xmf_binding["owner_and_input_lineage"]["typed_request"] = binding(typed_path, typed_sha)
        xmf_binding["owner_and_input_lineage"]["actual_converter_scope"] = {"schema": case["scope"]["schema"], "sha256": case["actual_hash"]}
        xmf_binding["source_owner"] = copy.deepcopy(case["old_typed"].get("source_owner"))
        xmf_binding["n3_vector_spec"] = {"path": str(N3_SPEC.resolve()), "sha256": n3_sha, "field": "velocity", "components": ["vx", "vy", "vz"], "semantic_type": "N3", "preserve_all_native_fields": True}
        xmf_binding["renderer_contract"]["n3_vector_spec"] = copy.deepcopy(xmf_binding["n3_vector_spec"])
        xmf_binding_path = HERE / "requests/xmf" / old_xmf_binding_path.name
        dump(xmf_binding_path, xmf_binding)
        xmf_binding_sha = sha256_file(xmf_binding_path)
        xmf_req = replace_strings(copy.deepcopy(old_xmf_req), old_pkg, new_pkg)
        xmf_req = replace_strings(xmf_req, "-077", "-078")
        xmf_req = replace_strings(xmf_req, str(stale_owner_in_new_pkg.resolve()), str(owner_path.resolve()))
        common_scope_fields(xmf_req, case["scope"], case["actual_hash"], case["source_hash"], case["source_tuple"])
        xmf_req["fresh_id"] = FRESH_ID
        xmf_req["binding"] = {"path": str(xmf_binding_path.resolve()), "sha256": xmf_binding_sha}
        xmf_req["typed_request"] = {"path": str(typed_path.resolve()), "sha256": typed_sha}
        xmf_req["n3_vector_spec"] = copy.deepcopy(xmf_binding["n3_vector_spec"])
        xmf_req["owner_and_input_lineage"] = xmf_binding["owner_and_input_lineage"]
        xmf_req["owner_metadata"] = {"path": str(owner_path.resolve()), "sha256": owner_sha}
        xmf_req["input_sha256"] = dict(xmf_req.get("input_sha256", {}))
        update_input_hashes(xmf_req, xmf_req["input_sha256"], {old_pkg: new_pkg, "-077": "-078"})
        ensure_input(xmf_req, N3_SPEC, n3_sha)
        ensure_input(xmf_req, owner_path, owner_sha)
        ensure_input(xmf_req, typed_path, typed_sha)
        ensure_input(xmf_req, xmf_binding_path, xmf_binding_sha)
        remove_input(xmf_req, stale_owner_in_new_pkg)
        ensure_input(xmf_req, owner_path, owner_sha)
        xmf_req_path = HERE / "requests/xmf" / old_xmf_req_path.name
        dump(xmf_req_path, xmf_req)
        xmf_req_sha = sha256_file(xmf_req_path)
        old_render_path = OLD / "requests/render" / f"{old_xmf_req['physical_case_id']}-native023-render-request.json"
        old_render = load(old_render_path)
        render = replace_strings(copy.deepcopy(old_render), old_pkg, new_pkg)
        render = replace_strings(render, "-077", "-078")
        render = replace_strings(render, str(stale_owner_in_new_pkg.resolve()), str(owner_path.resolve()))
        common_scope_fields(render, case["scope"], case["actual_hash"], case["source_hash"], case["source_tuple"])
        render["fresh_id"] = FRESH_ID
        render["depends_on_normal_xmf_request"] = str(xmf_req_path.resolve())
        render["depends_on_normal_xmf_request_sha256"] = xmf_req_sha
        render["n3_vector_spec"] = copy.deepcopy(xmf_binding["n3_vector_spec"])
        render["renderer_contract"]["n3_vector_spec"] = copy.deepcopy(xmf_binding["n3_vector_spec"])
        render["owner_metadata"] = {"path": str(owner_path.resolve()), "sha256": owner_sha}
        render["typed_request"] = {"path": str(typed_path.resolve()), "sha256": typed_sha}
        render["xmf_binding"] = {"path": str(xmf_binding_path.resolve()), "sha256": xmf_binding_sha}
        render["input_sha256"] = dict(render.get("input_sha256", {}))
        update_input_hashes(render, render["input_sha256"], {old_pkg: new_pkg, "-077": "-078"})
        ensure_input(render, N3_SPEC, n3_sha)
        ensure_input(render, owner_path, owner_sha)
        ensure_input(render, typed_path, typed_sha)
        ensure_input(render, xmf_binding_path, xmf_binding_sha)
        ensure_input(render, xmf_req_path, xmf_req_sha)
        remove_input(render, stale_owner_in_new_pkg)
        ensure_input(render, owner_path, owner_sha)
        render_path = HERE / "requests/render" / old_render_path.name
        dump(render_path, render)
        render_sha = sha256_file(render_path)
        rows.append({
            "case_id": cid,
            "physical_case_id": case["old_owner"]["physical_case_id"],
            "source_parameter_tuple": case["source_tuple"],
            "source_physical_condition_sha256": case["source_hash"],
            "actual_converter_scope": case["scope"],
            "actual_converter_scope_sha256": case["actual_hash"],
            "native": copy.deepcopy(case["native"]),
            "genuine_gencase_receipt": copy.deepcopy(case["actual"]["actual_native_binding"]["genuine_gencase_receipt"]),
            "owner": binding(owner_path, owner_sha),
            "typed_request": binding(typed_path, typed_sha),
            "xmf_binding": binding(xmf_binding_path, xmf_binding_sha),
            "xmf_request": binding(xmf_req_path, xmf_req_sha),
            "render_request": binding(render_path, render_sha),
            "future_typed_receipt_sha256": None,
            "future_trajectory_h5_sha256": None,
            "future_xdmf_sha256": None,
            "future_render_hashes": None,
        })
    audit = {
        "schema": "ds02.f3.fresh078.actual-converter-scope-audit.v1",
        "family_id": "F3", "fresh_id": FRESH_ID, "source_only": True,
        "arrays_read": False, "jobs_started": False, "shared_state_modified": False,
        "converter": {"path": str(CONVERTER.resolve()), "sha256": converter_sha, "import": "temporary sys.modules entry restored after metadata-only calls", "function": "_physical_condition_scope", "canonical_hash": "canonical_hash"},
        "decoder": binding(DECODER, DECODER_SHA), "partvtk": binding(PARTVTK, PARTVTK_SHA),
        "scope_semantics": "The actual converter sees no explicit physical_binding in fresh077 owners and therefore emits legacy-owner-scope.v0. This actual scope/hash is used by fresh078 conversion requests; original source tuple/hash remain separate and are not silently replaced.",
        "cases": rows,
        "all_native_completed0": True,
        "all_counts": {"total_particles": 179208, "fixed_particles": 111708, "fluid_particles": 67500, "moving_particles": 0, "dimension": 3, "frames": 836},
    }
    dump(HERE / "metadata/actual-converter-scope-audit.json", audit)
    n3_binding = {"path": str(N3_SPEC.resolve()), "sha256": n3_sha, "field": "velocity", "components": ["vx", "vy", "vz"], "semantic_type": "N3", "preserve_all_native_fields": True, "source": "Root-reviewed n3-vector-spec; XMF worker's velocity DataItem remains a 3-component native vector"}
    dump(HERE / "metadata/decoder-partvtk-n3-contract.json", {"schema": "ds02.f3.fresh078.decoder-partvtk-n3-contract.v1", "source_only": True, "arrays_read": False, "decoder": binding(DECODER, DECODER_SHA), "partvtk": binding(PARTVTK, PARTVTK_SHA), "n3_vector_spec": n3_binding, "typed_command_repairs": ["base-lab bi4_dump path and fixed SHA bound", "base-lab PartVTK_linux64 path and fixed SHA bound", "explicit --partvtk and --validation-dir arguments present"], "xmf_contract": "export_xmf.py emits velocity as AttributeType=Vector with all native fields retained; Root023 render remains disabled until completed typed/XMF evidence"})
    dump(HERE / "metadata/selection.json", {"schema": "ds02.f3.fresh078.selection.v1", "fresh_id": FRESH_ID, "scope_id": SCOPE_ID, "case_count": len(rows), "cases": [{"case_id": row["case_id"], "physical_case_id": row["physical_case_id"], "source_parameter_tuple": row["source_parameter_tuple"], "source_physical_condition_sha256": row["source_physical_condition_sha256"], "actual_converter_scope_sha256": row["actual_converter_scope_sha256"], "native_status": row["native"]["native_receipt"]["status"], "native_returncode": row["native"]["native_receipt"]["returncode"], "typed_request": row["typed_request"], "future_typed": True} for row in rows], "source_only": True, "arrays_read": False, "jobs_started": False, "independent_case_count_increment": 0, "q_n": "not_granted", "production_approval": "none"})
    dump(HERE / "requests/typed-bindings.json", {"schema": "ds02.f3.fresh078.typed-bindings.v1", "fresh_id": FRESH_ID, "scope_id": SCOPE_ID, "source_only": True, "all_requests_disabled": True, "cases": [{"case_id": row["case_id"], "typed_request": row["typed_request"], "actual_converter_scope_sha256": row["actual_converter_scope_sha256"], "source_physical_condition_sha256": row["source_physical_condition_sha256"], "future_typed_receipt_sha256": None, "future_conversion_report_sha256": None, "future_h5_sha256": None} for row in rows]})
    dump(HERE / "requests/xmf-bindings.json", {"schema": "ds02.f3.fresh078.xmf-bindings.v1", "fresh_id": FRESH_ID, "scope_id": SCOPE_ID, "source_only": True, "all_requests_disabled": True, "n3_vector_spec": n3_binding, "cases": [{"case_id": row["case_id"], "xmf_binding": row["xmf_binding"], "normal_xmf_request": row["xmf_request"], "actual_converter_scope_sha256": row["actual_converter_scope_sha256"], "future_xdmf_sha256": None} for row in rows]})
    dump(HERE / "requests/render-bindings.json", {"schema": "ds02.f3.fresh078.render-bindings.v1", "fresh_id": FRESH_ID, "scope_id": SCOPE_ID, "source_only": True, "all_requests_disabled": True, "n3_vector_spec": n3_binding, "cases": [{"case_id": row["case_id"], "render_request": row["render_request"], "xmf_request": row["xmf_request"], "future_render_hashes": None, "visual_decision": None} for row in rows]})
    readme = f"""# F3 fresh078 actual converter scope and typed/XMF/render handoff

This source-only package preserves the fourteen fresh077 native conditions and binds their actual completed/0 full836 receipts: 179208 total particles, 111708 fixed, 67500 fluid, zero moving, genuine 3-D, and 836 saved frames through 8.35 s. No case count, Q-N, production, visual, or precision claim is added.

The fresh077 owners contain only a `canonical_physical_binding` summary and no explicit `physical_binding` object. The metadata-only builder imports the actual `ds_data02_direct_convert.py` under a temporary `sys.modules` name, calls `_physical_condition_scope(owner)` and `canonical_hash`, then restores the module entry. Each fresh078 owner records that actual `legacy-owner-scope.v0` scope/hash used by conversion. The original source parameter tuple and source physical-condition hash remain separately recorded; the actual scope hash is never presented as the source planned hash.

Typed requests are disabled and use the base-lab `campaigns/l1-resume/artifacts/bi4_dump` executable with Root's fixed digest `{DECODER_SHA}`. They also carry the official base-lab PartVTK executable with its fixed digest `{PARTVTK_SHA}`, explicit `--partvtk`, and explicit validation output. Future typed receipt/report/H5 hashes remain null. XMF and Root023 render requests are also disabled. The XMF contract explicitly binds the reviewed N3 velocity-vector spec (`velocity`, `vx/vy/vz`) and retains all native fields; future XMF/render hashes and visual decisions remain null.

The package reads JSON/source metadata only. It does not open or hash BI4, CSV, H5/HDF5, VTK, or numerical arrays; it does not start conversion, XMF, render, or any registered job; and it does not modify shared registry, runner, resource ledger, or historical fresh077 evidence.
"""
    (HERE / "README.md").write_text(readme, encoding="utf-8")
    shutil.copyfile(Path(__file__).resolve(), HERE / "build_fresh078.py")
    # The validator is copied by the outer source-only preparation step.
    manifest_files = []
    for path in sorted(HERE.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            manifest_files.append({"path": str(path.relative_to(HERE)), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    dump(HERE / "manifest.json", {"schema": "ds02.f3.fresh078.actual-converter-scope-typed-xmf-render-manifest.v1", "family_id": "F3", "fresh_id": FRESH_ID, "scope_id": SCOPE_ID, "case_count": len(rows), "case_ids": [row["case_id"] for row in rows], "source_only": True, "arrays_read": False, "jobs_started": False, "shared_state_modified": False, "independent_case_count_increment": 0, "all_native_full836_completed0": True, "native_contract": {"total_particles": 179208, "fixed_particles": 111708, "fluid_particles": 67500, "moving_particles": 0, "dimension": 3, "saved_frames": 836, "time_window_s": [0.0, 8.35], "save_interval_s": 0.01}, "actual_converter_scope": "legacy-owner-scope.v0 per-case hash recorded; original source tuple/hash retained separately", "decoder": binding(DECODER, DECODER_SHA), "partvtk": binding(PARTVTK, PARTVTK_SHA), "n3_vector_spec": n3_binding, "all_typed_requests_disabled": True, "all_xmf_requests_disabled": True, "all_render_requests_disabled": True, "future_hash_policy": {"typed_receipt_sha256": None, "conversion_report_sha256": None, "trajectory_h5_sha256": None, "xdmf_sha256": None, "render_hashes": None, "visual_decision": None, "q_n": "not_granted", "production_approval": "none"}, "files": manifest_files})
    print(json.dumps({"package": str(HERE), "cases": len(rows), "typed_disabled": len(rows), "xmf_disabled": len(rows), "render_disabled": len(rows), "arrays_read": False}, indent=2))


if __name__ == "__main__":
    build()
