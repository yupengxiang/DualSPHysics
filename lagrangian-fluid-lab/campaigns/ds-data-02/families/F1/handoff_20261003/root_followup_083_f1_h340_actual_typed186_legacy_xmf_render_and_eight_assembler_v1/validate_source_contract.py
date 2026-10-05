from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

PKG = Path(__file__).resolve().parent
CASES = [
    "F1_STAGE1_DUAL_H340_DP020_VX010",
    "F1_STAGE1_DUAL_H340_DP020_VX020",
]
RAW_SUFFIXES = {".h5", ".bi4", ".ibi4", ".csv", ".vtk", ".vtu"}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def fail(message: str) -> None:
    raise SystemExit(message)


def check_hash(path_text: str, expected: str) -> None:
    path = Path(path_text)
    if path.suffix.lower() in RAW_SUFFIXES:
        # A source validator may register a completed converter's producer
        # hash, but it never opens, reads, or rehashes a scientific array.
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


def check_actual_chain(binding: dict) -> tuple[dict, dict]:
    owner_path = Path(binding["canonical_owner"])
    typed_owner_path = Path(binding["typed_owner"])
    owner = load(owner_path)
    typed_owner = load(typed_owner_path)
    if sha(owner_path) != binding["canonical_owner_sha256"]:
        fail(f"canonical owner SHA differs: {binding['case_id']}")
    if sha(typed_owner_path) != binding["typed_owner_sha256"]:
        fail(f"typed owner SHA differs: {binding['case_id']}")
    if owner.get("physical_condition_sha256") != binding["canonical_physical_condition_sha256"]:
        fail(f"canonical condition differs: {binding['case_id']}")
    if canonical_binding_hash(owner["physical_binding"]) != binding["canonical_physical_binding_sha256"]:
        fail(f"canonical physical_binding differs: {binding['case_id']}")
    if typed_owner.get("source_owner") != binding["canonical_owner"]:
        fail(f"typed owner source owner differs: {binding['case_id']}")
    if typed_owner.get("source_owner_sha256") != binding["canonical_owner_sha256"]:
        fail(f"typed owner source owner SHA differs: {binding['case_id']}")

    report_path = Path(binding["typed_conversion_report"])
    receipt_path = Path(binding["typed_execution_receipt"])
    report = load(report_path)
    receipt = load(receipt_path)
    if sha(report_path) != binding["typed_conversion_report_sha256"] or sha(receipt_path) != binding["typed_execution_receipt_sha256"]:
        fail(f"typed report/receipt SHA differs: {binding['case_id']}")
    if report.get("conversion_status") != "completed" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        fail(f"typed receipt is not completed/0: {binding['case_id']}")
    if report.get("output_sha256") != binding["typed_output_sha256"]:
        fail(f"typed producer hash differs from report: {binding['case_id']}")
    if int(report.get("frames", -1)) != int(binding["expected_frames"]):
        fail(f"typed frame count differs: {binding['case_id']}")
    if int(report.get("particles", -1)) != int(binding["expected_particles"]):
        fail(f"typed particle count differs: {binding['case_id']}")
    if int(report.get("solver_dimension", {}).get("solver_dimension", -1)) != 3:
        fail(f"typed product is not 3-D: {binding['case_id']}")
    scope = report.get("hash_scopes", {})
    legacy = scope.get("physical_condition_sha256")
    if legacy != binding["legacy_h5_physical_condition_sha256"]:
        fail(f"legacy report hash differs: {binding['case_id']}")
    if legacy == binding["canonical_physical_condition_sha256"]:
        fail(f"legacy/canonical hash collapse: {binding['case_id']}")
    if scope.get("physical_condition", {}).get("schema") != "legacy-owner-scope.v0":
        fail(f"legacy scope schema differs: {binding['case_id']}")
    provenance = report.get("source_provenance", {})
    for key, path_key, hash_key in (
        ("generated_xml", "generated_xml", "generated_xml_sha256"),
        ("gencase_receipt", "actual_gencase_receipt", "actual_gencase_receipt_sha256"),
    ):
        entry = provenance.get(key, {})
        if entry.get("path") != binding[path_key] or entry.get("sha256") != binding[hash_key]:
            fail(f"source provenance mismatch {key}: {binding['case_id']}")
    for key in (
        "canonical_card", "source_definition", "generated_xml", "generated_def",
        "actual_gencase_receipt", "actual_gencase_report", "actual_native_receipt",
        "actual_root181_frame0_vx_closure", "actual_root181_frame0_vx_receipt",
        "actual_root181_frame0_vx_report",
    ):
        if not Path(binding[key]).is_file():
            fail(f"missing metadata input {key}: {binding['case_id']}")
    gencase_receipt = load(Path(binding["actual_gencase_receipt"]))
    if gencase_receipt.get("status") != "completed" or gencase_receipt.get("returncode") != 0:
        fail(f"GenCase receipt is not completed/0: {binding['case_id']}")
    gencase_report = load(Path(binding["actual_gencase_report"]))
    if int(gencase_report.get("actual_total_particles", -1)) != int(binding["expected_particles"]):
        fail(f"GenCase total metadata differs: {binding['case_id']}")
    fluid_count = int(gencase_report.get("generated_xml_particle_counts", {}).get("fluid", -1))
    if fluid_count <= 0:
        fail(f"GenCase fluid metadata is missing: {binding['case_id']}")
    typed_fluid_count = sum(
        int(block.get("count", 0)) for block in report.get("typed_identity", {}).get("blocks", [])
        if block.get("tag") == "fluid" and int(block.get("type", -1)) == 3
    )
    if typed_fluid_count != fluid_count:
        fail(f"GenCase/typed fluid metadata differs: {binding['case_id']}")
    native_receipt = load(Path(binding["actual_native_receipt"]))
    if native_receipt.get("status") != "completed" or native_receipt.get("returncode") != 0:
        fail(f"native receipt is not completed/0: {binding['case_id']}")
    frame0 = load(Path(binding["actual_root181_frame0_vx_report"]))
    if not frame0.get("cases") or not all(bool(row.get("passed")) for row in frame0["cases"]):
        fail(f"Root181 frame0 audit not passed: {binding['case_id']}")
    return owner, report


