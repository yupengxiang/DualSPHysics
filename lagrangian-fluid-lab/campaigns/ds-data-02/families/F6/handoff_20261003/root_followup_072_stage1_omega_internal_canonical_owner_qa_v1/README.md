F6 fresh072: five internal omega canonical owners and disabled native QA handoff

Generated at 2026-10-04T23:16:15+00:00.

This package binds the five genuine Root120/GenCase069 direct-root outputs:
S050=[0.04,0.06,0.03], S075=[0.06,0.09,0.045], S125=[0.10,0.15,0.075],
S150=[0.12,0.18,0.09], and S175=[0.14,0.21,0.105] rad/s. Each actual receipt is
completed with returncode 0 and the XML contract is 417505 total, 327680 fluid,
73441 fixed, 16384 floating, 3D, Mk60/type2 floating support, dp 0.025 m,
center [2.4,1.2,1.08], free six DOF, and body mass 128 kg.

The canonical physical condition hash is computed only from the Root073
physical-binding.v1 JSON with case identity and the endpoint XML angular
velocity. The source-plan condition hash is deliberately null for these
internal endpoints. Physical body mass 128 kg, native support mass 256 kg,
and masspart 0.015625 kg remain separate; no normalization is applied.

The executable handoff is qa/initial-native-qa-request.json. It is disabled,
Root-only, CPU initial-native QA, and invokes the fresh070 wrapper from the
F6 WT. Root should enable it only after reviewing qa/qa-binding.json. The
worker then performs official PartVTK typed/geometry checks into the private
DATA attempt output. It is not a result claim.

future/ contains derived disabled full241 and FloatingInfo state0 request
metadata. It does not edit fresh070 and every future solver, QA, conversion,
and state0 output hash is null. Particle V0=0 is explicitly not treated as
proof of zero angular velocity; each endpoint requires its own state0 audit.

Read policy: this source package reads bounded XML/JSON metadata and hashes
opaque GenCase files only. It does not decode BI4/H5/CSV/particle arrays and
does not launch GenCase, PartVTK, a solver, or FloatingInfo.
