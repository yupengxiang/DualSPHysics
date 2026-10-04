# F6 stage1 visual batch8 source handoff (fresh055)

This fresh scope narrows the F6 batch to one physical control dimension: a scalar
multiplier `s` applied to the anchored angular-velocity vector
`[0.08, 0.12, 0.06] rad/s`. The eight values are
`s = 0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 1.75, 2.00`. Every row keeps the
zero orientation, zero linear velocity, center `[2.4, 1.2, 1.08] m`, body geometry,
128 kg physical rigid mass, 256 kg native support mass, inertia, fluid, tank, native
controls, and single `dp=0.025 m` recipe unchanged.

This is a source plan only. The request is disabled and contributes zero independent
cases. The bounded builder writes scalar physical specifications only; it does not
run GenCase, copy or generate BI4, run the solver, convert H5, export CSV/arrays,
run PartVTK, or render an animation.

The actual corrected native241 source remains the sole anchor: GenCase017, native
solver021, initial QA019, semantic audit020, actual full241 body SO(3) root029, and
exact native time root030. Genuine failures and uncertainties remain visible. In
particular, GenCase particles have zero velocity and frame-0 propagation of the
declared angular velocity through the solver is still unobserved. A changed
`angularvelini` in a new XML must therefore be followed by fresh GenCase, actual
initial QA, and semantic audit. Reusing the old zero-velocity BI4 while changing
floating metadata is forbidden; BI4 bytes are never cloned blindly.

The 128 kg physical rigid mass, the 256 kg native support-weight sum, the derived
0.0078125 kg diagnostic node weight, and the 0.015625 kg solver interaction masspart
remain distinct. The historical mass QA failure, finer-half/all3DP negative evidence,
unregistered orientation budget, `q_n` uncertainty, and visual review pending are
preserved from follow-up052.
