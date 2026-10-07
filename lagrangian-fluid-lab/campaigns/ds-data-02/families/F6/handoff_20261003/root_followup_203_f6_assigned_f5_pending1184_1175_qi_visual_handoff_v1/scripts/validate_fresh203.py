#!/usr/bin/env python3
"""Read-only validator for fresh203; never opens scientific payloads."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "metadata/f5-pending-1184-1175-qi-visual-handoff.json"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def refs(x):
    """Yield metadata refs, including refs nested in case observations."""
    if isinstance(x, dict):
        if "path" in x and "hash_policy" in x:
            yield x
        for v in x.values():
            yield from refs(v)
    elif isinstance(x, list):
        for v in x:
            yield from refs(v)


def validate_ref(r):
    policy = r["hash_policy"]
    # Producer-attested H5/BI4 paths are deliberately never opened by this
    # source validator, so they do not carry an exists_at_observation claim.
    if policy == "producer_attested_only":
        assert r.get("read_or_hashed_by_source_agent") is False
        assert len(r.get("producer_attested_sha256", "")) >= 32
        return
    p = Path(r["path"])
    assert r["exists_at_observation"] is True, p
    assert p.exists(), p
    if policy == "metadata_file":
        assert digest(p) == r["observed_sha256"], p
    elif policy == "metadata_live_snapshot":
        # A running execution receipt is mutable.  Validate the captured
        # digest's shape and path existence, but do not mistake a later
        # terminal rewrite for a mismatch in this immutable observation.
        assert r.get("mutable_at_observation") is True
        assert len(r.get("observed_sha256", "")) == 64
    elif policy == "producer_attested_only":
        # Handled before path access above.
        raise AssertionError("producer_attested_only branch reached unexpectedly")
    else:
        raise AssertionError(f"unknown metadata ref policy: {policy}")


def main() -> int:
    d = json.loads(META.read_text())
    assert d["schema"] == "ds02.f6.fresh203.f5-pending-qi-visual-handoff.v1"
    assert len(d["cases"]) == 2
    assert d["source_boundary"]["science_payload_IO"] is False
    assert d["source_boundary"]["arrays_read_or_hashed"] is False
    assert d["source_boundary"]["new_jobs_started"] is False
    assert d["review_semantics"]["case_credit"] == 0
    aliases = {c["alias"] for c in d["cases"]}
    assert aliases == {"M095_T090", "M104_T085"}
    for c in d["cases"]:
        assert c["family_id"] == "F5"
        assert c["physical_case_id"] and c["case_id"]
        assert c["identity_policy"]["mother_alias_is_not_unique"] is True
        assert c["native"]["status"] in ("completed", "completed/0")
        assert c["native"]["returncode"] == 0
        assert c["gencase"]["returncode"] == 0
        assert c["initial_qa"]["returncode"] == 0
        assert c["typed"]["returncode"] == 0
        assert c["xmf"]["returncode"] == 0
        assert c["counts_and_time"]["expected_frames"] == 801
        assert c["counts_and_time"]["expected_particles"] == 194427
        assert c["counts_and_time"]["solver_dimension"] == 3
        assert c["counts_and_time"]["typed_actual_time_window_s"]["strictly_increasing"] is True
        assert c["scope_roles"]["roles_must_not_be_collapsed"] is True
        presence = c["scope_roles"]["native_request_field_presence"]
        assert presence["physical_condition_sha256"] is True
        assert presence["source_definition_sha256"] is (c["alias"] == "M095_T090")
        if c["alias"] == "M095_T090":
            assert presence["source_plan_condition_sha256"] is False
            assert presence["source_plan_physical_condition_sha256"] is False
            assert c["scope_roles"]["native_request_source_plan_physical_condition_sha256"] is None
        else:
            assert presence["source_plan_physical_condition_sha256"] is True
            assert c["scope_roles"]["native_request_source_plan_physical_condition_sha256"] == c["scope_roles"]["native_condition_sha256"]
        assert c["flags"]["case_credit"] == 0 and c["flags"]["Q_N"] is False and c["flags"]["Q_E"] is False
        assert c["future_qi_visual"]["own_full801_QI"]["proof_path"] is None
        assert c["future_qi_visual"]["personal_visual_review"]["reviewed_by_source_agent"] is False
        obs = c["render_observation"]
        initial = obs["initial_live_observation"]
        assert initial["proc_exists"] is True
        assert initial["start_ticks_matches"] is True
        assert initial["cmdline_contains_expected_controller"] is True
        assert obs["observation_contract"]["initial_start_ticks_is_authoritative"] is True
        assert obs["observation_contract"]["terminal_status_is_taken_from_execution_receipt"] is True
        if c["alias"] == "M095_T090":
            # The renderer naturally terminated after a verified live census.
            assert obs["start_ticks_matches"] is False
            assert obs["terminal_after_verified_initial_live"] is True
            assert obs["render_receipt_status_at_observation"] == "completed"
            assert obs["render_returncode_at_observation"] == 0
            assert obs["terminal_receipt_observed"] is True
            assert obs["published"] is True
            assert obs["published_report_observed"] is True
            assert obs["render_publish_receipt"]["hash_policy"] == "metadata_file"
            assert c["status"] == "original-render-completed-published-awaiting-root-QI-and-personal-review"
            # The producer receipt is terminal and may be checked directly.
            receipt = json.loads(Path(obs["render_receipt"]["path"]).read_text())
            assert receipt.get("status") == "completed"
            assert receipt.get("returncode") == 0
        else:
            # The receipt exists only as a mutable running snapshot.
            assert obs["start_ticks_matches"] is True
            assert obs["render_receipt_status_at_observation"] == "running"
            assert obs["render_returncode_at_observation"] is None
            assert obs["terminal_receipt_observed"] is False
            assert obs["published"] is False
            assert obs["published_report_observed"] is False
            assert obs["render_report"] is None
            assert obs["render_receipt"]["hash_policy"] == "metadata_live_snapshot"
            assert c["status"] == "original-render-running-observed-awaiting-terminal-receipt"
        for r in refs(c["metadata_refs"]):
            validate_ref(r)
    print("fresh203 metadata validator: PASS (M095 terminal/published, M104 running snapshot; no scientific payload opened)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
