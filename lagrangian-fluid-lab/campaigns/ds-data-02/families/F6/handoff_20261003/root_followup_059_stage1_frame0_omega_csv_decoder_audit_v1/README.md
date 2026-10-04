# F6 frame-zero and first-saved angular corroboration (fresh059)

This scope prepares a Root-strict, source-only correction to the fresh056
FloatingInfo decoder.  The existing fresh056 scope and its Rootstrict048 source
receipt remain immutable.  This scope is disabled and does not launch a worker,
solver, conversion, GenCase step, or renderer.

If Root enables the request later, the worker reads the existing full241 typed
trajectory read-only for the Type2 native slice at `start=73441,count=16384` at
frame zero and the first saved frame.  It fits the measured particle velocity
field to `v = Vcm + omega x r`, reports residuals and UID coverage, and keeps
the frame-zero state separate from the first-saved state.  A frame-zero fit of
zero native particle velocity is reported as a native observation; it does not
establish that the physical rigid angular release was absent.

The FloatingInfo reader uses an explicit semicolon delimiter.  It normalizes
punctuation-bearing headers such as `fomega.x` to stable aliases, selects the
row closest to time zero and the first positive saved-time row, and marks a
row unresolved when the requested rigid vectors cannot be parsed.  This avoids
the fresh056 false `ok` status caused by treating the semicolon header as one
column.  Both selected rows remain corroboration only; the typed H5 fit is the
primary native measurement.

The worker also parses the exact native XML source.  It records the casedef and
particle floating `angularvelini=(0.08,0.12,0.06) rad/s`, physical mass 128 kg,
the initial `<move mkbound="50" x="0.0125" y="0.0125" z="-0.0075"/>`, and the
empty `<motion/>` element.  It distinguishes those rigid-body/source semantics
from direct Type2 particle velocities in the H5.  Native support mass 256 kg
versus physical mass 128 kg remains preserved, without rescaling.

The genuine initial QA failure, the H5 frame-zero result, later nonzero fitted
angular state, CSV corroboration status, and all visual/Q-N uncertainty remain
separate.  This scope makes no physics, precision, acceptance, or numerical
root-cause conclusion.

This turn inspected source XML and metadata/receipt text only.  It did not open
the typed H5, FloatingInfo CSV, BI4, pose arrays, or raw particle arrays.
