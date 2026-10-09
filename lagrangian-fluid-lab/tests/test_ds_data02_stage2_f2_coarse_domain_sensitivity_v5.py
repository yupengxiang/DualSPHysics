from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).parents[1]
REQUEST = ROOT / "campaigns/ds-data-02/stage2/requests/f2-s1-coarse-domain-sensitivity-v1/f2-s1-coarse-domain-sensitivity-v5-root-prepared-130-001.json"
PREPARED = ROOT / "campaigns/ds-data-02/stage2/prepared/f2-s1-coarse-domain-sensitivity-v1/prepared.json"
CANDIDATE = ROOT / "campaigns/ds-data-02/stage2/prepared/f2-s1-coarse-domain-sensitivity-v1/F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_DOMAIN_MARGIN_V1.xml"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _domain(path: Path) -> dict[str, dict[str, str]]:
    root = ET.parse(path).getroot()
    for element in root.iter():
        if _local_tag(element) != "simulationdomain":
            continue
        return {
            name: {axis: next(child for child in element if _local_tag(child) == name).attrib[axis] for axis in ("x", "y", "z")}
            for name in ("posmin", "posmax")
        }
    raise AssertionError("simulationdomain missing")


def test_domain_request_is_canonical_and_source_preserving():
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    assert request["schema"] == "ds02.stage2.external-solver-request.v5"
    assert request["status"] == "READY_FOR_PARENT_GUARD"
    assert request["attempt_id"].endswith("root-130-001")
    assert request["role"] == "DEVELOPMENT"
    assert request["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    body = {key: value for key, value in request.items() if key != "sha256"}
    import hashlib
    expected = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode()).hexdigest()
    assert request["sha256"] == expected
    resolved = [str(Path(path).expanduser().resolve()) for path in request["input_files"]]
    assert len(resolved) == len(set(resolved))
    candidate = request["source_preserving_control"]
    assert candidate["status"] == "PREREGISTERED_NOT_RUN"
    assert candidate["fixed"]["initial_bi4_sha256"] == "b95839d68b46acd4a1cc3a8805b2829aefc27b23b02b142d3249d20f7fbaeadd"
    assert candidate["fixed"]["motion_sha256"] == "fa9cdbaea99cbbdad8005a6cc11cb080864fe4059abfd020d987fbfec5f65d7b"
    assert candidate["fixed"]["mass_rescale"] is False
    assert candidate["candidate_xml_sha256"] == _sha(CANDIDATE)
    assert request["input_sha256"][str(CANDIDATE)] == _sha(CANDIDATE)


def test_candidate_xml_changes_only_the_six_numerical_domain_faces():
    prepared = json.loads(PREPARED.read_text(encoding="utf-8"))
    source = Path(prepared["source_generated_xml"])
    assert _sha(source) == prepared["source_generated_xml_sha256"]
    source_domain = _domain(source)
    candidate_domain = _domain(CANDIDATE)
    assert source_domain == prepared["source_domain"]
    assert candidate_domain == prepared["candidate_domain"]
    assert candidate_domain["posmin"]["x"] == "-1.40015500"
    assert candidate_domain["posmin"]["y"] == "-1.20010000"
    assert candidate_domain["posmin"]["z"] == "-0.50017012"
    assert candidate_domain["posmax"]["x"] == "3.00015500"
    assert candidate_domain["posmax"]["y"] == "1.20010000"
    assert candidate_domain["posmax"]["z"] == "2.20017012"
    assert prepared["changed_xml_paths"] == [
        "parameters/simulationdomain/posmin/@x",
        "parameters/simulationdomain/posmin/@y",
        "parameters/simulationdomain/posmin/@z",
        "parameters/simulationdomain/posmax/@x",
        "parameters/simulationdomain/posmax/@y",
        "parameters/simulationdomain/posmax/@z",
    ]


def test_source_aliases_resolve_to_inherited_small_known_sha_without_reading_bi4():
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    aliases = request["source_preserving_control"]["input_aliases"]
    bi4 = Path(aliases["candidate_bi4_symlink"]["path"])
    motion = Path(aliases["candidate_motion_symlink"]["path"])
    assert bi4.is_symlink() and motion.is_symlink()
    assert aliases["candidate_bi4_symlink"]["sha256"] == "b95839d68b46acd4a1cc3a8805b2829aefc27b23b02b142d3249d20f7fbaeadd"
    assert aliases["candidate_motion_symlink"]["sha256"] == "fa9cdbaea99cbbdad8005a6cc11cb080864fe4059abfd020d987fbfec5f65d7b"
