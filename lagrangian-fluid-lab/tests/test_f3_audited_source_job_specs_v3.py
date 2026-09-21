from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "campaigns/core-v1/material/evidence/f3-native-mls-audited-source-job-specs-v3-20260920.json"
JOB_DIR = ROOT / "campaigns/core-v1/material/jobs/f3-native-mls-audited-v2"


def test_audited_matrix_job_specs_bind_all_requested_rows() -> None:
    bundle = json.loads(BUNDLE.read_text())
    rows = [item["matrix_row"] for item in bundle["configs"]]
    assert rows == [16, 17, 18, 19, 20, 21, 22, 23, 29, 31]
    assert bundle["qualification_claim"].startswith("none;")
    assert bundle["runtime_policy"] == {
        "host": "ada",
        "gpu_required": False,
        "gpu_peak_mib": 0,
        "cpu_cores": 2,
        "ram_mib": 4096,
        "blas_threads": 1,
        "central_ledger_mutation": 0,
        "distinct_product_filenames": True,
        "runtime_reserved_result_name": "result.json",
    }
    for item in bundle["configs"]:
        path = ROOT / Path(item["path"]).relative_to(ROOT)
        assert path.is_file()
        spec = json.loads(path.read_text())
        assert spec["matrix_row"] == item["matrix_row"]
        assert spec["qualification_only"] is True
        assert spec["t2_qualification_granted"] is False
        assert spec["central_ledger_mutation"] == 0
        assert spec["resources"]["gpu_peak_mib"] == 0
        assert spec["env"]["OPENBLAS_NUM_THREADS"] == "1"
        assert spec["env"]["OMP_NUM_THREADS"] == "1"
        assert spec["env"]["MKL_NUM_THREADS"] == "1"
        assert all("result.json" not in output for output in spec["required_outputs"])


def test_4096_s4_timeout_is_explicit_twofold_profile_estimate() -> None:
    bundle = json.loads(BUNDLE.read_text())
    large = [item for item in bundle["configs"] if item["matrix_row"] in (29, 31)]
    assert len(large) == 2
    for item in large:
        assert item["timeout_seconds"] == 24000
        estimate = item["estimate"]
        assert estimate["method"].startswith("2.0x the measured 4096-seed s2")
        assert estimate["wall_seconds"] > 20000
