"""Synthetic serialization/ref-graph tests; the codec grants no trust or credit."""
import hashlib
import json

import pytest

from scripts.core_f4_qualification_bundle_v3_codec import (
    BINDING_ADMISSION_SCHEMA,
    BundleCodecError,
    DOMAIN_SEPARATOR,
    EVALUATION_ADMISSION_SCHEMA,
    EVALUATION_SOURCE_SCHEMA,
    F4_REVISION_ID,
    F4_SCOPE_ID,
    OUTER_SCHEMA,
    ROLE_ORDER,
    canonical_json_bytes,
    document_digests,
    inspect_untrusted_admission_envelope,
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


def _ref(raw, *, role, target_schema, object_id):
    raw_sha256, canonical_sha256 = document_digests(raw)
    return {
        "stage": "qualification",
        "role": role,
        "object_id": object_id,
        "target_schema": target_schema,
        "bytes": len(raw),
        "raw_sha256": raw_sha256,
        "canonical_json_sha256": canonical_sha256,
    }


def _synthetic_evaluation_source(variant="base"):
    value = {
        "schema": EVALUATION_SOURCE_SCHEMA,
        "scope_id": F4_SCOPE_ID,
        "revision_id": F4_REVISION_ID,
        "qualification_claim": "none",
        "static_manifest": "synthetic-manifest.json",
        "static_manifest_sha256": "2" * 64,
        "static_contract_pass": True,
        "static_issues": [],
        "binding_results": {},
        "cell_count": 15,
        "scheduled_solver_cells": sorted((*range(12), 13, 14)),
        "reused_canary_cells": [12],
        "matrix_complete": False,
        "T1_numerical": False,
        "promotion_status": "blocked_until_14_scheduled_products_and_all_gates",
    }
    if variant in {"matrix", "complete"}:
        value.update(cells=[], missing=[], failures=[])
    if variant == "complete":
        value.update(
            comparisons=[],
            checks={
                "static_contract": True,
                "matrix_complete": False,
                "all_case_hard_mass_event_gates": False,
                "spatial": False,
                "independent_checks": False,
                "time_and_output": False,
                "cell12_reuse_verified": False,
                "cell12_reuse_does_not_inherit_qualification": True,
            },
        )
    return value


def _valid_untrusted_graph(*, mode="formal_release", t1=True, source_variant="base", source_payload=None):
    if source_payload is None:
        source_payload = _synthetic_evaluation_source(source_variant)
    source_raw = canonical_json_bytes(source_payload)
    source_ref = _ref(
        source_raw, role="qualification_evaluation_raw",
        target_schema=EVALUATION_SOURCE_SCHEMA, object_id="evaluation-source-v1",
    )
    checks = {
        "static_contract": True,
        "matrix_complete": True,
        "all_case_hard_mass_event_gates": True,
        "spatial": True,
        "independent_checks": True,
        "time_and_output": True,
        "cell12_reuse_verified": True,
        "cell12_reuse_does_not_inherit_qualification": True,
    }
    all_cells = list(range(15))
    evaluation = {
        "schema": EVALUATION_ADMISSION_SCHEMA,
        "scope_id": F4_SCOPE_ID,
        "revision_id": F4_REVISION_ID,
        "manifest_sha256": "1" * 64,
        "evaluation_source_ref": source_ref,
        "evaluation_raw_sha256": source_ref["raw_sha256"],
        "evaluation_canonical_json_sha256": source_ref["canonical_json_sha256"],
        "cell_indices": all_cells,
        "passed_cell_indices": all_cells,
        "missing_indices": [],
        "failure_indices": [],
        "checks": checks,
        "matrix_complete": True,
        "T1_numerical": t1,
        "artifact_bindings_verified": True,
        "declaration_consistent": True,
        "promotion_status": (
            "qualified_candidate_pending_root_review" if t1 else "blocked_until_all_gates"
        ),
    }
    evaluation_raw = canonical_json_bytes(evaluation)
    evaluation_ref = _ref(
        evaluation_raw, role="qualification_evaluation_admission",
        target_schema=EVALUATION_ADMISSION_SCHEMA, object_id="evaluation-admission-v1",
    )
    binding = {
        "schema": BINDING_ADMISSION_SCHEMA,
        "scope_id": F4_SCOPE_ID,
        "revision_id": F4_REVISION_ID,
        "manifest_sha256": evaluation["manifest_sha256"],
        "evaluation_raw_sha256": evaluation["evaluation_raw_sha256"],
        "reevaluation_sha256": evaluation["evaluation_canonical_json_sha256"],
        "evaluation_admission_canonical_json_sha256": evaluation_ref["canonical_json_sha256"],
        "matrix_complete": evaluation["matrix_complete"],
        "T1_numerical": evaluation["T1_numerical"],
        "cell_indices": list(evaluation["cell_indices"]),
        "passed_cell_indices": list(evaluation["passed_cell_indices"]),
        "missing_indices": [],
        "failure_indices": [],
        "checks": dict(checks),
        "artifact_bindings_verified": True,
        "declaration_consistent": True,
    }
    binding_raw = canonical_json_bytes({
        "schema": BINDING_ADMISSION_SCHEMA,
        "binding": binding,
        "evaluation_ref": evaluation_ref,
    })
    binding_ref = _ref(
        binding_raw, role="qualification_binding_admission",
        target_schema=BINDING_ADMISSION_SCHEMA, object_id="binding-admission-v1",
    )
    envelope_raw = canonical_json_bytes({
        "schema": OUTER_SCHEMA,
        "mode": mode,
        "scope_id": F4_SCOPE_ID,
        "binding_ref": binding_ref,
        "evaluation_ref": evaluation_ref if mode == "formal_release" else None,
    })
    documents = {
        "binding_admission": binding_raw,
        "evaluation_admission": evaluation_raw,
        "evaluation_source_raw": source_raw,
    }
    return envelope_raw, documents


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


@pytest.mark.parametrize("mode", ["formal_release", "preparation_only"])
@pytest.mark.parametrize("source_variant", ["base", "matrix", "complete"])
def test_v12_v13_reference_graph_is_consistent_but_never_a_capability(mode, source_variant):
    envelope, documents = _valid_untrusted_graph(mode=mode, source_variant=source_variant)
    result = inspect_untrusted_admission_envelope(envelope, documents)
    assert result["status"] == "metadata_ref_graph_consistent_untrusted"
    assert result["mode"] == mode
    assert result["qualification_bundle_sha256"]
    assert result["formal_qualification_admitted"] is False
    assert result["capability_minted"] is False
    assert result["evaluation_source_semantics_verified"] is False
    assert result["object_allowlist_verified"] is False
    assert result["descriptor_root_verified"] is False
    assert result["producer_identity_verified"] is False


def test_reference_graph_rejects_raw_hash_role_copy_and_exact_type_mismatch():
    envelope, documents = _valid_untrusted_graph()
    changed_docs = dict(documents)
    binding_object = strict_json_object(documents["binding_admission"])
    changed_binding = json.dumps(
        dict(reversed(tuple(binding_object.items()))), separators=(",", ":")
    ).encode("utf-8")
    assert len(changed_binding) == len(documents["binding_admission"])
    assert document_digests(changed_binding)[1] == document_digests(
        documents["binding_admission"]
    )[1]
    assert document_digests(changed_binding)[0] != document_digests(
        documents["binding_admission"]
    )[0]
    changed_docs["binding_admission"] = changed_binding
    with pytest.raises(BundleCodecError, match="raw SHA-256"):
        inspect_untrusted_admission_envelope(envelope, changed_docs)

    outer = strict_json_object(envelope)
    outer["binding_ref"]["role"] = "qualification_evaluation_raw"
    with pytest.raises(BundleCodecError, match="role"):
        inspect_untrusted_admission_envelope(canonical_json_bytes(outer), documents)

    outer = strict_json_object(envelope)
    outer["binding_ref"]["bytes"] = True
    with pytest.raises(BundleCodecError, match="exact positive integer"):
        inspect_untrusted_admission_envelope(canonical_json_bytes(outer), documents)


def test_reference_graph_rejects_outer_copy_mismatch_and_wrong_t1_predicate():
    envelope, documents = _valid_untrusted_graph()
    outer = strict_json_object(envelope)
    outer["evaluation_ref"]["object_id"] = "different-object"
    with pytest.raises(BundleCodecError, match="refs differ"):
        inspect_untrusted_admission_envelope(canonical_json_bytes(outer), documents)

    bad_envelope, bad_documents = _valid_untrusted_graph(t1=False)
    with pytest.raises(BundleCodecError, match="T1_numerical"):
        inspect_untrusted_admission_envelope(bad_envelope, bad_documents)


def test_reference_graph_rejects_unknown_fields_bad_object_id_and_prep_copy():
    envelope, documents = _valid_untrusted_graph()
    outer = strict_json_object(envelope)
    outer["unexpected"] = True
    with pytest.raises(BundleCodecError, match="exact schema"):
        inspect_untrusted_admission_envelope(canonical_json_bytes(outer), documents)

    outer = strict_json_object(envelope)
    outer["binding_ref"]["object_id"] = "../outside"
    with pytest.raises(BundleCodecError, match="identifier domain"):
        inspect_untrusted_admission_envelope(canonical_json_bytes(outer), documents)

    prep_envelope, prep_documents = _valid_untrusted_graph(mode="preparation_only")
    prep = strict_json_object(prep_envelope)
    prep["evaluation_ref"] = {"not": "null"}
    with pytest.raises(BundleCodecError, match="must have a null outer evaluation_ref"):
        inspect_untrusted_admission_envelope(canonical_json_bytes(prep), prep_documents)


def test_reference_graph_rejects_inexact_evaluation_source_result_shape():
    source = _synthetic_evaluation_source()
    source["unreviewed_claim"] = True
    envelope, documents = _valid_untrusted_graph(source_payload=source)
    with pytest.raises(BundleCodecError, match="exact evaluator-v2 result shape"):
        inspect_untrusted_admission_envelope(envelope, documents)

    source = _synthetic_evaluation_source()
    source["cell_count"] = True
    envelope, documents = _valid_untrusted_graph(source_payload=source)
    with pytest.raises(BundleCodecError, match="exact positive integer"):
        inspect_untrusted_admission_envelope(envelope, documents)

    for bad_status in ([], {}):
        source = _synthetic_evaluation_source()
        source["promotion_status"] = bad_status
        envelope, documents = _valid_untrusted_graph(source_payload=source)
        with pytest.raises(BundleCodecError, match="promotion_status"):
            inspect_untrusted_admission_envelope(envelope, documents)
