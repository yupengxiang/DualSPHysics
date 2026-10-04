import hashlib
import json
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
ENDPOINTS = ["F4_DROP_ENDPOINT_GAP0p18000_DP010", "F4_DROP_ENDPOINT_GAP0p26000_DP010"]
CANONICAL = {
    ENDPOINTS[0]: ("F4_DROP_B08_gap0p18000_xoff0p00000_yoff0p00000_uz0p50000", "773e18d598ef3452bdf1721ed894a0a90af22d37b3d3dada9fd7bada9e15de56"),
    ENDPOINTS[1]: ("F4_DROP_B08_gap0p26000_xoff0p00000_yoff0p00000_uz0p50000", "b625efb4404dfa63055fae940f7a078a6ecf94dfb323d7ce71ccb4812aa75412"),
}
H5 = {
    ENDPOINTS[0]: "ed810b818b7bda53d98c201dc8ad1ee9a0c2a610bead5fde38a1b26af4c0fd52",
    ENDPOINTS[1]: "d7fab5e7c8b7d7a9e93ffdea5bc418eede946204da81abb17f51698a3157e3c0",
}
def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()
def load(path):
    return json.loads(Path(path).read_text())
def test_static_native_scan_contract():
    worker = PKG / "workers/render_f4_full_saved_animation.py"
    text = worker.read_text()
    assert "_scan_native_bounds" in text
    assert "native valid positions scanned through XdmfReader" in text
    assert "camera/domain bounds are provenance-only" in text
    assert "actual t={time:.17g}" in text
    camera = load(PKG / "camera-spec.json")
    assert "camera_bounds" not in camera and "domain_bounds" not in camera
    assert "xml_defined_domain_bounds" in camera and camera["family_id"] == "F4"
    pages = load(PKG / "contact-page-keys.json")
    assert pages["page_count"] == 51 and pages["pages"][0]["frame_start"] == 0
    assert pages["pages"][-1]["frame_end"] == 1200
    assert sum(p["frame_count"] for p in pages["pages"]) == 1201
    worker_hash = sha(worker)
    for case in ENDPOINTS:
        cid, condition = CANONICAL[case]
        xb = load(PKG / "bindings" / f"{case}-xmf-binding.json")
        rb = load(PKG / "bindings" / f"{case}-render-binding.json")
        xr = load(PKG / "requests" / f"{case}-xmf-request.json")
        rr = load(PKG / "requests" / f"{case}-render-request.json")
        assert xb["physical_case_id"] == cid and xb["physical_condition_sha256"] == condition
        assert xb["expected_frames"] == 1201 and xb["expected_particles"] == 83233 and xb["fluid_particles_expected"] == 59072
        assert "camera_bounds" not in xb and "domain_bounds" not in xb
        assert "camera_bounds" not in xb["camera_spec"] and "domain_bounds" not in xb["camera_spec"]
        assert xb["future_outputs"]["xmf"]["case_xmf_sha256"] is None
        assert rb["expected_contact_pages"] == 51 and rb["render_worker"]["sha256"] == worker_hash
        assert "camera_bounds" not in rb and "domain_bounds" not in rb
        for req in (xr, rr):
            assert req["launch"] is False and req["launch_allowed"] is False
            assert req["status"] == "source_only_disabled" and req["independent_case_count_increment"] == 0
        assert xr["output_contract"]["frames"] == 1201 and rr["output_contract"]["contact_pages"] == 51
        assert "camera_bounds" not in rr["camera_contract"] and "domain_bounds" not in rr["camera_contract"]
        assert xr["input_sha256"][xb["trajectory_h5"]] == H5[case]
        for req in (xr, rr):
            for path, expected in req["input_sha256"].items():
                if path.endswith(".h5"):
                    assert expected == H5[case]
                else:
                    assert Path(path).is_file() and sha(path) == expected
