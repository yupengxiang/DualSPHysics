# F2 fresh092 native109 NVME typed handoff

This source-only handoff binds actual GenCase101, QA107, and solver109 metadata for
P01 and P03. Each native cohort is 418104 total particles: 372840 fixed, 24150
moving, and 21114 Type=3 fluid particles in 3-D. Native fluid mass is 21.114 kg.
The source continuum envelope is 18.876 kg; it is reported separately and never
used to rescale native mass. UID, Type/Mk, EOS, and native MassFluid/MassBound stay
native.

The source090 endpoint geometry is retained exactly and differs from the accepted
mother geometry. The mother is support only; its historical typed conversion had
118 missing fluid UIDs with unknown fate. No new lost-zero assumption is made.
The source physical-condition hash and canonical physical-binding hash are separate.

Both NVME requests are disabled. They use the unchanged direct converter through
ds_data02_nvme_convert_v1.py, /tmp/ds02-nvme-conversion, a 24 GiB peak, a 100 GiB
free-space floor, concurrency 2, and PartVTK validation at frames 0, 200, and 400.
No converter, solver, PartVTK, GPU, or array read was performed by this handoff.

Run only the JSON/XML/hash helper for source validation:
    python3 scripts/bind_f2_native109_nvme.py --mode static --case all

Bind mode writes JSON-only pending-conversion sidecars and never opens arrays.
