# F7 fresh073 typed-completion adapter

This F7-only package is a metadata adapter for the 16 disabled fresh072
full601 requests. It consumes a Root142 typed conversion receipt and its
producer `conversion-report.json`, then writes new **disabled** actual-bound
XMF and Root023 render requests into a caller-selected staging directory.

The adapter requires, before it writes a downstream binding:

- typed receipt `status=completed` and `returncode=0`;
- conversion report `conversion_status=completed`, schema
  `ds-data-02.bi4-direct-conversion.v1`, `frames=601`, `particles=70179`;
- producer `output_hdf5` path exists and producer `output_sha256` is a
  64-character digest. The adapter records that digest without opening or
  hashing H5;
- `hash_scopes.physical_condition.schema` is
  `ds-data-02.physical-binding.v1`, its producer physical hash equals the
  canonical owner hash, and the source-plan hash remains recorded separately;
- `partvtk_validation.all_passed=true`;
- the actual Root313 native receipt exists and remains `completed/0`.

The AST review found that the fresh072 XMF binding snapshot did not carry the
`physical_condition_sha256` key that `export_xmf.py` indexes directly. The
fresh073 binding adds that key from the producer physical scope and also keeps
the canonical owner hash and source-plan hash as separate fields.

It binds the actual typed receipt, conversion report, H5 path/digest, native
receipt, producer scope schema, and producer physical hash. It also replaces
the old `/usr/bin/python3.10` request interpreter with the integration
worktree's `.venv/bin/python`. XMF and rendering output hashes remain null,
requests remain disabled, and output directories remain independent
`{attempt_root}/xdmf` and `{attempt_root}/render` children.

The adapter hashes only JSON/source/binary metadata inputs needed for strict
request closure. The H5 digest is adopted from the producer report and is
marked `producer_attested`; no BI4, CSV, H5, or motion payload is read or
hashed by this package. No solver, converter, XMF, renderer, ledger, or
shared registry is started or modified.

Static contract review:

```text
python scripts/preflight_fresh073.py --source-package \
  lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_072_stage1_actualQA310_full601_typed_xmf_render_v1
```

After Root has a real typed receipt and report, produce one disabled actual
binding set with:

```text
python scripts/bind_actual_typed_fresh073.py \
  --source-package <fresh072-package> \
  --case-id F7_OBSTACLE_QUINTIC_B08_A031 \
  --typed-receipt <actual-typed>/execution-receipt.json \
  --conversion-report <actual-typed>/conversion-report.json \
  --output-dir /tmp/ds02-f7-fresh073-actual-bound
```

The same command accepts `--case-map <JSON>` for all 16 cases. The output is
still disabled and is intended for Root's strict review and later launch.
