from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

PKG = Path(__file__).resolve().parent
CASES = [
    "F1_STAGE1_ECC_H110_DP010_VX010",
    "F1_STAGE1_ECC_H110_DP010_VX020",
    "F1_STAGE1_ECC_H190_DP010_VX010",
    "F1_STAGE1_ECC_H190_DP010_VX020",
    "F1_STAGE1_DUAL_H220_DP020_VX010",
    "F1_STAGE1_DUAL_H220_DP020_VX020",
]
RAW_SUFFIXES = {".h5", ".bi4", ".ibi4", ".csv", ".vtk", ".vtu"}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def fail(message: str) -> None:
    raise SystemExit(message)


def check_path_hash(path_text: str, expected: str) -> None:
    path = Path(path_text)
    if path.suffix.lower() in RAW_SUFFIXES:
        # The typed H5 hash is the converter's verified output_sha256.  The
        # source validator never opens or rehashes a scientific array file.
        if len(expected) != 64:
            fail(f"raw source hash is not SHA-256: {path}")
        return
    if not path.is_file():
        fail(f"missing input: {path}")
    actual = sha(path)
    if actual != expected:
        fail(f"input SHA differs for {path}: {actual} != {expected}")


def canonical_binding_hash(value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    top = load(PKG / "manifest.json")
    if top.get("fresh_id") != "fresh082" or top.get("family_id") != "F1":
        fail("wrong top manifest scope")
    if top.get("case_count") != 6 or top.get("cases") != CASES:
        fail("case set is not the six actual typed186 cases")
    if not top.get("source_only") or top.get("raw_arrays_read") or top.get("jobs_started"):
        fail("source-only guard is false")
    if top.get("launch_allowed") or top.get("execution_allowed"):
        fail("source package is enabled")
    worker = PKG / "workers/export_xmf_legacy_aware.py"
    renderer = PKG / "workers/render_native023.py"
    for source in (worker, renderer):
        try:
            ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        except SyntaxError as exc:
            fail(f"syntax error: {source}: {exc}")
    for path in PKG.rglob("*"):
        if path.is_file() and path.suffix.lower() in RAW_SUFFIXES:
            fail(f"raw scientific output copied into source package: {path}")

    request_paths = []
    for case in CASES:
        b = load(PKG / f"bindings/{case}.legacy-aware-binding.json")
        rb = load(PKG / f"bindings/{case}.render-binding.json")
        canonical_path = Path(b["canonical_owner"])
        typed_owner_path = Path(b["typed_owner"])
        canonical = load(canonical_path)
        typed_owner = load(typed_owner_path)
        if sha(canonical_path) != b["canonical_owner_sha256"]:
            fail(f"canonical owner SHA differs: {case}")
        if sha(typed_owner_path) != b["typed_owner_sha256"]:
            fail(f"typed owner SHA differs: {case}")
        if canonical.get("physical_condition_sha256") != b["canonical_physical_condition_sha256"]:
            fail(f"canonical condition differs: {case}")
        if canonical_binding_hash(canonical["physical_binding"]) != b["canonical_physical_binding_sha256"]:
            fail(f"canonical physical_binding hash differs: {case}")
        if typed_owner.get("source_owner") != b["canonical_owner"] or typed_owner.get("source_owner_sha256") != b["canonical_owner_sha256"]:
            fail(f"typed owner canonical mapping differs: {case}")
        report_path = Path(b["typed_conversion_report"])
        receipt_path = Path(b["typed_execution_receipt"])
        report = load(report_path)
        receipt = load(receipt_path)
        if sha(report_path) != b["typed_conversion_report_sha256"] or sha(receipt_path) != b["typed_execution_receipt_sha256"]:
            fail(f"typed report/receipt SHA differs: {case}")
        if report.get("conversion_status") != "completed" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            fail(f"typed receipt is not completed/0: {case}")
        legacy = report.get("hash_scopes", {}).get("physical_condition_sha256")
        if legacy != b["legacy_h5_physical_condition_sha256"]:
            fail(f"legacy hash differs from converter report: {case}")
        if report.get("hash_scopes", {}).get("physical_condition", {}).get("schema") != "legacy-owner-scope.v0":
            fail(f"legacy scope schema differs: {case}")
        if legacy == b["canonical_physical_condition_sha256"]:
            fail(f"legacy/canonical hash collapse: {case}")
        if report.get("frames") != b["expected_frames"] or report.get("solver_dimension", {}).get("solver_dimension") != 3:
            fail(f"typed frame/dimension metadata differs: {case}")
        provenance = report.get("source_provenance", {})
        for key, path_key, sha_key in (("generated_xml", "generated_xml", "generated_xml_sha256"), ("gencase_receipt", "actual_gencase_receipt", "actual_gencase_receipt_sha256")):
            entry = provenance.get(key, {})
            if entry.get("path") != b[path_key] or entry.get("sha256") != b[sha_key]:
                fail(f"source provenance mismatch {key}: {case}")
        for key in ("canonical_card", "source_definition", "generated_xml", "generated_def", "actual_gencase_receipt", "actual_gencase_report", "actual_native_receipt", "actual_root181_frame0_vx_closure", "actual_root181_frame0_vx_receipt", "actual_root181_frame0_vx_report"):
            if not Path(b[key]).is_file():
                fail(f"missing actual metadata input {key}: {case}")
        xreq = load(PKG / f"requests/{case}.root193-xmf.request.json")
        rreq = load(PKG / f"requests/{case}.root194-render.request.json")
        for req in (xreq, rreq):
            if req.get("launch") or req.get("launch_allowed") or req.get("execution_allowed"):
                fail(f"request enabled: {case}")
            files = set(req.get("input_files", []))
            hashes = set(req.get("input_sha256", {}))
            if files != hashes:
                fail(f"input file/hash key closure differs: {case}")
            for path, digest in req.get("input_sha256", {}).items():
                check_path_hash(path, digest)
            if req.get("future_outputs", {}).get("execution_receipt_sha256") is not None:
                fail(f"future receipt hash is fabricated: {case}")
        for path, digest in rreq.get("future_input_sha256", {}).items():
            if digest is not None:
                fail(f"future XMF hash is fabricated: {case}")
        request_paths.extend([str(PKG / f"requests/{case}.root193-xmf.request.json"), str(PKG / f"requests/{case}.root194-render.request.json")])
        if rb.get("legacy_h5_physical_condition_sha256") != legacy or rb.get("canonical_physical_condition_sha256") != b["canonical_physical_condition_sha256"]:
            fail(f"render binding semantic layers differ: {case}")
    if len(request_paths) != 12:
        fail("request count differs")
    result = {"status": "pass", "case_count": 6, "request_count": 12, "arrays_read": False, "jobs_started": False, "legacy_canonical_layers_separate": True}
    (PKG / "source-validation-report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
