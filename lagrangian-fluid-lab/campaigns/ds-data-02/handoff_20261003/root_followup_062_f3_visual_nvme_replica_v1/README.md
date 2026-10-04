# F3 Root113 visual NVMe replica source handoff (fresh062)

This package prepares a Root-only byte-preserving replica workflow for the
three observed entries in `F3_STAGE1_FIRST24_AY0250_AY0750_VISUAL_V1`. The
worker recursively discovers `path`/`sha256` bindings inside the original case
decision JSON, records opaque originals as `source_absolute_path`, and selects
only H5/GIF/native blob files at least 64 MiB. It streams each selected source
once into `/tmp/ds02-visual-evidence-cache/SHA.ext`, verifies the frozen digest while
copying, checks source stat before/after, rehashes existing cache files, and
publishes with an atomic rename. It enforces a 24 GiB cache peak and 100 GiB
free-space floor.

The package has performed no byte copy, H5 hash, decode, solver run, GPU run,
or source mutation. `replicate_visual_evidence.py` must be run only by Root.
The disabled CPU audit request then rehashes the NVMe copies without opening
the original H5 datasets. `derive_visual_scope.py` can run only after a
completed receipt and creates schema-preserving derived decisions plus a
derived scope/candidate index; it changes only proven cache paths and keeps
all physical IDs, observed results, precision labels, and case counts intact.
