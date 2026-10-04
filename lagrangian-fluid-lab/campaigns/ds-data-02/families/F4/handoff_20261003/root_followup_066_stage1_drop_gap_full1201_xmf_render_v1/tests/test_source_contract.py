import hashlib
import json
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
ENDPOINTS = [
    "F4_DROP_ENDPOINT_GAP0p18000_DP010",
    "F4_DROP_ENDPOINT_GAP0p26000_DP010",
]
CANONICAL = {
    ENDPOINTS[0]: (
        "F4_DROP_B08_gap0p18000_xoff0p00000_yoff0p00000_uz0p50000",
        "773e18d598ef3452bdf1721ed894a0a90af22d37b3d3dada9fd7bada9e15de56",
    ),
    ENDPOINTS[1]: (
        "F4_DROP_B08_gap0p26000_xoff0p00000_yoff0p00000_uz0p50000",
        "b625efb4404dfa63055fae940f7a078a6ecf94dfb323d7ce71ccb4812aa75412",
    ),
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
def test_static_contract():
    worker = PKG / "workers/render_f4_full_saved_animation.py"
    text = worker.read_text()
    assert "F3" not in text
    assert "F4 DROP GAP FULL1201" in text
    assert "actual t={time:.17g}" in text
    assert ".17g" in text
    assert "CameraParallelScale = 0.43" not in text
    assert "camera_for_bounds" in text
    assert "source_reader_unclipped" in text
    assert "boundary_bbox_preview_only" in text or "bbox preview" in text.lower()

    camera = load(PKG / "camera-spec.json")
    assert camera["family_id"] == "F4"
    assert len(camera["views"]) == 2
    assert camera["framing"]["physical_tank_high_m"] == [1.2, 0.4, 0.6]
    assert camera["native_reader_policy"]["boundary_outline_bbox_preview_only"] is True
    assert camera["text_policy"]["actual_time_format"] == ".17g"

    pages = load(PKG / "contact-page-keys.json")
    assert pages["page_count"] == 51
    assert pages["pages"][0]["frame_start"] == 0
    assert pages["pages"][-1]["frame_end"] == 1200
    assert sum(page["frame_count"] for page in pages["pages"]) == 1201

    for case in ENDPOINTS:
        cid, condition = CANONICAL[case]
        xb = load(PKG / "bindings" / f"{case}-xmf-binding.json")
        rb = load(PKG / "bindings" / f"{case}-render-binding.json")
        xr = load(PKG / "requests" / f"{case}-xmf-request.json")
        rr = load(PKG / "requests" / f"{case}-render-request.json")
        assert xb["physical_case_id"] == cid
        assert xb["topphysical_case_id"] == cid
        assert xb["physical_condition_sha256"] == condition
        assert xb["expected_frames"] == 1201
        assert xb["expected_particles"] == 83233
        assert xb["fluid_particles_expected"] == 59072
        assert xb["camera_spec"]["family_id"] == "F4"
        assert xb["bbox_preview_only"] is True
        assert xb["time_policy"]["xdmf_format"] == ".17g"
        assert xb["source_package_read_policy"]["h5_arrays_read"] is False
        assert rb["expected_contact_pages"] == 51
        assert rb["render_worker"]["source_sha256"] == "5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66"
        for request in (xr, rr):
            assert request["launch"] is False
            assert request["launch_allowed"] is False
            assert request["status"] == "source_only_disabled"
            assert request["family_id"] == "F4"
            assert request["independent_case_count_increment"] == 0
        assert xr["output_contract"]["frames"] == 1201
        assert xr["output_contract"]["no_time_rounding"] is True
        assert rr["output_contract"]["frames"] == 1201
        assert rr["output_contract"]["contact_pages"] == 51
        assert rr["output_contract"]["f4_labels_only"] is True
        assert rr["camera_contract"]["framing"]["physical_tank_high_m"] == [1.2, 0.4, 0.6]
        assert xr["input_sha256"][xb["trajectory_h5"]] == H5[case]
        for path, expected in xr["input_sha256"].items():
            if path == xb["trajectory_h5"]:
                continue
            p = Path(path)
            assert p.is_file(), p
            assert sha(p) == expected, p
        for path, expected in rr["input_sha256"].items():
            p = Path(path)
            assert p.is_file(), p
            assert sha(p) == expected, p
