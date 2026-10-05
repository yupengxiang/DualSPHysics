#!/usr/bin/env python3
import json
from pathlib import Path
P = Path(__file__).resolve().parents[1]
RAW = {".bi4",".h5",".hdf5",".vtk",".vtu",".vtp",".csv",".dat"}
METADATA = {".json", ".xml", ".py", ".md", ".txt", ".out"}
def load(p): return json.loads(Path(p).read_text())
def main():
    idx = load(P/"requests/index.json")
    assert idx["case_count"] == 24 and idx["request_count"] == 96 and idx["all_disabled"]
    assert all(len(set(row) - {"case_id","kind","path","sha256","disabled"}) == 0 for row in idx["requests"])
    for row in idx["requests"]:
        req = load(row["path"])
        assert req["disabled"] and not req["launch"] and not req["execution_allowed"]
        assert req["family_id"] == "F4" and req["cpu_threads"] == 2
        assert req["input_files"] and set(req["input_sha256"]) == set(req["input_files"])
        for path in req["input_files"]:
            suffix = Path(path).suffix.lower()
            assert suffix not in RAW
            # Source validation never opens suffixless executables/tools;
            # their published 64-hex digests remain for Root's runtime.
            if suffix in METADATA:
                assert req["input_sha256"][path] == __import__("hashlib").sha256(Path(path).read_bytes()).hexdigest()
            else:
                assert isinstance(req["input_sha256"][path], str) and len(req["input_sha256"][path]) == 64
        # Output paths are deterministic deferred destinations; only output
        # digests are required to remain unknown until Root runs the request.
        for key, value in req["expected_outputs"].items():
            if key.endswith("sha256") or key in {"output_sha256", "all_sha256"}:
                assert value is None
        assert all(value is None for value in req["future_hashes"].values())
    manifest = load(P/"manifest.json")
    assert manifest["actual_root604_gencase_completed0"] == 24 and manifest["future_hashes_null"]
    assert manifest["actual_root616_basicQA_completed0_pass"] == 24
    assert manifest["actual_root619_native_completed0"] == 24
    assert manifest["actual_root623_frame0_completed_pass"] == 24
    evidence = load(P / "evidence/actual-root616-root619-root623-root626.json")
    assert evidence["case_count"] == 24
    assert evidence["root616_basic_qa_completed0_pass"] == 24
    assert evidence["root619_native_completed0"] == 24
    assert evidence["root623_frame0_completed_pass"] == 24
    assert evidence["full_typed_render_visual_acceptance"] == "pending"
    assert all(row["root623_frame0"]["report"]["status"] == "completed_pass" for row in evidence["cases"])
    assert all(row["future_typed_xmf_render_hashes"]["typed_receipt_sha256"] is None for row in evidence["cases"])
    pre = load(P/"evidence/converter-physical-scope-preflight.json")
    assert pre["all_pass"] and len(pre["cases"]) == 24
    assert all(row["source_owner_hash_reused"] is False for row in pre["cases"])
    print("fresh104 source contract: PASS (24 cases, 96 disabled singleton requests, Root616/619/623/626 evidence, converter scope preflight)")
if __name__ == "__main__": main()
