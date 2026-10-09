#!/usr/bin/env python3
"""Prepare the bounded F1-S2 DP020 SaveDt/CFL comparison pair (ROOT271).

This is a source-only builder.  It derives two independent ``ds02.request.v1``
requests from the already reviewed ROOT265 source closure:

* same-CFL: CFL ``.2/.2`` and SaveDt/output interval ``.005``;
* half-CFL: CFL ``.1/.1`` and the same SaveDt/output interval ``.005``.

Both requests use the unchanged DP020 XML/BI4/GenCase source, owner contract,
geometry, controls, and solver closure.  The bounded request window is 0.5 s
(``-tmax:0.5``) so the parent can run a cheap source/control canary before
deciding whether a full-window study is warranted.  The historical completed
receipt used ``-tout:0.01`` over the full four-second window; it is retained as
lineage and output-control evidence only.  It is never presented as an actual
``.005`` same-CFL baseline or as evidence for a CFL comparison.

The builder imports the committed ROOT265 builder for its already audited
source checks and static closure.  It does not read the BI4 or any native/H5
payload.  The parent runner must materialize fresh copies after reservation,
perform pre/post SHA and full-stat checks, and then decide whether to launch
either request.  This module itself never launches a solver or allocates a
GPU.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any


REQUEST_SCHEMA = "ds02.request.v1"
VARIANT_SCHEMA = "ds02.stage2.f1-s2.medium-savedt-cfl-pair-source-request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.medium-savedt-cfl-pair-source-manifest.v1"
ROOT271_STATUS = "SOURCE_PREPARED_LAUNCH_DISABLED_ROOT271"

# A source-repo override is useful only for a reviewer running this file from
# an isolated worktree before cherry-picking it into the primary worktree.  In
# the primary worktree the default is the repository containing this file.
REPO = Path(
    os.environ.get("DS02_STAGE2_REPO_ROOT", str(Path(__file__).resolve().parents[5]))
).resolve()
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
ROOT265_REL = Path(
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_f1_s2_medium_half_cfl_solver_request_root265_v1.py"
)
ROOT265_PATH = REPO / ROOT265_REL
BUILDER_REL = Path(
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_f1_s2_medium_savedt_cfl_pair_request_root271_v1.py"
)
# The output directory is deliberately separate from REPO so an isolated
# reviewer can build a disposable manifest using primary source paths.  Normal
# parent use leaves it at REPO and therefore writes under the committed tree.
OUTPUT_REPO = Path(
    os.environ.get("DS02_STAGE2_OUTPUT_ROOT", str(REPO))
).resolve()
REQUEST_DIR = OUTPUT_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/source-prepared271"
SAME_REQUEST_PATH = REQUEST_DIR / "f1_s2_medium_dp020_same_cfl_savedt_0p5s_solver_root271_v1.json"
HALF_REQUEST_PATH = REQUEST_DIR / "f1_s2_medium_dp020_half_cfl_savedt_0p5s_solver_root271_v1.json"
PAIR_MANIFEST_PATH = REQUEST_DIR / "f1_s2_medium_dp020_savedt_cfl_pair_manifest_root271_v1.json"

SHORT_WINDOW_S = 0.5
SHORT_PLANNED_FRAMES = 101
SAVEDT_INTERVAL_S = 0.005
SAME_CFL = ["0.2", "0.2"]
HALF_CFL = ["0.1", "0.1"]


def _load_root265() -> Any:
    """Load ROOT265 without adding its directory to ``sys.path``."""
    if not ROOT265_PATH.is_file():
        raise FileNotFoundError(
            f"ROOT265 dependency is missing: {ROOT265_PATH}; cherry-pick ROOT265 first"
        )
    spec = importlib.util.spec_from_file_location("stage2_root265_source", ROOT265_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load ROOT265 builder: {ROOT265_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_file() and path.read_bytes() == payload:
            return
        raise FileExistsError(f"refusing to overwrite differing file: {path}")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_bytes(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def _canonical_hash(value: dict[str, Any]) -> str:
    body = copy.deepcopy(value)
    body.pop("request_sha256", None)
    body.pop("sha256", None)
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _record(path: Path, label: str, root265: Any) -> dict[str, Any]:
    return root265.regular_record(path, label)


def _validate_overlay(source_text: str, overlay_text: str, expected_cfl: list[str], root265: Any) -> dict[str, Any]:
    """Validate one overlay and return its bounded semantic diff."""
    source_cfl = root265.cfl_values(source_text)
    overlay_cfl = root265.cfl_values(overlay_text)
    if source_cfl != ["0.2", "0.2"]:
        raise ValueError(f"unexpected CURRENT CFL values: {source_cfl}")
    if overlay_cfl != expected_cfl:
        raise ValueError(f"unexpected overlay CFL values: {overlay_cfl}; expected {expected_cfl}")
    expected_savedt = {
        "start": "0", "finish": "0", "interval": "0.005",
        "fullinfo": "0", "alldt": "1", "active": "true",
    }
    if root265.savedt_values(overlay_text) != expected_savedt:
        raise ValueError(f"unexpected SaveDt values: {root265.savedt_values(overlay_text)}")
    if root265.savedt_values(source_text) is not None:
        raise ValueError("CURRENT source unexpectedly contains SaveDt")
    if root265.canonical_xml(source_text) != root265.canonical_xml(
        overlay_text, restore_cfl=source_cfl
    ):
        raise ValueError("overlay changed semantics outside CFL and SaveDt")
    if root265.xml_parameters(source_text) != root265.xml_parameters(overlay_text):
        raise ValueError("overlay changed execution parameters")
    return {
        "source_cfl_values": source_cfl,
        "overlay_cfl_values": overlay_cfl,
        "savedt": expected_savedt,
        "source_semantics_equal_after_restoring_cfl": True,
        "declared_diff": [
            {"field": "execution.special.savedt", "value": ".005", "scope": "common_pair_output_contract"},
            {"field": "cflnumber[0]", "from": ".2", "to": expected_cfl[0], "scope": "same_to_half_cfl" if expected_cfl == HALF_CFL else "same_cfl_member"},
            {"field": "cflnumber[1]", "from": ".2", "to": expected_cfl[1], "scope": "same_to_half_cfl" if expected_cfl == HALF_CFL else "same_cfl_member"},
        ],
    }


def _proof_status(root265: Any) -> dict[str, Any]:
    """Use only the small ROOT260 proof to classify existing baseline evidence."""
    proof = root265.load_json(root265.ROOT260_PROOF)
    absent = proof.get("F1_S2_half_CFL_actual_pair") == "ABSENT_FROM_THIS_BOUND_EVIDENCE"
    baseline = root265.load_json(root265.BASELINE_RECEIPT)
    command = [str(x) for x in baseline.get("command", [])]
    historical_tout = next((x for x in command if str(x).startswith("-tout:")), None)
    historical_tmax = next((x for x in command if str(x).startswith("-tmax:")), None)
    return {
        "same_cfl_savedt_actual_baseline": {
            "status": "ABSENT_FROM_BOUND_EVIDENCE",
            "evidence_scope": "ROOT260 proof plus the one bound completed DP020 receipt; no recursive DATA scan",
            "root260_half_cfl_pair_field": proof.get("F1_S2_half_CFL_actual_pair"),
            "historical_completed_receipt": root265.regular_record(root265.BASELINE_RECEIPT, "historical DP020 solver receipt"),
            "historical_command": command,
            "historical_tmax": historical_tmax,
            "historical_tout": historical_tout,
            "historical_output_contract": "0.01 s; not the .005 pair baseline",
            "reusable_for_cfl_comparison": False,
            "classification_is_conservative": True,
        },
        "root260_absence_assertion": absent,
    }


def _frozen_budget(root265: Any) -> dict[str, Any]:
    contract = root265.load_json(root265.CALIBRATION_CONTRACT)
    budget = contract.get("frozen_error_budget")
    if not isinstance(budget, dict):
        raise ValueError("calibration contract has no frozen_error_budget")
    # Copy exact registered values; do not derive or widen them here.
    return copy.deepcopy(budget)


def _member(
    base: dict[str, Any],
    root265: Any,
    *,
    mode: str,
    overlay: Path,
    overlay_manifest: Path,
    cfl: list[str],
    request_path: Path,
) -> dict[str, Any]:
    source_text = root265.SOURCE_XML.read_text(encoding="utf-8")
    overlay_text = overlay.read_text(encoding="utf-8")
    semantics = _validate_overlay(source_text, overlay_text, cfl, root265)
    member = copy.deepcopy(base)
    stem = f"F1_STAGE1_DUAL_H340_DP020_{mode}_savedt_0p5s"
    case_token = "SAME_CFL" if mode == "same_cfl" else "HALF_CFL"
    member["variant_schema"] = VARIANT_SCHEMA
    member["status"] = ROOT271_STATUS
    member["case_id"] = f"F1_S2_MEDIUM_DP020_SAVEDT_{case_token}_0P5S_ROOT271"
    member["attempt_id"] = f"f1-s2-medium-dp020-savedt-{mode}-0p5s-root271-001"
    member["qualification_stage"] = "stage2_f1_s2_medium_savedt_cfl_bounded_pair_source_prepared_pending_parent_guard"
    member["expected_native_frames"] = SHORT_PLANNED_FRAMES
    member["physical_window_s"] = [0.0, SHORT_WINDOW_S]
    member["save_interval_s"] = SAVEDT_INTERVAL_S
    member["command"] = [
        str(root265.SOLVER),
        f"{{attempt_root}}/solver-input/{stem}",
        "{attempt_root}/solver_output",
        f"-tmax:{SHORT_WINDOW_S:g}",
        "-tout:0.005",
    ]
    binding = member["source_binding"]
    binding["schema"] = "ds02.stage2.f1-s2.medium-savedt-cfl-pair-source-binding.v1"
    binding["source_request_namespace"] = "ROOT271 source-prepared bounded pair; parent must create a fresh root-forward request"
    binding["overlay_xml"] = _record(overlay, f"ROOT271 {mode} SaveDt XML", root265)
    binding["overlay_manifest"] = _record(overlay_manifest, f"ROOT271 {mode} overlay manifest", root265)
    binding["xml_semantics"] = semantics
    binding["baseline_control"]["role"] = "historical endpoint/control lineage only; .01 output is not a .005 same-CFL baseline"
    binding["pair_control"] = {
        "pair_schema": "ds02.stage2.f1-s2.medium-savedt-cfl-pair.v1",
        "member_mode": mode,
        "same_cfl_values": SAME_CFL,
        "half_cfl_values": HALF_CFL,
        "this_member_cfl_values": cfl,
        "common_output_interval_s": SAVEDT_INTERVAL_S,
        "common_requested_window_s": [0.0, SHORT_WINDOW_S],
        "full_reference_window_s": [0.0, float(root265.WINDOW_END)],
        "same_to_half_single_variable": "only cflnumber[0:2] changes .2 -> .1; SaveDt=.005, tmax=.5, tout=.005 and source/geometry/control remain common",
        "historical_baseline_is_output_only": True,
        "historical_baseline_tout_s": 0.01,
        "historical_baseline_not_same_cfl_savedt_baseline": True,
    }
    materialization = binding["materialization"]
    materialization["target_prefix"] = f"{{attempt_root}}/solver-input/{stem}"
    materialization["target_xml"] = f"{{attempt_root}}/solver-input/{stem}.xml"
    materialization["target_bi4"] = f"{{attempt_root}}/solver-input/{stem}.bi4"
    materialization["target_output"] = "{attempt_root}/solver_output"
    materialization["copy_xml_from"] = str(overlay.resolve())
    materialization["copy_mode"] = "byte_for_byte_copy_to_new_inode_after_parent_reservation"
    member["control_change_contract"] = {
        "historical_to_pair": [
            "historical completed DP020 receipt used -tmax:4 and -tout:0.01 with no SaveDt node",
            "both ROOT271 members are bounded to tmax=.5, SaveDt=.005, and -tout:.005",
            "this is a common output/window contract change and is not assigned to CFL",
        ],
        "same_to_half": [
            "same CURRENT DP020 BI4, owner, geometry, source controls, output contract, and .5 s window",
            "only the two execution XML cflnumber values change .2 -> .1",
            "no -cfl CLI override is present",
        ],
        "historical_baseline_reuse": "forbidden_for_.005_CFL_comparison",
        "runtime_join_required": True,
    }
    owner_admission = member["owner_admission"]
    owner_admission["full_native_dynamic_support"] = "UNKNOWN_PENDING_PARENT_GUARDED_PAIR"
    owner_admission["half_cfl_absence_is_not_an_admission_rejection"] = True
    owner_admission["admission_state"] = "SOURCE_READY_FOR_PARENT_GUARD; SCIENTIFIC_QUALIFICATION_PENDING"
    owner_admission["minimal_parent_evidence"] = [
        "fresh after-reservation XML/BI4 copies with full pre/post SHA and dev/ino/mtime/ctime checks",
        "terminal receipt for each member with actual launch argv and no hidden -cfl/-tout override",
        "RunPARTs.csv, Run.out, and DtAllInfo join for the bounded .5 s window",
        "separate native frame-0/support and selected-field observer; no mass rescale",
        "fresh UUID GPU lease and storage/CPU fee closure recorded by the parent",
    ]
    member["output_plan"] = {
        "native_output": "retain every actual Part_*.bi4 in the bounded .5 s window",
        "planned_frames": SHORT_PLANNED_FRAMES,
        "queries_s": [0.0, 0.25, 0.5],
        "actual_saved_time_source": "RunPARTs.csv from each terminal receipt",
        "postrun_checks": [
            "actual final saved time and terminal convention",
            "DtAllInfo row/time relation and Run.out DTsMin/clamp semantics",
            "same/half common query brackets; no interpolation unless a separate registered calibration permits it",
            "native MF/role/finite support in a separate guarded observer",
        ],
        "interpolation": "forbidden",
        "neighbor_grid_truth": "forbidden",
        "comparison_scope": "bounded output/CFL diagnostic only; not full-window scientific qualification",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    member["admission_blockers_and_minimum_repairs"] = [
        {
            "blocker": "No completed same-CFL .005 actual DP020 baseline is bound",
            "evidence": "ROOT260 absence field plus historical receipt -tout:0.01",
            "minimum_repair": "run ROOT271 same member first under a fresh parent lease; it becomes the .005 reference only after terminal receipt and source joins",
        },
        {
            "blocker": "No completed half-CFL .1/.005 member is bound",
            "evidence": "ROOT260.F1_S2_half_CFL_actual_pair == ABSENT_FROM_THIS_BOUND_EVIDENCE",
            "minimum_repair": "run ROOT271 half member with the same fresh source closure; absence is pending work, not an admission rejection",
        },
        {
            "blocker": "Runtime control and saved-time axis are not proved by XML labels",
            "evidence": "CFL entrypoint contract requires ReadXmlRun/launch argv/receipt precedence",
            "minimum_repair": "join actual receipt.request, execution launch argv, XML pre/post SHA, RunPARTs, Run.out and DtAllInfo",
        },
        {
            "blocker": "Contact/overlap and full dynamic support are not closed by the owner/frame-0 proofs",
            "evidence": "ROOT227 owner and ROOT233 frame-0 evidence grant limited diagnostic scope only",
            "minimum_repair": "parent-gated frame-0/native support observer; report fluid/fixed/moving roles separately",
        },
    ]
    member["comparison_contract"] = {
        "schema": "ds02.stage2.f1-s2.medium-savedt-cfl-comparison.v1",
        "pair_id": "F1-S2-DP020-SAVEDT005-0P5S",
        "same_member": "f1_s2_medium_dp020_same_cfl_savedt_0p5s_solver_root271_v1.json",
        "half_member": "f1_s2_medium_dp020_half_cfl_savedt_0p5s_solver_root271_v1.json",
        "shared_initial_state": True,
        "shared_owner_geometry_controls": True,
        "common_output_contract": {"savedt_interval_s": SAVEDT_INTERVAL_S, "tout_s": SAVEDT_INTERVAL_S, "window_s": [0.0, SHORT_WINDOW_S]},
        "contrast": "same CFL .2/.2 versus half CFL .1/.1 only",
        "historical_baseline": "output_contract_only_.01_full4s; excluded from CFL contrast",
        "actual_pair_baseline_status": "ABSENT_FROM_BOUND_EVIDENCE",
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    member["request_sha256"] = _canonical_hash(member)
    return member


def build_pair() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    root265 = _load_root265()
    base, base_manifest = root265.build_without_bi4_hash()
    source_text = root265.SOURCE_XML.read_text(encoding="utf-8")
    same = _member(
        base, root265, mode="same_cfl", overlay=root265.SAME_XML,
        overlay_manifest=root265.SAME_MANIFEST, cfl=SAME_CFL,
        request_path=SAME_REQUEST_PATH,
    )
    half = _member(
        base, root265, mode="half_cfl", overlay=root265.HALF_XML,
        overlay_manifest=root265.HALF_MANIFEST, cfl=HALF_CFL,
        request_path=HALF_REQUEST_PATH,
    )
    baseline = _proof_status(root265)
    budget = _frozen_budget(root265)
    # The inherited closure includes ROOT265.  Add this builder as a separate
    # source record; do not remove the older builder because it is an imported
    # implementation dependency, not an actual run input.
    builder_path = REPO / BUILDER_REL
    if not builder_path.is_file():
        # Isolated pre-commit self-tests may not have the new file at its
        # canonical primary path yet.  Production --prepare always does.
        builder_path = Path(__file__).resolve()
    builder_record = _record(builder_path, "ROOT271 pair request builder", root265)
    for member in (same, half):
        member["input_files"] = list(dict.fromkeys(member["input_files"] + [builder_record["path"]]))
        member["input_sha256"][builder_record["path"]] = builder_record["sha256"]
        member["input_records"][builder_record["path"]] = builder_record
        member["source_binding"]["source_records"]["ROOT271_PAIR_BUILDER"] = {
            "builder": builder_record,
            "dependency": "additive wrapper around ROOT265 source-only closure",
        }
        member["source_binding"]["frozen_error_budget"] = budget
        member["source_binding"]["existing_baseline_evidence"] = baseline
        member["source_binding"]["window_contract"] = {
            "bounded_request_window_s": [0.0, SHORT_WINDOW_S],
            "full_reference_window_s": [0.0, float(root265.WINDOW_END)],
            "bounded_canary_is_not_full_reference": True,
        }
        member["source_binding"]["actual_medium_savedt_same_cfl_baseline"] = baseline[
            "same_cfl_savedt_actual_baseline"
        ]
        member["source_binding"]["admission_provenance"] = {
            "owner": "ROOT227 340 kg continuous owner box",
            "initial_support": "ROOT233 limited frame-0 support only",
            "native_storage": "ROOT207 + ROOT217 decoder/storage calibration; world orientation remains UNKNOWN",
            "cfl_entrypoint": "ROOT260 source/entrypoint audit; no half-CFL actual pair in that evidence",
            "task_contract": "ROOT calibration v5 frozen_error_budget copied verbatim",
        }
        member["source_binding"]["parent_only_checks"] = [
            "actual request/receipt identity and source root join",
            "actual launch argv and execution constants",
            "copy source BI4 to a new inode and verify full pre/post stat/SHA",
            "retain actual RunPARTs/Run.out/DtAllInfo and native output until observer closes",
        ]
    pair_manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": ROOT271_STATUS,
        "pair_id": "F1-S2-DP020-SAVEDT005-0P5S",
        "source_only": True,
        "launch_disabled": True,
        "solver_started": False,
        "gpu_started": False,
        "native_payload_read": False,
        "hdf5_read": False,
        "actual_medium_savedt_same_cfl_baseline": baseline[
            "same_cfl_savedt_actual_baseline"
        ],
        "members": [
            {
                "mode": "same_cfl",
                "request_path": str(SAME_REQUEST_PATH.resolve()),
                "request_sha256": same["request_sha256"],
                "cfl_values": SAME_CFL,
                "savedt_interval_s": SAVEDT_INTERVAL_S,
                "window_s": [0.0, SHORT_WINDOW_S],
            },
            {
                "mode": "half_cfl",
                "request_path": str(HALF_REQUEST_PATH.resolve()),
                "request_sha256": half["request_sha256"],
                "cfl_values": HALF_CFL,
                "savedt_interval_s": SAVEDT_INTERVAL_S,
                "window_s": [0.0, SHORT_WINDOW_S],
            },
        ],
        "shared_source": {
            "current_xml": same["source_binding"]["current_xml"],
            "current_bi4": same["source_binding"]["current_bi4"],
            "gencase_receipt": same["source_binding"]["gencase_receipt"],
            "physical_case_id": same["physical_case_id"],
            "grid": same["grid"],
            "owner_mass_kg": 340.0,
            "no_mass_rescale": True,
        },
        "control_contract": {
            "same_to_half_only_variable": "cflnumber .2/.2 -> .1/.1",
            "common_output_contract": "SaveDt interval .005, CLI -tout:.005",
            "historical_baseline": "completed -tout:.01 full-window receipt; output lineage only",
            "no_interpolation": True,
            "neighbor_grid_truth": False,
        },
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "builder": builder_record,
        "root265_dependency": _record(ROOT265_PATH, "ROOT265 imported source builder", root265),
    }
    return same, half, pair_manifest


def self_test() -> None:
    same, half, manifest = build_pair()
    assert same["status"] == ROOT271_STATUS
    assert half["status"] == ROOT271_STATUS
    assert same["physical_window_s"] == [0.0, SHORT_WINDOW_S]
    assert half["physical_window_s"] == [0.0, SHORT_WINDOW_S]
    assert same["save_interval_s"] == half["save_interval_s"] == SAVEDT_INTERVAL_S
    assert same["source_binding"]["xml_semantics"]["overlay_cfl_values"] == SAME_CFL
    assert half["source_binding"]["xml_semantics"]["overlay_cfl_values"] == HALF_CFL
    assert same["source_binding"]["current_bi4"]["sha256"] == half["source_binding"]["current_bi4"]["sha256"]
    assert same["source_binding"]["current_xml"]["sha256"] == half["source_binding"]["current_xml"]["sha256"]
    assert same["comparison_contract"]["common_output_contract"] == half["comparison_contract"]["common_output_contract"]
    assert same["comparison_contract"]["historical_baseline"] == "output_contract_only_.01_full4s; excluded from CFL contrast"
    assert manifest["actual_medium_savedt_same_cfl_baseline"]["status"] == "ABSENT_FROM_BOUND_EVIDENCE"
    assert same["launch_disabled"] and half["launch_disabled"]
    assert same["command"][-1] == half["command"][-1] == "-tout:0.005"
    assert not any(str(token).startswith("-cfl:") for token in same["command"] + half["command"])

    root265 = _load_root265()
    source = root265.SOURCE_XML.read_text(encoding="utf-8")
    good_same = root265.SAME_XML.read_text(encoding="utf-8")
    bad_same = good_same.replace('interval value="0.005"', 'interval value="0.01"', 1)
    try:
        _validate_overlay(source, bad_same, SAME_CFL, root265)
    except ValueError:
        pass
    else:
        raise AssertionError("same-CFL output mutation was accepted")
    bad_half = root265.HALF_XML.read_text(encoding="utf-8").replace('value="0.1"', 'value="0.15"', 1)
    try:
        _validate_overlay(source, bad_half, HALF_CFL, root265)
    except ValueError:
        pass
    else:
        raise AssertionError("half-CFL mutation was accepted")
    print(json.dumps({
        "status": "SELF_TEST_PASS",
        "pair_manifest_schema": manifest["schema"],
        "same_request_sha256": same["request_sha256"],
        "half_request_sha256": half["request_sha256"],
        "same_cfl_savedt_actual_baseline": manifest["actual_medium_savedt_same_cfl_baseline"]["status"],
        "window_s": [0.0, SHORT_WINDOW_S],
    }, indent=2))


def prepare() -> None:
    same, half, manifest = build_pair()
    _atomic_json(SAME_REQUEST_PATH, same)
    _atomic_json(HALF_REQUEST_PATH, half)
    manifest["members"][0]["request_path"] = str(SAME_REQUEST_PATH.resolve())
    manifest["members"][1]["request_path"] = str(HALF_REQUEST_PATH.resolve())
    manifest["request_paths_are_source_only"] = True
    _atomic_json(PAIR_MANIFEST_PATH, manifest)
    print(json.dumps({
        "status": ROOT271_STATUS,
        "same_request": str(SAME_REQUEST_PATH.resolve()),
        "half_request": str(HALF_REQUEST_PATH.resolve()),
        "pair_manifest": str(PAIR_MANIFEST_PATH.resolve()),
        "same_request_sha256": same["request_sha256"],
        "half_request_sha256": half["request_sha256"],
        "manifest_sha256": _sha256_file(PAIR_MANIFEST_PATH),
        "same_cfl_savedt_actual_baseline": manifest["actual_medium_savedt_same_cfl_baseline"]["status"],
        "window_s": [0.0, SHORT_WINDOW_S],
        "solver_started": False,
        "native_payload_read": False,
    }, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if args.self_test == args.prepare:
        parser.error("choose exactly one of --self-test or --prepare")
    if args.self_test:
        self_test()
    else:
        prepare()


if __name__ == "__main__":
    main()
