"""Synthetic serialization-only tests; the codec grants no trust or credit."""
import hashlib

import pytest

from scripts.core_f4_qualification_bundle_v3_codec import (
    BundleCodecError,
    DOMAIN_SEPARATOR,
    ROLE_ORDER,
    canonical_json_bytes,
    document_digests,
    positive_builtin_int,
    qualification_bundle_sha256,
    strict_json_object,
)


def _golden_inputs():
    envelope = b'{"mode":"synthetic"}'
    documents = {
        "binding_admission": b'{"a":1}',
        "evaluation_admission": b'{"b":2}',
        "evaluation_source_raw": b'{"c":3}',
    }
    return envelope, documents


def test_v13_serialization_golden_vector_and_domain_separator():
    envelope, documents = _golden_inputs()
    assert len(envelope) == 20
    assert DOMAIN_SEPARATOR == b"CORE-F4-QUALIFICATION-BUNDLE-V3\x0a"
    assert tuple(documents) == ROLE_ORDER
    assert document_digests(documents["binding_admission"]) == (
        "015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862",
        "015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862",
    )
    assert document_digests(documents["evaluation_admission"]) == (
        "0ab1a6d394cd30195f0642b67ae1180c375ffadf5dd7f39c390668b5fdb6da93",
        "0ab1a6d394cd30195f0642b67ae1180c375ffadf5dd7f39c390668b5fdb6da93",
    )
    assert document_digests(documents["evaluation_source_raw"]) == (
        "caba9cb06ac77da7781b8bbd7e0700c58ea69bc7d8b12f0b6695a2af6ee6a6b3",
        "caba9cb06ac77da7781b8bbd7e0700c58ea69bc7d8b12f0b6695a2af6ee6a6b3",
    )
    assert qualification_bundle_sha256(envelope, documents) == (
        "10c3a2d73f51262f595de744f111580157c4d37521c650a530cebe6e4142137e"
    )


def test_bundle_digest_uses_fixed_role_order_and_binds_raw_bytes():
    envelope, documents = _golden_inputs()
    reordered = dict(reversed(tuple(documents.items())))
    assert qualification_bundle_sha256(envelope, reordered) == qualification_bundle_sha256(
        envelope, documents
    )
    changed = dict(documents)
    changed["binding_admission"] = b'{ "a" : 1 }'
    assert qualification_bundle_sha256(envelope, changed) != qualification_bundle_sha256(
        envelope, documents
    )


@pytest.mark.parametrize("raw", [
    b'{"x":1,"x":2}',
    b'{"outer":{"x":1,"x":2}}',
    b'{"x":NaN}',
    b'{"x":Infinity}',
    b'{"x":-Infinity}',
    b'{"x":1e999}',
    b'{"x":1',
    b'{"x":"\xff"}',
    b'[1,2,3]',
])
def test_strict_json_rejects_duplicate_nonfinite_invalid_or_nonobject_inputs(raw):
    with pytest.raises(BundleCodecError):
        strict_json_object(raw)


def test_exact_raw_type_role_set_and_positive_integer_rules():
    envelope, documents = _golden_inputs()
    with pytest.raises(BundleCodecError, match="exact bytes"):
        strict_json_object(bytearray(b"{}"))
    with pytest.raises(BundleCodecError, match="exactly the three V3 roles"):
        qualification_bundle_sha256(envelope, {"binding_admission": documents["binding_admission"]})
    for invalid in (True, False, 0, -1, 1.0, "1"):
        with pytest.raises(BundleCodecError, match="exact positive integer"):
            positive_builtin_int(invalid, name="hdf5_size_bytes")
    assert positive_builtin_int(1, name="hdf5_size_bytes") == 1


def test_canonical_json_uses_v12_utf8_digest_rules_without_newline():
    canonical = canonical_json_bytes({"z": 1, "name": "é"})
    assert canonical == b'{"name":"\\u00e9","z":1}'
    assert not canonical.endswith(b"\n")
    assert hashlib.sha256(canonical).hexdigest() == (
        "5864fa4df6a1158336568275a6eda18da860fbc1b38bc48d247f01b80c47e9d0"
    )
