from __future__ import annotations

import json

from scripts.r3_g2_tracer_validation import release_sidecar_coverage


def test_release_sidecar_coverage_distinguishes_fluid_and_body_cases(tmp_path):
    release = tmp_path / "release"
    sidecar = release / "sidecars" / "fluid.h5"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_bytes(b"candidate geometry")
    manifest = release / "manifest.json"
    manifest.write_text(json.dumps({
        "cases": [
            {
                "case_id": "fluid",
                "family": "F1",
                "geometry": {"boundary_sidecar": "sidecars/fluid.h5"},
            },
            {"case_id": "body", "family": "F6", "geometry": {}},
        ]
    }))
    report = release_sidecar_coverage(manifest)
    assert report["case_count"] == 1
    assert report["declared_count"] == 1
    assert report["existing_count"] == 1
    assert report["all_cases_have_existing_sidecar"] is True


def test_release_sidecar_coverage_rejects_missing_or_escaping_links(tmp_path):
    release = tmp_path / "release"
    release.mkdir()
    manifest = release / "manifest.json"
    manifest.write_text(json.dumps({
        "cases": [
            {
                "case_id": "missing",
                "family": "F2",
                "geometry": {"boundary_sidecar": "sidecars/missing.h5"},
            },
            {
                "case_id": "escape",
                "family": "F3",
                "geometry": {"boundary_sidecar": "../outside.h5"},
            },
        ]
    }))
    report = release_sidecar_coverage(manifest)
    assert report["case_count"] == 2
    assert report["existing_count"] == 0
    assert report["all_cases_have_existing_sidecar"] is False
    assert all(not row["exists"] for row in report["cases"])