def check_request(path: Path, binding: dict, require_audit: bool = True) -> None:
    request = load(path)
    if request.get("case_id") != binding["case_id"]:
        fail(f"request case mismatch: {path}")
    if request.get("launch") or request.get("launch_allowed") or request.get("execution_allowed"):
        fail(f"request enabled: {path}")
    files = set(request.get("input_files", []))
    hashes = set(request.get("input_sha256", {}))
    if files != hashes:
        fail(f"input file/hash closure differs: {path}")
    for path_text, digest in request.get("input_sha256", {}).items():
        check_hash(path_text, digest)
        if Path(path_text).suffix.lower() == ".h5" and digest != binding["typed_output_sha256"]:
            fail(f"H5 producer hash is not report output SHA: {path_text}")
    command = request.get("command", [])
    if require_audit:
        if request.get("cpu_task_kind") != "audit":
            fail(f"read-only request is not classified as audit: {path}")
        if ".root193-" in path.name:
            if "{attempt_root}/xdmf" not in command:
                fail(f"Root193 output is not isolated below attempt_root/xdmf: {path}")
        elif ".root194-" in path.name:
            if "{attempt_root}/render" not in command:
                fail(f"Root194 output is not isolated below attempt_root/render: {path}")
    if any(value is not None for value in request.get("future_outputs", {}).values()):
        fail(f"future output hash fabricated: {path}")
    for future_path, future_hash in request.get("future_input_sha256", {}).items():
        if future_hash is not None:
            fail(f"future XMF input hash fabricated: {future_path}")


