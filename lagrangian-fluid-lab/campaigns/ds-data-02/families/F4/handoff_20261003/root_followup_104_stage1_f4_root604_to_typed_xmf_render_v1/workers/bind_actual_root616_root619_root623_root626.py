#!/usr/bin/env python3
"""Bind existing F4 Root616/619/623 metadata into fresh104.

This source-only adapter reads JSON receipts/reports and package JSON/XML
metadata.  It never opens or hashes BI4/H5/VTK/CSV/DAT payloads and never
launches a worker.  The resulting package remains disabled; actual native and
frame-0 evidence is recorded as provenance for the next Root-owned stage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


RAW_SUFFIXES = {".bi4", ".h5", ".hdf5", ".vtk", ".vtu", ".vtp", ".csv", ".dat"}
METADATA_SUFFIXES = {".json", ".xml", ".py", ".md", ".txt", ".out"}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    if path.suffix.lower() in RAW_SUFFIXES:
        raise RuntimeError(f"refusing scientific payload hash: {path}")
    if path.suffix.lower() not in METADATA_SUFFIXES:
        raise RuntimeError(f"refusing non-metadata input hash: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ref(path: Path, **extra: Any) -> dict[str, Any]:
    out = {"path": str(path), "sha256": sha(path)}
    out.update(extra)
    return out


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def update_input_closure(request: dict[str, Any], evidence_path: Path) -> None:
    files = list(dict.fromkeys(request.get("input_files", [])))
    if str(evidence_path) not in files:
        files.append(str(evidence_path))
    request["input_files"] = files
    hashes = dict(request.get("input_sha256", {}))
    for raw_path in files:
        path = Path(raw_path)
        if path.suffix.lower() in RAW_SUFFIXES:
            # Source requests must never add raw science payloads.  Preserve a
            # pre-existing value only for compatibility with older disabled
            # requests; this adapter never reads it.
            continue
        if path.suffix.lower() not in METADATA_SUFFIXES:
            # Keep already-published executable/tool digests byte-for-byte;
            # the source adapter does not reopen binaries or suffixless
            # artifact tools.  Root's runtime still validates them when it
            # registers a request.
            continue
        hashes[raw_path] = sha(path)
    request["input_sha256"] = hashes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", required=True, type=Path)
    ap.add_argument("--integration-handoff", required=True, type=Path)
    args = ap.parse_args()
    package = args.package.resolve()
    handoff = args.integration_handoff.resolve()

    root604 = handoff / "root_stage1_f4_distinct_second24_fresh102_genuine_GenCase_604"
    root616 = handoff / "root_stage1_f4_actualGen604_second24_interface_adapter_basic_initial_QA_616"
    root619 = handoff / "root_stage1_f4_actualGen604_basicQA616_full1201_native_second24_619"
    root623 = handoff / "root_stage1_f4_actualnative619_frame0_rawMk_velocity_QA_623"
    root626 = handoff / "root_stage1_f4_new24_native619_frame0QA623_independent_review_626"
    review_path = root626 / "actual-root24-native619-frame0QA623-independent-review.json"
    review = load(review_path)
    review_cases = {row["case_id"]: row for row in review["cases"]}
    if len(review_cases) != 24:
        raise RuntimeError("Root626 review is not a complete 24-case map")

    native_request_files = sorted(root619.glob("*-native-request.json"))
    frame_request_files = sorted(root623.glob("*-initial-qa-request.json"))
    if len(native_request_files) != 24 or len(frame_request_files) != 24:
        raise RuntimeError("Root619/Root623 metadata is not a complete 24-case set")
    native_requests = {load(path)["case_id"]: (path, load(path)) for path in native_request_files}
    frame_requests = {load(path)["case_id"]: (path, load(path)) for path in frame_request_files}
    if set(native_requests) != set(frame_requests) != set(review_cases):
        raise RuntimeError("Root616/619/623/626 case sets differ")

    evidence_cases: list[dict[str, Any]] = []
    for case_id in sorted(native_requests):
        native_request_path, native_request = native_requests[case_id]
        frame_request_path, frame_request = frame_requests[case_id]

        native_attempt_root = Path(native_request["attempt_root"])
        native_receipt_path = native_attempt_root / "execution-receipt.json"
        native_receipt = load(native_receipt_path)
        if native_receipt.get("status") != "completed" or native_receipt.get("returncode") != 0:
            raise RuntimeError(f"Root619 is not completed/0 for {case_id}")

        actual_qa = native_request["actual_initial_qa"]
        basic_report_path = Path(actual_qa["actual_QA_report"])
        basic_receipt_path = Path(actual_qa["actual_QA_receipt"])
        basic_binding_path = Path(actual_qa["actual_QA_binding"])
        basic_request_path = Path(actual_qa["actual_QA_request"])
        basic_request = load(basic_request_path)
        basic_report = load(basic_report_path)
        basic_receipt = load(basic_receipt_path)
        if basic_report.get("status") != "completed" or basic_report.get("returncode") != 0:
            raise RuntimeError(f"Root616 report is not completed/0 for {case_id}")
        if basic_receipt.get("status") != "completed" or basic_receipt.get("returncode") != 0:
            raise RuntimeError(f"Root616 receipt is not completed/0 for {case_id}")

        frame_attempt_root = Path(frame_request["attempt_root"])
        frame_receipt_path = frame_attempt_root / "execution-receipt.json"
        frame_report_path = frame_attempt_root / "audit" / "native-frame0-partvtk-vz-audit.json"
        frame_receipt = load(frame_receipt_path)
        frame_report = load(frame_report_path)
        frame_case = frame_report.get("cases", [{}])[0]
        if frame_receipt.get("status") != "completed" or frame_receipt.get("returncode") != 0:
            raise RuntimeError(f"Root623 receipt is not completed/0 for {case_id}")
        if frame_case.get("status") != "completed_pass" or frame_case.get("pass") is not True:
            raise RuntimeError(f"Root623 frame-0 audit did not pass for {case_id}")

        review_case = review_cases[case_id]
        counts = dict(native_request["actual_initial_qa"]["actual_generated_counts"])
        entry = {
            "case_id": case_id,
            "root604_gencase": {
                "prepared_report": native_request["gencase_receipt"].replace("/execution-receipt.json", "/prepared/prepared-input-report.json"),
                "counts": counts,
                "total": native_request["expected_particles"],
            },
            "root616_basic_qa": {
                "request": ref(basic_request_path, binding=ref(basic_binding_path)),
                "binding": ref(basic_binding_path),
                "attempt_id": basic_request["attempt_id"],
                "receipt": ref(basic_receipt_path, status=basic_receipt["status"], returncode=basic_receipt["returncode"]),
                "report": ref(basic_report_path, status=basic_report["status"], returncode=basic_report["returncode"]),
                "physical_condition_sha256": basic_report.get("physical_condition_sha256"),
                "precision_status": basic_report.get("precision_status"),
                "q_n_status": basic_report.get("q_n_status"),
                "production_approval": basic_report.get("production_approval"),
            },
            "root619_native": {
                "attempt_id": native_request["attempt_id"],
                "request": ref(native_request_path),
                "receipt": ref(native_receipt_path, status=native_receipt["status"], returncode=native_receipt["returncode"]),
                "output_root": native_request["attempt_root"],
                "expected_frames": native_request.get("expected_native_frames"),
                "expected_time_window_s": [1.2, 0.001],
            },
            "root623_frame0": {
                "attempt_id": frame_request["attempt_id"],
                "request": ref(frame_request_path),
                "receipt": ref(frame_receipt_path, status=frame_receipt["status"], returncode=frame_receipt["returncode"]),
                "report": ref(frame_report_path, status=frame_case["status"], pass_result=frame_case["pass"]),
                "raw_mk_type_observed": frame_case.get("native_raw_mk_type_observed"),
                "raw_velocity_observed": frame_case.get("native_raw_velocity_observed"),
                "gencase_declared_velocity_used_as_evidence": frame_case.get("gencase_declared_velocity_used_as_evidence"),
                "actual_total_particles": frame_case.get("actual_total_particles"),
                "native_frame0_particles": frame_case.get("frame0_count_lifecycle", {}).get("native_frame0_particles"),
                "native_frame0_fluid_particles": frame_case.get("frame0_count_lifecycle", {}).get("native_frame0_fluid_particles"),
                "raw_fluid_rows_by_mk": frame_case.get("fluid_rows_by_mk"),
                "max_abs_velocity_error_m_per_s": frame_case.get("max_abs_velocity_error_m_per_s"),
                "native_frame0_bi4_sha256_before_partvtk": frame_case.get("native_frame0_bi4_sha256_before_partvtk"),
                "native_frame0_bi4_sha256_after_partvtk": frame_case.get("native_frame0_bi4_sha256_after_partvtk"),
            },
            "root626_review": {
                "review": ref(review_path, schema=review.get("schema")),
                "native_solver_exclusions_from_actual_log": review_case.get("native_solver_exclusions_from_actual_log"),
                "actual_velocity_error_m_per_s": review_case.get("actual_velocity_error_m_s"),
                "full_typed_lifecycle": review_case.get("full_typed_lifecycle"),
                "full_visual_acceptance": review_case.get("full_visual_acceptance"),
            },
            "future_typed_xmf_render_hashes": {
                "typed_receipt_sha256": None,
                "typed_conversion_report_sha256": None,
                "trajectory_h5_sha256": None,
                "xmf_sha256": None,
                "render_receipt_sha256": None,
            },
        }
        evidence_cases.append(entry)

    evidence = {
        "schema": "ds02.f4.fresh104.actual-root616-root619-root623-root626-evidence.v1",
        "source_only": True,
        "arrays_read_or_hashed_by_source": False,
        "jobs_started_by_source": False,
        "case_count": 24,
        "root604_gencase_completed0": 24,
        "root616_basic_qa_completed0_pass": 24,
        "root619_native_completed0": 24,
        "root623_frame0_completed_pass": 24,
        "root626_independent_review": ref(review_path, schema=review.get("schema")),
        "registered_scientific_digest_source": review.get("registered_scientific_digest_source"),
        "no_initial_missing_or_padding": review.get("no_initial_missing_or_padding"),
        "maximum_observed_velocity_error_m_s": review.get("maximum_observed_velocity_error_m_s"),
        "numerical_precision_status": review.get("numerical_precision_status"),
        "full_typed_render_visual_acceptance": review.get("full_typed_render_visual_acceptance"),
        "mass_semantics": review.get("mass_semantics"),
        "cases": evidence_cases,
        "claim_boundary": "Actual Root616 basic QA, Root619 native completion, and Root623 frame-0 raw Mk/Type/velocity QA are recorded. Typed conversion, XMF, full render, Q-N, precision, visual, and production approval remain pending.",
    }
    evidence_path = package / "evidence" / "actual-root616-root619-root623-root626.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    write(evidence_path, evidence)

    case_by_id = {row["case_id"]: row for row in evidence_cases}
    for case_id, ev in case_by_id.items():
        safe = case_id
        binding_dir = package / "bindings"
        native_binding_path = next(binding_dir.glob(safe + ".native-binding.json"))
        typed_binding_path = next(binding_dir.glob(safe + ".typed-binding.json"))
        xmf_binding_path = next(binding_dir.glob(safe + ".xmf-binding.json"))
        render_binding_path = next(binding_dir.glob(safe + ".render-binding.json"))
        native_request_path = next((package / "requests").glob(safe + ".full1201-native-*.json"))
        typed_request_path = next((package / "requests").glob(safe + ".full1201-typed-nvme-*.json"))
        xmf_request_path = next((package / "requests").glob(safe + ".full1201-xmf-*.json"))
        render_request_path = next((package / "requests").glob(safe + ".full1201-root023-*.json"))

        nb = load(native_binding_path)
        native = ev["root619_native"]
        basic = ev["root616_basic_qa"]
        frame = ev["root623_frame0"]
        evidence_ref = ref(evidence_path)
        nb["actual_upstream_evidence"] = evidence_ref
        nb["native_status"] = "actual_root619_completed0"
        nb["native_receipt"] = dict(native["receipt"], attempt_id=native["attempt_id"])
        nb["native_solver"] = {
            "attempt_id": native["attempt_id"],
            "data_root": native["output_root"] + "/solver_output/data",
            "execution_receipt": native["receipt"]["path"],
            "expected_frames": native["expected_frames"],
            "output_root": native["output_root"],
            "receipt_sha256": native["receipt"]["sha256"],
            "save_interval_s": 0.001,
            "status": "completed/0",
            "time_window_s": 1.2,
        }
        nb["basic_qa_gate"] = {
            **nb.get("basic_qa_gate", {}),
            "actual_attempt_id": ev["root616_basic_qa"]["attempt_id"],
            "actual_binding": basic["request"],
            "actual_binding_sidecar": basic["binding"],
            "actual_report": basic["report"],
            "actual_receipt": basic["receipt"],
            "status": "actual_root616_completed0_pass",
        }
        nb["frame0_gate"] = {
            **nb.get("frame0_gate", {}),
            "actual_attempt_id": frame["attempt_id"],
            "actual_binding": frame["request"],
            "actual_report": frame["report"],
            "actual_receipt": frame["receipt"],
            "raw_mk_type_observed": frame["raw_mk_type_observed"],
            "raw_velocity_observed": frame["raw_velocity_observed"],
            "status": "actual_root623_completed0_pass",
        }
        nb["future_hashes"] = {"solver_output_sha256": None, "typed_receipt_sha256": None, "frame0_report_sha256": None}
        write(native_binding_path, nb)

        nr = load(native_request_path)
        nr["actual_upstream_evidence"] = evidence_ref
        nr["actual_completion"] = {
            "attempt_id": native["attempt_id"],
            "execution_receipt": native["receipt"],
            "status": "completed/0",
            "duplicate_launch_forbidden": True,
        }
        nr["status"] = "actual_root619_completed0_bound_source_only"
        nr["actual_output_root"] = native["output_root"]
        write(native_request_path, nr)

        tb = load(typed_binding_path)
        tb["actual_upstream_evidence"] = evidence_ref
        tb["native_binding"] = {"path": str(native_binding_path), "sha256": None}
        tb["native_solver"] = nb["native_solver"]
        tb["native_frame0_gate"] = nb["frame0_gate"]
        tb["native_completion"] = {"attempt_id": native["attempt_id"], "receipt": native["receipt"], "status": "completed/0"}
        tb["frame0_completion"] = {"attempt_id": frame["attempt_id"], "report": frame["report"], "status": "completed_pass"}
        tb["full_typed_lifecycle"] = ev["root626_review"]["full_typed_lifecycle"]
        write(typed_binding_path, tb)

        tr = load(typed_request_path)
        tr["actual_upstream_evidence"] = evidence_ref
        tr["native_binding"] = {"path": str(native_binding_path), "sha256": None}
        tr["native_receipt"] = native["receipt"]
        tr["native_data_root"] = native["output_root"] + "/solver_output/data"
        tr["native_frame0_gate"] = nb["frame0_gate"]
        tr["depends_on_attempts"] = [native["attempt_id"], frame["attempt_id"]]
        tr["status"] = "WAIT_ROOT_TYPED_CONVERSION_AFTER_ACTUAL_FRAME0_QA"
        update_input_closure(tr, evidence_path)
        write(typed_request_path, tr)

        xb = load(xmf_binding_path)
        xb["actual_upstream_evidence"] = evidence_ref
        xb["typed_binding"] = {"path": str(typed_binding_path), "sha256": None}
        xb["native_completion"] = {"attempt_id": native["attempt_id"], "receipt": native["receipt"], "status": "completed/0"}
        xb["frame0_completion"] = {"attempt_id": frame["attempt_id"], "report": frame["report"], "status": "completed_pass"}
        write(xmf_binding_path, xb)

        xr = load(xmf_request_path)
        xr["actual_upstream_evidence"] = evidence_ref
        xr["typed_binding"] = {"path": str(typed_binding_path), "sha256": None}
        xr["depends_on_attempts"] = [tr["attempt_id"]]
        update_input_closure(xr, evidence_path)
        write(xmf_request_path, xr)

        rb = load(render_binding_path)
        rb["actual_upstream_evidence"] = evidence_ref
        rb["typed_binding"] = {"path": str(typed_binding_path), "sha256": None}
        rb["xmf_binding"] = {"path": str(xmf_binding_path), "sha256": None}
        write(render_binding_path, rb)

        rr = load(render_request_path)
        rr["actual_upstream_evidence"] = evidence_ref
        rr["typed_binding"] = {"path": str(typed_binding_path), "sha256": None}
        rr["xmf_binding"] = {"path": str(xmf_binding_path), "sha256": None}
        update_input_closure(rr, evidence_path)
        write(render_request_path, rr)

    # Resolve binding/request references and input hashes after every file has
    # reached its final shape.  This avoids stale closure digests without
    # touching any external scientific payload.
    for path in sorted((package / "bindings").glob("*.native-binding.json")):
        pass
    for case_id in sorted(case_by_id):
        safe = case_id
        native_binding_path = next((package / "bindings").glob(safe + ".native-binding.json"))
        typed_binding_path = next((package / "bindings").glob(safe + ".typed-binding.json"))
        xmf_binding_path = next((package / "bindings").glob(safe + ".xmf-binding.json"))
        render_binding_path = next((package / "bindings").glob(safe + ".render-binding.json"))
        native_request_path = next((package / "requests").glob(safe + ".full1201-native-*.json"))
        typed_request_path = next((package / "requests").glob(safe + ".full1201-typed-nvme-*.json"))
        xmf_request_path = next((package / "requests").glob(safe + ".full1201-xmf-*.json"))
        render_request_path = next((package / "requests").glob(safe + ".full1201-root023-*.json"))
        # Resolve the one-way binding chain to a fixed point.  The native
        # binding has no child reference; typed references native; XMF and
        # render reference the resulting typed/XMF bytes.  Re-serializing in
        # this order is deterministic and avoids stale child digests.
        for _ in range(4):
            tb = load(typed_binding_path)
            tb["native_binding"]["sha256"] = sha(native_binding_path)
            write(typed_binding_path, tb)

            xb = load(xmf_binding_path)
            xb["typed_binding"]["sha256"] = sha(typed_binding_path)
            write(xmf_binding_path, xb)

            rb = load(render_binding_path)
            rb["typed_binding"]["sha256"] = sha(typed_binding_path)
            rb["xmf_binding"]["sha256"] = sha(xmf_binding_path)
            write(render_binding_path, rb)

        tb = load(typed_binding_path)
        xb = load(xmf_binding_path)
        rb = load(render_binding_path)
        if tb["native_binding"]["sha256"] != sha(native_binding_path):
            raise RuntimeError(f"stale native binding digest: {typed_binding_path}")
        if xb["typed_binding"]["sha256"] != sha(typed_binding_path):
            raise RuntimeError(f"stale typed binding digest: {xmf_binding_path}")
        if rb["typed_binding"]["sha256"] != sha(typed_binding_path) or rb["xmf_binding"]["sha256"] != sha(xmf_binding_path):
            raise RuntimeError(f"stale render binding digest: {render_binding_path}")

        tr = load(typed_request_path); xr = load(xmf_request_path); rr = load(render_request_path)
        tr["native_binding"]["sha256"] = sha(native_binding_path)
        xr["typed_binding"]["sha256"] = sha(typed_binding_path)
        xr["xmf_binding"] = {"path": str(xmf_binding_path), "sha256": sha(xmf_binding_path)}
        rr["typed_binding"]["sha256"] = sha(typed_binding_path)
        rr["xmf_binding"]["sha256"] = sha(xmf_binding_path)
        for req in [tr, xr, rr]:
            update_input_closure(req, evidence_path)
        write(typed_request_path, tr); write(xmf_request_path, xr); write(render_request_path, rr)

    # A final metadata-only pass closes every request against the now-final
    # binding bytes.  This deliberately skips raw/science and suffixless tool
    # inputs; their already-published digests stay immutable for Root's
    # runtime validation.
    for _ in range(6):
        for request_path in sorted((package / "requests").glob("*.request.json")):
            req = load(request_path)
            for raw_path in req.get("input_files", []):
                path = Path(raw_path)
                if path.suffix.lower() in METADATA_SUFFIXES:
                    req.setdefault("input_sha256", {})[raw_path] = sha(path)
            for key in ("native_binding", "typed_binding", "xmf_binding", "render_binding"):
                value = req.get(key)
                if isinstance(value, dict) and value.get("path"):
                    child = Path(value["path"])
                    if child.suffix.lower() in METADATA_SUFFIXES:
                        value["sha256"] = sha(child)
            write(request_path, req)

    # Recompute the request index, source binding, and manifest only after all
    # per-case request/binding bytes are final.
    index_path = package / "requests" / "index.json"
    index = load(index_path)
    for row in index["requests"]:
        row["sha256"] = sha(Path(row["path"]))
    write(index_path, index)

    source_binding_path = package / "source-binding.json"
    source_binding = load(source_binding_path)
    for row in source_binding["cases"]:
        case_id = row["case_id"]
        ev = case_by_id[case_id]
        row["actual_root616_root619_root623_root626_evidence"] = ref(evidence_path)
        row["actual_native619_receipt"] = ev["root619_native"]["receipt"]
        row["actual_frame0_root623_report"] = ev["root623_frame0"]["report"]
        for key in ["native_request", "typed_request", "xmf_request", "render_request"]:
            path = Path(row[key]["path"])
            row[key]["sha256"] = sha(path)
    write(source_binding_path, source_binding)

    manifest_path = package / "manifest.json"
    manifest = load(manifest_path)
    manifest["claim_boundary"] = "Root604 GenCase, Root616 basic QA, Root619 native completion, and Root623 frame-0 raw Mk/Type/velocity QA are actual metadata evidence. Typed conversion, XMF, full render, precision, Q-N, visual, and production approval remain pending."
    manifest["actual_root616_basicQA_completed0_pass"] = 24
    manifest["actual_root619_native_completed0"] = 24
    manifest["actual_root623_frame0_completed_pass"] = 24
    manifest["actual_independent_review626"] = ref(review_path, schema=review.get("schema"))
    manifest["actual_evidence"] = ref(evidence_path)
    manifest["source_binding"] = {"path": str(source_binding_path), "sha256": sha(source_binding_path)}
    manifest["request_index"] = {"path": str(index_path), "sha256": sha(index_path)}
    manifest["future_hashes_null"] = True
    write(manifest_path, manifest)

    # Final source closure: every non-science input hash must be exact.  The
    # validator performs the same check; this pass makes the adapter itself
    # fail before it can publish an incomplete package.
    for request_path in sorted((package / "requests").glob("*.request.json")):
        req = load(request_path)
        for raw_path in req.get("input_files", []):
            path = Path(raw_path)
            if path.suffix.lower() in RAW_SUFFIXES:
                raise RuntimeError(f"raw science input in source request: {path}")
            if path.suffix.lower() not in METADATA_SUFFIXES:
                continue
            if req["input_sha256"].get(raw_path) != sha(path):
                raise RuntimeError(f"stale source input hash: {request_path} -> {path}")
    print(json.dumps({"package": str(package), "cases": 24, "root619_native": 24, "root623_frame0_pass": 24, "future_typed_xmf_render_hashes_null": True}, indent=2))


if __name__ == "__main__":
    main()
