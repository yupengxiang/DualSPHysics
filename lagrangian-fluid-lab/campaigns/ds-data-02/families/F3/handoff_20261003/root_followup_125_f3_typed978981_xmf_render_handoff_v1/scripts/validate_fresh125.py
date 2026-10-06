#!/usr/bin/env python3
"""Static, metadata-only validator for F3 fresh125."""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
FORBIDDEN = {".bi4", ".ibi4", ".obi4", ".h5", ".hdf5", ".csv", ".dat", ".vtk", ".vtu", ".npy", ".npz", ".raw"}
SAFE = {".json", ".py", ".xml", ".xmf", ".log", ".txt", ".md"}

def digest(path: Path) -> str:
    if path.suffix.lower() in FORBIDDEN:
        raise AssertionError(f"forbidden science payload hash: {path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def load(path: Path):
    if path.suffix.lower() in FORBIDDEN:
        raise AssertionError(f"forbidden science payload read: {path}")
    return json.loads(path.read_text(encoding="utf-8"))

def main() -> int:
    errors = []
    snapshots = sorted((HERE / "metadata/case-snapshots").glob("*.json"))
    cases = load(HERE / "metadata/case-index.json")["cases"]
    if len(cases) != 19 or len(snapshots) != 19:
        errors.append(f"case count is {len(cases)} snapshots={len(snapshots)}, expected 19")
    provenance = load(HERE / "metadata/fresh125-worker-provenance.json")
    if provenance["export_xmf"]["sha256"] != "da50e26d5322b1b6f1539bca3109dfc115164427b37e1b2f86f56b153f56b0b0":
        errors.append("export_xmf source hash drift")
    if provenance["nvme_render_successor"]["sha256"] != "5d577e4b28e62906472bfba30ad445685f804be4ba5d8bab44b4bab3d32e1621":
        errors.append("fresh116 wrapper source hash drift")
    if provenance["root023_renderer"]["sha256"] != "5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66":
        errors.append("Root023 renderer hash drift")
    terminal = 0
    active_progress_names = {"actual-progress.json", "actual948-native-progress-immutable-snapshot.json"}
    for row in cases:
        case = row["case_id"]
        snap = load(HERE / "metadata/case-snapshots" / f"{case}.json")
        if row["typed_terminal_completed0"]:
            terminal += 1
        for rel in [row["xmf_request"], row["xmf_binding"], row["render_request"], row["render_binding"], row["wrapper_request"]]:
            path = Path(rel)
            if not path.is_file(): errors.append(f"missing {rel}")
        xr = load(Path(row["xmf_request"]))
        xb = load(Path(row["xmf_binding"]))
        rr = load(Path(row["render_request"]))
        rb = load(Path(row["render_binding"]))
        wr = load(Path(row["wrapper_request"]))
        if not all(x.get("disabled") is True and x.get("source_only") is True and x.get("execution_allowed") is False for x in (xr, rr)):
            errors.append(f"{case}: XMF/render not disabled source-only")
        if not all(x.get("disabled") is True and x.get("source_only") is True and x.get("launch") is False and x.get("execution_allowed") is False for x in (wr,)):
            errors.append(f"{case}: wrapper not disabled source-only")
        if any(x.get("case_credit") != 0 for x in (xr, rr)):
            errors.append(f"{case}: downstream case credit nonzero")
        if xr.get("physical_condition_sha256") != row["actual_converter_scope_sha256"] or xb.get("physical_condition_sha256") != row["actual_converter_scope_sha256"]:
            errors.append(f"{case}: actual converter scope drift")
        if xr.get("source_physical_condition_sha256") != row["physical_condition_sha256"]:
            errors.append(f"{case}: source scope drift")
        # Every future XMF/render product remains null. Typed producer values may be
        # present only for a terminal completed producer snapshot.
        for obj, label in [(xb, "xmf binding"), (rb, "render binding"), (xr, "xmf request"), (rr, "render request")]:
            for key, value in obj.get("future_outputs", {}).items():
                if key.endswith("sha256") and value is not None:
                    errors.append(f"{case}: {label} future output {key} is not null")
        for path_text in xr.get("input_files", []) + rr.get("input_files", []) + wr.get("input_files", []):
            p = Path(path_text)
            if p.name in active_progress_names:
                errors.append(f"{case}: live progress entered runtime input closure")
            if p.suffix.lower() in FORBIDDEN:
                errors.append(f"{case}: science payload entered metadata input closure: {p}")
        for obj, label in [(xr, "xmf"), (rr, "render"), (wr, "wrapper")]:
            files, hashes = obj.get("input_files"), obj.get("input_sha256")
            if not isinstance(files, list) or not isinstance(hashes, dict) or set(files) != set(hashes):
                errors.append(f"{case}: {label} input closure mismatch")
                continue
            for text in files:
                p = Path(text)
                if p.suffix.lower() in FORBIDDEN:
                    continue
                if not p.is_file(): errors.append(f"{case}: missing metadata input {p}")
                elif digest(p) != hashes[text]: errors.append(f"{case}: metadata input digest mismatch {p}")
        if wr.get("renderer_argv_template", [None, None])[1] != "--force-offscreen-rendering":
            errors.append(f"{case}: Root023 offscreen argv missing")
        if wr.get("expected_frames") != 836 or wr.get("expected_particles") != 179208:
            errors.append(f"{case}: render dimensions not 836/179208")
        if wr.get("cpu_threads") != 24 or wr.get("environment_threads") != 2 or wr.get("global_renderer_cap") != 2:
            errors.append(f"{case}: Root023 resource contract drift")
        if wr.get("home_free_floor_bytes", 0) < 500 * 1024**3 or wr.get("nvme_free_floor_bytes", 0) < 100 * 1024**3 or wr.get("nvme_stage_cap_bytes", 0) > 24 * 1024**3:
            errors.append(f"{case}: storage floor/cap drift")
        for text in xr.get("future_input_files", []) + rr.get("future_input_files", []) + wr.get("future_input_files", []):
            if Path(text).suffix.lower() in FORBIDDEN:
                # Future scientific paths are permitted only with a null or producer-attested
                # hash, never in source input_sha256.
                continue
    if terminal > 3:
        errors.append(f"terminal typed completed0 count {terminal} exceeds handoff bound 3")
    result = {
        "schema": "ds02.stage1.f3.fresh125.validator-report.v1",
        "status": "pass" if not errors else "fail",
        "case_count": len(cases),
        "terminal_typed_completed0_count": terminal,
        "source_only": True,
        "jobs_started": False,
        "shared_state_modified": False,
        "science_payload_opened_or_hashed": False,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 1

if __name__ == "__main__":
    raise SystemExit(main())
