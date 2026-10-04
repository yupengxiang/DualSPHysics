# F5 A061 fresh068: Root129 actual XMF to disabled bed audit

This isolated handoff binds the real Root129 short-event XMF product to a
fresh disabled bed-audit request. It does not modify Root129 or fresh066 and
does not read BI4/H5/CSV arrays. The binder reads JSON/XML metadata and hashes
the immutable inputs; `workers/bed_audit.py` remains Root-owned and is the
only component that reads the particle datasets.

The actual Root129 products are closed in the generated binding and request:

- receipt `b04bc8b14db78db2d9484e5463755f86c3d49a9db699eff31ea59e414952f120`;
- manifest `f46947df8ed9bd28d33331808b0975c98205e738a259c8ae2deb2f32d5d6ed60`;
- `case.xmf` `cda1bf4f448226ebb6b2d9e2c6023ab86ff5cafdd1093cabcb7f6388d7d413de`.

The manifest and XMF contain the same 51 actual time values from `0` through
`1.000064187318789 s`; the binder preserves those values and records
`uniform_spacing_assumption: false`. The nominal `.02 s` is metadata only.
The typed H5 hash remains the manifest-provided
`bf8f8767a9f348abb269e56b46d6a4eee2781f10360ac9217733bc9837a81d31`; the
source-plan hash `268d4e…` and canonical typed hash `d4a165…` remain separate.

Root should review and enable [bed-audit-request.json](./bed-audit-request.json)
through the strict dispatcher. Its attempt is
`root-stage1-f5-short51-normal-dynamic-bed-audit-068`; output is expected
under the A061 case directory. The worker must scan all 51 saved frames,
retain the frame-zero Type-3 UID denominator, report finite/nonfinite and
missing/extra UIDs, use the exact seven-node profile and `y∈[-0.15,0.15] m`,
and report below-1DP/below-2DP counts, fractions, maximum depths, and samples.
The request is disabled, diagnostic-only, does not grant full16 or Q-N, and
does not increment the independent case count. Root will use the actual audit
metrics for the later manual full16 decision.

The source-only binder entry point is:

```text
python3 scripts/bind_root129_bed_audit.py --check
python3 scripts/bind_root129_bed_audit.py --output-dir . --force
```
