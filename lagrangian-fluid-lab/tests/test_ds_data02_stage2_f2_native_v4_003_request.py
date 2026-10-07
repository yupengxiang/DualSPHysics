from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/v4/"
    "f2-s1-native-raw-to-typed-reference-compare-request-v4-003-root-canonical.json"
)
PLACEHOLDER = "PENDING_PARENT_GUARD_CONTENT_SHA256"


def _canonical_sha(value: dict) -> str:
    payload = dict(value)
    payload.pop("sha256", None)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def test_v4_003_request_is_canonical_and_parent_guard_ready() -> None:
    request = json.loads(REQUEST.read_text())
    assert request["schema"] == "ds02.stage2.f2-native-raw-to-typed-reference-compare-request.v4"
    assert request["status"] == "READY_FOR_PARENT_GUARD"
    assert request["role"] == "DEVELOPMENT"
    assert request["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    assert request["sha256"] == _canonical_sha(request)

    wrapper = request["root_canonical_wrapper"]
    assert wrapper["current_case_index"] == 78
    assert wrapper["current_identity_binding"]["frames"] == 401
    assert wrapper["current_identity_binding"]["particles"] == 418104
    assert wrapper["reference_hdf5_binding"]["sha256"] == (
        "f882a38dca872cbe81523b0691ea10ff6cc122037917b5d0a3004337eb6a8e9d"
    )
    assert wrapper["raw_producer_binding"]["expected_raw_tree_sha256"] == (
        "08b0f5bef680bffc6bd0af05c81444340da6877eff403e318008994a56e4d0cd"
    )
    assert wrapper["raw_producer_binding"]["per_frame_sha256_status"] == (
        "UNKNOWN_PENDING_PARENT_WORKER"
    )
    assert wrapper["raw_producer_binding"]["per_frame_sha256_declared_in_request"] is False
    assert wrapper["raw_producer_binding"]["no_h5_copy_for_reconstruction"] is True

    assert request["resource_request"]["cpu_threads"] == 1
    assert request["resource_request"]["max_wall_seconds"] == 5400
    assert request["resource_request"]["new_storage_reservation_bytes"] == 5 * 1024**3
    assert request["resource_request"]["max_rss_observational_bytes"] == 5 * 1024**3
    assert request["execution"]["requires_parent_stage2guard"] is True
    assert request["execution"]["labels"] == "v2 invokes frozen v15 operator and v16 forward sidecar after typed/reference comparison"

    guard_roles = wrapper["shared_four_guard_roles"]
    assert guard_roles == ["runtime_v2", "runtime_v4", "stage2_dispatch_v4", "strict_dispatch_v4"]
    for role in guard_roles:
        item = wrapper["shared_four_guard_sources"][role]
        assert Path(item["path"]).is_file()
        assert len(item["sha256"]) == 64


def test_v4_003_does_not_prefill_raw_frame_content_hashes() -> None:
    request = json.loads(REQUEST.read_text())
    base = json.loads(Path(request["base_v2_request"]["path"]).read_text())
    frames = base["raw_binding"]["frames"]
    assert len(frames) == 401
    assert all(item["sha256"] == PLACEHOLDER for item in frames)
    assert request["root_canonical_wrapper"]["raw_producer_binding"]["per_frame_sha256_status"] == (
        "UNKNOWN_PENDING_PARENT_WORKER"
    )
