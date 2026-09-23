import json

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


def _install_catalog_responses(monkeypatch, *, crossref_title=None, fail=False):
    expected = _candidate()
    title = crossref_title or expected["title"]

    def fake_urlopen(request, timeout):
        assert timeout > 0
        url = request.full_url
        if fail:
            raise OSError("temporary catalog outage")
        if url.startswith(verifier.ARXIV_API):
            assert request.get_header("Accept") == "application/atom+xml"
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
        raise AssertionError(url)

    monkeypatch.setattr(verifier, "urlopen", fake_urlopen)


def test_three_independent_catalog_matches_verify_exact_title(monkeypatch):
    _install_catalog_responses(monkeypatch)

    result = verifier.verify_records([_candidate()], crossref_delay=0)

    paper = result["papers"][0]
    assert result["verdict"] == "PASS"
    assert paper["status"] == "verified"
    assert paper["method"] == ["arxiv", "crossref", "semantic_scholar"]
    assert paper["checks"]["arxiv"]["id"].endswith("2401.01234v2")


def test_conflicting_catalog_title_prevents_verification(monkeypatch):
    _install_catalog_responses(monkeypatch, crossref_title="A Different Paper")

    result = verifier.verify_records([_candidate()], crossref_delay=0)

    paper = result["papers"][0]
    assert result["verdict"] == "WARN"
    assert paper["status"] == "unverified"
    assert paper["checks"]["crossref"]["status"] == "mismatch"


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
        raise AssertionError(request.full_url)

    monkeypatch.setattr(verifier, "urlopen", fake_urlopen)
    result = verifier.verify_records([candidate], crossref_delay=0)

    assert result["papers"][0]["status"] == "verified"
    assert result["papers"][0]["checks"]["crossref"]["doi"] == "10.1000/example"


def test_doi_only_candidate_uses_crossref_and_s2(monkeypatch):
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
