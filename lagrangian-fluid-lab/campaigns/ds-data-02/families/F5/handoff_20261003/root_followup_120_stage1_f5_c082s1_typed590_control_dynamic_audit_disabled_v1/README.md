# F5 fresh120: typed590 control/state diagnostic (disabled)

This package is a source-only, metadata-bound follow-up for the actual A080/A120
full16s/801 typed products. It does not contain H5, DAT, BI4, CSV or VTK payloads.
The two Root142 CPU requests remain disabled until the primary agent explicitly
reviews and registers them.

The source XML binds object `ref="10"` to predefined motion `id="1"`, with
`start=0`, `finish=16`, `duration=16`, `fieldtime=0`, and `fieldx=1`. Existing
Root370 metadata measured 641 control rows, moving-particle displacement, and a
7.282415375104486e-09 m moving/control error for an earlier typed trajectory.
That is evidence that the control path can be applied, but it is not substituted
for the actual typed590 measurement. Root371 and the current Root590 bed review
remain diagnostic-only; visible wave/runup acceptance stays WAIT.

When enabled by Root, `workers/typed590_control_dynamic_audit.py` reads the
producer-attested typed590 H5 and transformed motion table and reports all 801
saved states plus focus frames 0, 97, 153, 219, 400, 718 and 800. It measures
moving center position/velocity, control residual, fluid velocity, UID/type/
finite identity, and a source Mk50 footprint surface extent proxy. It does not
alter data, resample, change thresholds, grant precision/Q-N, or create case
credit.

Future audit report hashes are null. Fullnative and new 24s/1201 conditions stay
WAIT for Root635 full visual and actual mechanism review.
