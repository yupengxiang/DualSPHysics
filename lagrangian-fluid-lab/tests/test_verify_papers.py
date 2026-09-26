import json
from urllib.parse import unquote

import pytest

from scripts import verify_papers as verifier


class _Response:
    def __init__(self, body):
        self.body = (
            body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        )

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def _candidate():
    return {
        "id": "sample-paper",
        "arxiv_id": "2401.01234",
        "doi": "10.1000/example",
        "title": "A Sample Paper: Exact Metadata",
    }


def _install_catalog_responses(
    monkeypatch, *, crossref_title=None, openalex_title=None,
    openalex_doi=None, openalex_payload=None, fail=False
):
    expected = _candidate()
    title = crossref_title or expected["title"]

    def fake_urlopen(request, timeout):
        assert timeout > 0
        url = request.full_url
        if fail:
            raise OSError("temporary catalog outage")
        if url.startswith(verifier.ARXIV_API):
            assert request.get_header("Accept") == "*/*"
            return _Response(
                b'<feed xmlns="http://www.w3.org/2005/Atom">'
                b"<entry><id>https://arxiv.org/abs/2401.01234v2</id>"
                b"<title>A Sample Paper: Exact Metadata</title></entry></feed>"
            )
        if url.startswith(verifier.CROSSREF_API):
            assert request.get_header("Accept") == "application/json"
            return _Response({"message": {"DOI": "10.1000/example", "title": [title]}})
        if url.startswith(verifier.S2_BATCH_API):
            assert request.get_header("Accept") == "application/json"
            assert json.loads(request.data) == {"ids": ["ARXIV:2401.01234"]}
            return _Response(
                [
                    {
                        "title": expected["title"],
                        "year": 2024,
                        "venue": "Test Venue",
                        "externalIds": {
                            "ArXiv": "2401.01234",
                            "DOI": "10.1000/example",
                        },
                    }
                ]
            )
        if url.startswith(verifier.OPENALEX_WORKS_API):
            assert request.get_header("Accept") == "application/json"
            if openalex_payload is not None:
                return _Response(openalex_payload)
            identifier = unquote(url.split("/works/", 1)[1].split("?", 1)[0])
            lookup_doi = identifier.removeprefix("doi:")
            return _Response(
                {
                    "id": "https://openalex.org/W123",
                    "doi": "https://doi.org/" + (openalex_doi or lookup_doi),
                    "display_name": openalex_title or expected["title"],
                    "publication_year": 2024,
                }
            )
        raise AssertionError(url)

    monkeypatch.setattr(verifier, "urlopen", fake_urlopen)


def test_four_independent_catalog_matches_verify_exact_title(monkeypatch):
    _install_catalog_responses(monkeypatch)

    result = verifier.verify_records([_candidate()], crossref_delay=0)

    paper = result["papers"][0]
    assert result["verdict"] == "PASS"
    assert paper["status"] == "verified"
    assert paper["method"] == ["arxiv", "crossref", "semantic_scholar", "openalex"]
    assert paper["checks"]["arxiv"]["id"].endswith("2401.01234v2")


def test_conflicting_catalog_title_prevents_verification(monkeypatch):
    _install_catalog_responses(monkeypatch, crossref_title="A Different Paper")

    result = verifier.verify_records([_candidate()], crossref_delay=0)

    paper = result["papers"][0]
    assert result["verdict"] == "WARN"
    assert paper["status"] == "unverified"
    assert paper["checks"]["crossref"]["status"] == "mismatch"


def test_openalex_identifier_mismatch_prevents_verification(monkeypatch):
    _install_catalog_responses(monkeypatch, openalex_doi="10.9999/wrong")

    result = verifier.verify_records([_candidate()], crossref_delay=0, openalex_delay=0)

    paper = result["papers"][0]
    assert paper["status"] == "unverified"
    assert paper["checks"]["openalex"]["status"] == "mismatch"


def test_openalex_title_mismatch_prevents_verification(monkeypatch):
    _install_catalog_responses(monkeypatch, openalex_title="A Different Paper")

    result = verifier.verify_records([_candidate()], crossref_delay=0, openalex_delay=0)

    paper = result["papers"][0]
    assert paper["status"] == "unverified"
    assert paper["checks"]["openalex"]["status"] == "mismatch"


def test_malformed_openalex_response_is_an_error_not_a_catalog_miss(monkeypatch):
    _install_catalog_responses(monkeypatch, openalex_payload=[])

    result = verifier.verify_records([_candidate()], crossref_delay=0, openalex_delay=0)

    paper = result["papers"][0]
    assert paper["status"] == "verified"
    assert paper["checks"]["openalex"]["status"] == "error"


def test_transient_catalog_outage_is_pending_not_a_pass(monkeypatch):
    _install_catalog_responses(monkeypatch, fail=True)

    result = verifier.verify_records([_candidate()], crossref_delay=0)

    assert result["verdict"] == "WARN"
    assert result["papers"][0]["status"] == "verify_pending"
    assert all(
        check["status"] == "error" for check in result["papers"][0]["checks"].values()
    )