def main() -> int:
    top = load(PKG / "manifest.json")
    if top.get("fresh_id") != "fresh083" or top.get("family_id") != "F1":
        fail("wrong fresh083 manifest scope")
    if top.get("cases") != CASES or top.get("case_count") != 2:
        fail("fresh083 case set is not the two H340 typed186 cases")
    if not top.get("source_only") or top.get("raw_arrays_read") or top.get("jobs_started"):
        fail("source-only guard is false")
    if top.get("launch_allowed") or top.get("execution_allowed"):
        fail("fresh083 package is enabled")
    for source in (
        PKG / "workers/export_xmf_legacy_aware.py",
        PKG / "workers/render_native023.py",
        PKG / "workers/assemble_eight_root193_root194.py",
    ):
        try:
            ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        except SyntaxError as exc:
            fail(f"syntax error: {source}: {exc}")
    for path in PKG.rglob("*"):
        if path.is_file() and path.suffix.lower() in RAW_SUFFIXES:
            fail(f"raw scientific output copied into source package: {path}")
    request_count = 0
    for case in CASES:
        binding = load(PKG / f"bindings/{case}.legacy-aware-binding.json")
        render_binding = load(PKG / f"bindings/{case}.render-binding.json")
        owner, report = check_actual_chain(binding)
        sidecar_path = Path(binding["legacy_canonical_semantic_sidecar"])
        sidecar = load(sidecar_path)
        if sha(sidecar_path) != binding["legacy_canonical_semantic_sidecar_sha256"]:
            fail(f"legacy/canonical sidecar SHA differs: {case}")
        if sidecar.get("canonical", {}).get("physical_condition_sha256") != binding["canonical_physical_condition_sha256"]:
            fail(f"sidecar canonical scope differs: {case}")
        if sidecar.get("legacy_converter", {}).get("physical_condition_sha256") != binding["legacy_h5_physical_condition_sha256"]:
            fail(f"sidecar legacy scope differs: {case}")
        if sidecar.get("separation", {}).get("legacy_and_canonical_equal") is not False:
            fail(f"sidecar collapses legacy/canonical scopes: {case}")
        card_path = Path(binding["canonical_card"])
        card = load(card_path)
        if sha(card_path) != binding["canonical_card_sha256"]:
            fail(f"canonical card SHA differs: {case}")
        if card.get("physical_condition_sha256") != binding["canonical_physical_condition_sha256"]:
            fail(f"canonical card condition differs: {case}")
        if render_binding.get("legacy_h5_physical_condition_sha256") != binding["legacy_h5_physical_condition_sha256"]:
            fail(f"render legacy scope differs: {case}")
        if render_binding.get("canonical_physical_condition_sha256") != binding["canonical_physical_condition_sha256"]:
            fail(f"render canonical scope differs: {case}")
        xmf = PKG / f"requests/{case}.root193-xmf.request.json"
        render = PKG / f"requests/{case}.root194-render.request.json"
        check_request(xmf, binding)
        check_request(render, binding)
        request_count += 2
    if request_count != 4:
        fail("fresh083 request count differs")

    index = load(PKG / "metadata/eight-case-inputs.json")
    if index.get("schema") != "ds02.f1.fresh083.eight-case-inputs.v1" or len(index.get("cases", [])) != 8:
        fail("eight-case assembler input index is not closed")
    index_cases = {record.get("case_id") for record in index["cases"]}
    expected = {
        "F1_STAGE1_ECC_H110_DP010_VX010", "F1_STAGE1_ECC_H110_DP010_VX020",
        "F1_STAGE1_ECC_H190_DP010_VX010", "F1_STAGE1_ECC_H190_DP010_VX020",
        "F1_STAGE1_DUAL_H220_DP020_VX010", "F1_STAGE1_DUAL_H220_DP020_VX020",
        *CASES,
    }
    if index_cases != expected:
        fail(f"eight-case input index case set differs: {sorted(index_cases)}")
    for record in index["cases"]:
        for key in ("legacy_aware_binding", "root193_request", "root194_request"):
            path = Path(record[key])
            if not path.is_file():
                fail(f"assembler input missing: {path}")
        binding_path = Path(record["legacy_aware_binding"])
        if sha(binding_path) != record["legacy_aware_binding_sha256"]:
            fail(f"assembler binding SHA differs: {binding_path}")
        binding = load(binding_path)
        if binding.get("typed_output_sha256") != record["typed_h5_producer_sha256"]:
            fail(f"assembler H5 producer SHA differs from binding: {binding_path}")
        report_path = Path(binding["typed_conversion_report"])
        report = load(report_path)
        if report.get("output_sha256") != record["typed_h5_producer_sha256"]:
            fail(f"assembler H5 producer SHA differs from report: {binding_path}")
        # Existing fresh082 source requests remain immutable historical inputs;
        # the assembler normalizes their output subdirectories and audit kind
        # in its derived copies.
        check_request(Path(record["root193_request"]), binding, require_audit=False)
        check_request(Path(record["root194_request"]), binding, require_audit=False)

    result = {
        "status": "pass",
        "fresh_id": "fresh083",
        "case_count": 2,
        "request_count": 4,
        "assembler_case_count": 8,
        "arrays_read": False,
        "jobs_started": False,
        "legacy_canonical_layers_separate": True,
        "h5_producer_hash_source": "actual conversion-report output_sha256; no H5 read or rehash",
    }
    (PKG / "source-validation-report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
