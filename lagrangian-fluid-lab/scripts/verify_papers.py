#!/usr/bin/env python3
"""Conservatively cross-check paper metadata against arXiv, Crossref, and S2.

This verifies bibliographic identity only. It does not assess paper claims,
scientific quality, or the project's novelty.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ARXIV_API = "https://export.arxiv.org/api/query"
CROSSREF_API = "https://api.crossref.org/works"
S2_BATCH_API = "https://api.semanticscholar.org/graph/v1/paper/batch"
USER_AGENT = (
    "CorePlanReferenceVerifier/1.0 (https://github.com/yupengxiang/DualSPHysics)"
)
ATOM_NS = "http://www.w3.org/2005/Atom"


def normalize_title(value: str) -> str:
    """Normalize punctuation/case while requiring every title word to match."""
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def normalize_arxiv_id(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^https?://arxiv\.org/abs/", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\.pdf$", "", value, flags=re.IGNORECASE)
    return re.sub(r"v[0-9]+$", "", value, flags=re.IGNORECASE)


def normalize_doi(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value, flags=re.IGNORECASE)
    return value.casefold()


def _request_bytes(
    url: str, *, data: bytes | None = None, timeout: float = 20
) -> bytes | None:
    accept = "application/atom+xml" if url.startswith(ARXIV_API) else "application/json"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": accept,
    }
    if url.startswith(S2_BATCH_API) and os.environ.get("S2_API_KEY"):
        headers["x-api-key"] = os.environ["S2_API_KEY"]
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as error:
        if error.code == 404:
            return None
        raise


def _request_json(url: str, *, data: bytes | None = None, timeout: float = 20):
    body = _request_bytes(url, data=data, timeout=timeout)
    if body is None:
        return None
    return json.loads(body.decode("utf-8"))


def _parse_arxiv_feed(body: bytes) -> dict[str, dict]:
    root = ET.fromstring(body)
    entries = {}
    for entry in root.findall(f"{{{ATOM_NS}}}entry"):
        raw_id = entry.findtext(f"{{{ATOM_NS}}}id", default="")
        arxiv_id = normalize_arxiv_id(raw_id.rsplit("/", 1)[-1])
        title = " ".join(entry.findtext(f"{{{ATOM_NS}}}title", default="").split())
        if arxiv_id and title:
            entries[arxiv_id] = {"title": title, "id": raw_id}
    return entries


def _fetch_arxiv(candidates: list[dict], *, timeout: float) -> dict[str, dict]:
    with_id = [item for item in candidates if item.get("arxiv_id")]
    if not with_id:
        return {}
    ids = [normalize_arxiv_id(item["arxiv_id"]) for item in with_id]
    query = urlencode({"id_list": ",".join(ids), "max_results": len(ids)})
    body = _request_bytes(f"{ARXIV_API}?{query}", timeout=timeout)
    if body is None:
        raise ValueError("arXiv API returned HTTP 404")
    return _parse_arxiv_feed(body)


def _fetch_crossref(candidate: dict, *, timeout: float) -> dict | None:
    doi = candidate.get("doi")
    if doi:
        url = f"{CROSSREF_API}/{quote(doi, safe='')}"
        payload = _request_json(url, timeout=timeout)
        return payload.get("message") if isinstance(payload, dict) else None
    query = urlencode({"query.title": candidate["title"], "rows": 5})
    payload = _request_json(f"{CROSSREF_API}?{query}", timeout=timeout)
    if not isinstance(payload, dict):
        return None
    items = payload.get("message", {}).get("items", [])
    expected = normalize_title(candidate["title"])
    return next(
        (
            item
            for item in items
            if any(
                normalize_title(title) == expected for title in item.get("title", [])
            )
        ),
        None,
    )


def _crossref_match(candidate: dict, item: dict | None) -> dict:
    if item is None:
        return {"status": "not_found"}
    titles = item.get("title", [])
    matched_title = next(
        (
            title
            for title in titles
            if normalize_title(title) == normalize_title(candidate["title"])
        ),
        None,
    )
    actual_doi = item.get("DOI")
    expected_doi = candidate.get("doi")
    doi_matches = not expected_doi or (
        actual_doi and normalize_doi(actual_doi) == normalize_doi(expected_doi)
    )
    if matched_title and doi_matches:
        return {"status": "matched", "title": matched_title, "doi": actual_doi}
    return {
        "status": "mismatch",
        "title": titles[0] if titles else None,
        "doi": actual_doi,
        "expected_doi": expected_doi,
    }


def _s2_identifier(candidate: dict) -> str:
    if candidate.get("arxiv_id"):
        return "ARXIV:" + normalize_arxiv_id(candidate["arxiv_id"])
    if candidate.get("doi"):
        return "DOI:" + candidate["doi"]
    return candidate["title"]


def _fetch_s2(candidates: list[dict], *, timeout: float) -> list[dict | None]:
    identifiers = [_s2_identifier(item) for item in candidates]
    data = json.dumps({"ids": identifiers}).encode("utf-8")
    url = S2_BATCH_API + "?" + urlencode({"fields": "title,year,venue,externalIds"})
    payload = _request_json(url, data=data, timeout=timeout)
    if not isinstance(payload, list) or len(payload) != len(candidates):
        raise ValueError("Semantic Scholar batch response did not match request length")
    return payload


def _s2_match(candidate: dict, item: dict | None) -> dict:
    if item is None:
        return {"status": "not_found"}
    title = item.get("title")
    if title and normalize_title(title) == normalize_title(candidate["title"]):
        return {
            "status": "matched",
            "title": title,
            "year": item.get("year"),
            "venue": item.get("venue"),
            "external_ids": item.get("externalIds", {}),
        }
    return {
        "status": "mismatch",
        "title": title,
        "year": item.get("year"),
        "venue": item.get("venue"),
        "external_ids": item.get("externalIds", {}),
    }


def verify_records(
    candidates: list[dict], *, timeout: float = 20, crossref_delay: float = 0.25
) -> dict:
    """Return a three-source identity audit; network errors never become passes."""
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("input must be a nonempty array of paper records")
    for index, candidate in enumerate(candidates):
        if (
            not isinstance(candidate, dict)
            or not isinstance(candidate.get("title"), str)
            or not candidate["title"].strip()
        ):
            raise ValueError(f"paper record {index} requires a nonempty title")
        if not (candidate.get("arxiv_id") or candidate.get("doi")):
            raise ValueError(f"paper record {index} requires an arXiv ID or DOI")

    try:
        arxiv_records = _fetch_arxiv(candidates, timeout=timeout)
        arxiv_error = None
    except Exception as error:  # Preserve a transient catalog failure per candidate.
        arxiv_records = {}
        arxiv_error = repr(error)

    crossref_results = []
    for index, candidate in enumerate(candidates):
        try:
            crossref_results.append(
                {
                    "status": "response",
                    "record": _fetch_crossref(candidate, timeout=timeout),
                }
            )
        except Exception as error:
            crossref_results.append({"status": "error", "error": repr(error)})
        if crossref_delay > 0 and index + 1 < len(candidates):
            time.sleep(crossref_delay)

    try:
        s2_records = _fetch_s2(candidates, timeout=timeout)
        s2_error = None
    except Exception as error:
        s2_records = [None] * len(candidates)
        s2_error = repr(error)

    papers = []
    for index, candidate in enumerate(candidates):
        if not candidate.get("arxiv_id"):
            arxiv = {"status": "not_applicable"}
        elif arxiv_error:
            arxiv = {"status": "error", "error": arxiv_error}
        else:
            record = arxiv_records.get(normalize_arxiv_id(candidate["arxiv_id"]))
            if record is None:
                arxiv = {"status": "not_found"}
            elif normalize_title(record["title"]) == normalize_title(
                candidate["title"]
            ):
                arxiv = {"status": "matched", **record}
            else:
                arxiv = {"status": "mismatch", **record}

        crossref_result = crossref_results[index]
        if crossref_result["status"] == "error":
            crossref = {"status": "error", "error": crossref_result["error"]}
        else:
            crossref = _crossref_match(candidate, crossref_result["record"])

        if s2_error:
            s2 = {"status": "error", "error": s2_error}
        else:
            s2 = _s2_match(candidate, s2_records[index])

        checks = {"arxiv": arxiv, "crossref": crossref, "semantic_scholar": s2}
        matched_sources = [
            name for name, result in checks.items() if result["status"] == "matched"
        ]
        mismatches = [
            name for name, result in checks.items() if result["status"] == "mismatch"
        ]
        transient_errors = [
            name for name, result in checks.items() if result["status"] == "error"
        ]
        if len(matched_sources) >= 2 and not mismatches:
            status = "verified"
        elif transient_errors:
            status = "verify_pending"
        else:
            status = "unverified"
        papers.append(
            {
                **candidate,
                "status": status,
                "method": matched_sources,
                "checks": checks,
                "verification_note": (
                    "exact normalized title matched in at least two catalogs"
                    if status == "verified"
                    else (
                        "one or more metadata catalogs returned conflicting titles"
                        if mismatches
                        else (
                            "transient metadata API error; retry before making a negative claim"
                            if transient_errors
                            else "fewer than two independent catalogs confirmed the exact title"
                        )
                    )
                ),
            }
        )

    return {
        "schema": "research_lit.paper_verification.v1",
        "verdict": (
            "PASS" if all(paper["status"] == "verified" for paper in papers) else "WARN"
        ),
        "method": "exact normalized title cross-check across arXiv, Crossref, and Semantic Scholar; verified requires two matches and no mismatch",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "papers": papers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=20)
    parser.add_argument("--crossref-delay-seconds", type=float, default=0.25)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive and finite")
    if (
        not math.isfinite(args.crossref_delay_seconds)
        or args.crossref_delay_seconds < 0
    ):
        parser.error("--crossref-delay-seconds must be nonnegative and finite")
    if args.output.exists() and not args.overwrite:
        parser.error(
            f"output already exists (pass --overwrite to replace): {args.output}"
        )
    candidates = json.loads(args.input.read_text(encoding="utf-8"))
    result = verify_records(
        candidates,
        timeout=args.timeout_seconds,
        crossref_delay=args.crossref_delay_seconds,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=args.output.parent,
            prefix=args.output.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(args.output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(
        json.dumps(
            {
                "verdict": result["verdict"],
                "output": str(args.output),
                "counts": {
                    status: sum(paper["status"] == status for paper in result["papers"])
                    for status in ("verified", "unverified", "verify_pending")
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