def test_no_doi_candidate_uses_exact_crossref_title_match(monkeypatch):
    candidate = _candidate()
    candidate.pop("doi")

    def fake_urlopen(request, timeout):
        if request.full_url.startswith(verifier.ARXIV_API):
            return _Response(
                b'<feed xmlns="http://www.w3.org/2005/Atom">'
                b"<entry><id>https://arxiv.org/abs/2401.01234</id>"
                b"<title>A Sample Paper: Exact Metadata</title></entry></feed>"
            )
        if request.full_url.startswith(verifier.CROSSREF_API):
            assert "query.title=" in request.full_url
            return _Response(
                {
                    "message": {
                        "items": [
                            {"DOI": "10.2000/unrelated", "title": ["Unrelated Paper"]},
                            {"DOI": "10.1000/example", "title": [candidate["title"]]},
                        ]
                    }
                }
            )
        if request.full_url.startswith(verifier.S2_BATCH_API):
            assert json.loads(request.data) == {"ids": ["ARXIV:2401.01234"]}
            return _Response(
                [
                    {
                        "title": candidate["title"],
                        "year": 2024,
                        "venue": "Test Venue",
                        "externalIds": {"ArXiv": "2401.01234"},
                    }
                ]
            )
        if request.full_url.startswith(verifier.OPENALEX_WORKS_API):
            identifier = unquote(request.full_url.split("/works/", 1)[1].split("?", 1)[0])
            lookup_doi = identifier.removeprefix("doi:")
            return _Response(
                {
                    "id": "https://openalex.org/W123",
                    "doi": "https://doi.org/" + lookup_doi,
                    "display_name": candidate["title"],
                    "publication_year": 2024,
                }
            )
        raise AssertionError(request.full_url)

    monkeypatch.setattr(verifier, "urlopen", fake_urlopen)
    result = verifier.verify_records([candidate], crossref_delay=0)

    assert result["papers"][0]["status"] == "verified"
    assert result["papers"][0]["checks"]["crossref"]["doi"] == "10.1000/example"
    assert result["papers"][0]["checks"]["openalex"]["lookup_doi"] == (
        "10.48550/arxiv.2401.01234"
    )


def test_no_exact_crossref_search_result_is_not_a_title_conflict(monkeypatch):
    candidate = _candidate()
    candidate.pop("doi")

    def fake_urlopen(request, timeout):
        if request.full_url.startswith(verifier.ARXIV_API):
            return _Response(
                b'<feed xmlns="http://www.w3.org/2005/Atom">'
                b"<entry><id>https://arxiv.org/abs/2401.01234</id>"
                b"<title>A Sample Paper: Exact Metadata</title></entry></feed>"
            )
        if request.full_url.startswith(verifier.CROSSREF_API):
            return _Response(
                {
                    "message": {
                        "items": [
                            {
                                "DOI": "10.2000/unrelated",
                                "title": ["Unrelated Search Result"],
                            }
                        ]
                    }
                }
            )
        if request.full_url.startswith(verifier.S2_BATCH_API):
            return _Response(
                [
                    {
                        "title": candidate["title"],
                        "year": 2024,
                        "venue": "Test Venue",
                        "externalIds": {"ArXiv": "2401.01234"},
                    }
                ]
            )
        if request.full_url.startswith(verifier.OPENALEX_WORKS_API):
            identifier = unquote(request.full_url.split("/works/", 1)[1].split("?", 1)[0])
            lookup_doi = identifier.removeprefix("doi:")
            return _Response(
                {
                    "id": "https://openalex.org/W123",
                    "doi": "https://doi.org/" + lookup_doi,
                    "display_name": candidate["title"],
                    "publication_year": 2024,
                }
            )
        raise AssertionError(request.full_url)

    monkeypatch.setattr(verifier, "urlopen", fake_urlopen)
    result = verifier.verify_records([candidate], crossref_delay=0)

    paper = result["papers"][0]
    assert paper["status"] == "verified"
    assert paper["checks"]["crossref"]["status"] == "not_found"


def test_doi_only_candidate_uses_doi_directories(monkeypatch):
    candidate = _candidate()
    candidate.pop("arxiv_id")

    def fake_urlopen(request, timeout):
        if request.full_url.startswith(verifier.CROSSREF_API):
            assert request.full_url.endswith("10.1000%2Fexample")
            return _Response(
                {"message": {"DOI": "10.1000/example", "title": [candidate["title"]]}}
            )
        if request.full_url.startswith(verifier.S2_BATCH_API):
            assert json.loads(request.data) == {"ids": ["DOI:10.1000/example"]}
            return _Response(
                [
                    {
                        "title": candidate["title"],
                        "year": 2024,
                        "venue": "Test Venue",
                        "externalIds": {"DOI": "10.1000/example"},
                    }
                ]
            )
        if request.full_url.startswith(verifier.OPENALEX_WORKS_API):
            identifier = unquote(request.full_url.split("/works/", 1)[1].split("?", 1)[0])
            lookup_doi = identifier.removeprefix("doi:")
            return _Response(
                {
                    "id": "https://openalex.org/W123",
                    "doi": "https://doi.org/" + lookup_doi,
                    "display_name": candidate["title"],
                    "publication_year": 2024,
                }
            )
        raise AssertionError(request.full_url)

    monkeypatch.setattr(verifier, "urlopen", fake_urlopen)
    result = verifier.verify_records([candidate], crossref_delay=0)

    paper = result["papers"][0]
    assert paper["status"] == "verified"
    assert paper["checks"]["arxiv"]["status"] == "not_applicable"


def test_input_without_stable_identifier_is_rejected():
    with pytest.raises(ValueError, match="arXiv ID or DOI"):
        verifier.verify_records(
            [{"title": "Paper without identifier"}], crossref_delay=0
        )
