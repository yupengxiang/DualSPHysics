import json
from pathlib import Path
P = Path(__file__).resolve().parents[1]
def test_fresh104_disabled_and_closed():
    idx = json.loads((P / "requests/index.json").read_text())
    assert idx["case_count"] == 24 and idx["request_count"] == 96
    assert idx["all_disabled"] is True
    for row in idx["requests"]:
        req = json.loads(Path(row["path"]).read_text())
        assert req["disabled"] and req["execution_allowed"] is False and req["launch"] is False
        assert req["input_files"] and set(req["input_sha256"]) == set(req["input_files"])
        assert all(isinstance(v, str) and len(v) == 64 for v in req["input_sha256"].values())
        for key, value in req["expected_outputs"].items():
            if key.endswith("sha256") or key in {"output_sha256", "all_sha256"}:
                assert value is None
