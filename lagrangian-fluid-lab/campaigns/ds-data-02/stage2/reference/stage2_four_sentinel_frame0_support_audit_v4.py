#!/usr/bin/env python3
"""Thin ROOT314 entry point over the frozen frame-zero worker.

The consumed V2 worker owns the manifest and report schemas and the complete
per-case diagnostic implementation.  This additive entry point deliberately
does not copy or reinterpret that implementation: it calls ``V2.run``
directly and only changes process completion semantics.  A completed report
may contain PASS and FAILED rows, because a failed sentinel is retained as a
diagnostic result; malformed manifests, missing inputs, and output/write
errors remain process failures.  No scientific credit is assigned.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
V2_PATH = HERE / "stage2_four_sentinel_frame0_support_audit_v2.py"
V2_SPEC = importlib.util.spec_from_file_location("stage2_four_sentinel_frame0_support_audit_v2_for_v4", V2_PATH)
if V2_SPEC is None or V2_SPEC.loader is None:
    raise RuntimeError(f"cannot load frozen frame-zero worker: {V2_PATH}")
V2 = importlib.util.module_from_spec(V2_SPEC)
V2_SPEC.loader.exec_module(V2)

SCHEMA = V2.SCHEMA
MANIFEST_SCHEMA = V2.MANIFEST_SCHEMA
CASES = V2.CASES


class AuditV4Failure(RuntimeError):
    """A malformed request or an incomplete report, distinct from case failure."""


def run(manifest_path: Path, attempt_root: Path, output: Path) -> dict[str, Any]:
    """Run the unchanged V2 implementation and preserve its V2 report bytes.

    ``V2.run`` catches per-case decoder/support exceptions and records them in
    the report.  Only errors that prevent a report from being completed escape
    as exceptions here.  The returned value is checked for the original V2
    shape so a future incompatible worker cannot silently pass this adapter.
    """

    value = V2.run(Path(manifest_path), Path(attempt_root), Path(output))
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise AuditV4Failure("frozen V2 worker did not return its V2 report schema")
    rows = value.get("cases")
    counts = value.get("case_counts")
    if not isinstance(rows, list) or len(rows) != len(CASES):
        raise AuditV4Failure("frozen V2 worker returned an incomplete case report")
    if not isinstance(counts, dict) or any(int(counts.get(name, -1)) < 0 for name in ("PASS", "FAILED")):
        raise AuditV4Failure("frozen V2 worker returned invalid case counts")
    if not Path(output).expanduser().absolute().is_file():
        raise AuditV4Failure("frozen V2 worker did not create its report")
    return value


def _write_decoder_that_fails_one_case(decoder: Path, sentinel: str) -> None:
    """Mutate only the manufactured decoder, making one real subprocess fail."""

    decoder.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, struct, sys\n"
        "frame = pathlib.Path(sys.argv[1])\n"
        "prefix = pathlib.Path(sys.argv[2])\n"
        f"if {sentinel!r} in str(frame):\n"
        "    raise SystemExit(17)\n"
        "data = prefix / 'particles'\n"
        "data.mkdir(parents=True, exist_ok=True)\n"
        "(prefix.with_suffix('.xml')).write_text('<root><item><double name=\"Npiece\" v=\"1\"/><double name=\"Piece\" v=\"0\"/><double name=\"NpDynamic\" v=\"0\"/><double name=\"ReuseIds\" v=\"0\"/><double name=\"PeriMode\" v=\"0\"/><item name=\"particles\"><double name=\"TimeStep\" v=\"0\"/></item></item></root>')\n"
        "data.joinpath('Idp.bin').write_bytes(struct.pack('<4I', 0, 1, 2, 3))\n"
        "data.joinpath('Posd.bin').write_bytes(struct.pack('<12d', 0.1, 0.1, 0.1, 0.25, 0.25, 0.25, 0.75, 0.75, 0.75, 0.5, 0.5, 1.0))\n"
        "if not frame.is_file():\n"
        "    raise SystemExit(3)\n",
        encoding="utf-8",
    )
    decoder.chmod(0o755)


def self_test() -> None:
    """Exercise the actual V2 CLI path and the consumed V5 verifier.

    The fixture is made by the existing V2 verifier helper.  The only
    mutation is its tiny decoder, which exits nonzero for F4-S2; the report is
    then produced by this module's subprocess CLI and consumed by V5.  No
    report row is manufactured or edited.
    """

    verifier_spec = importlib.util.spec_from_file_location(
        "stage2_four_sentinel_frame0_support_verify_v5_for_audit_v4",
        HERE / "stage2_four_sentinel_frame0_support_verify_v5.py",
    )
    if verifier_spec is None or verifier_spec.loader is None:
        raise AuditV4Failure("cannot load consumed ROOT314 V5 verifier")
    verifier = importlib.util.module_from_spec(verifier_spec)
    verifier_spec.loader.exec_module(verifier)

    with tempfile.TemporaryDirectory(prefix="root314-audit-v4-") as directory:
        root = Path(directory)
        manifest, attempt, output = verifier.V2._fixture_manifest(root)
        decoder = Path(json.loads(manifest.read_text(encoding="utf-8"))["cases"][0]["decoder"]["path"])
        _write_decoder_that_fails_one_case(decoder, "F4-S2")

        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--run",
            "--manifest",
            str(manifest),
            "--attempt-root",
            str(attempt),
            "--output",
            str(output),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise AssertionError(f"mixed V2 diagnostic was rejected: {completed.stdout}\n{completed.stderr}")
        report = json.loads(output.read_text(encoding="utf-8"))
        assert report["schema"] == SCHEMA
        assert report["case_counts"] == {"PASS": 3, "FAILED": 1}
        failed = [row for row in report["cases"] if row["sentinel_id"] == "F4-S2"]
        assert len(failed) == 1 and failed[0]["status"].startswith("FAILED")
        checked = verifier.verify(manifest, output)
        assert checked["case_counts"] == {"PASS": 3, "UNKNOWN": 0, "FAILED": 1}
        assert checked["scientific_qualification"]["credit"] == 0

        # A global manifest error cannot be downgraded to a completed report.
        malformed = root / "malformed-manifest.json"
        malformed.write_text("{}\n", encoding="utf-8")
        bad_output = root / "malformed-output.json"
        bad = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--run",
                "--manifest",
                str(malformed),
                "--attempt-root",
                str(root / "bad-attempt"),
                "--output",
                str(bad_output),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert bad.returncode != 0
        assert not bad_output.exists()

    print("PASS_FOUR_SENTINEL_FRAME0_SUPPORT_AUDIT_V4_THIN_V2_MIXED_CLI_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--attempt-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        try:
            self_test()
        except Exception as exc:
            print(f"FAILED_FOUR_SENTINEL_FRAME0_SUPPORT_AUDIT_V4_SELFTEST: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.manifest is None or args.attempt_root is None or args.output is None:
        parser.error("--run requires --manifest, --attempt-root, --output")
    try:
        value = run(args.manifest, args.attempt_root, args.output)
    except Exception as exc:
        print(f"FAILED_FOUR_SENTINEL_FRAME0_SUPPORT_AUDIT_V4: {exc}", file=sys.stderr)
        return 2
    # A report with per-case FAILED/UNKNOWN rows is still a completed
    # diagnostic.  Only the exception path above is a failed parent task.
    print(json.dumps({"status": value["status"], "output": str(args.output.absolute()),
                      "case_counts": value["case_counts"], "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
