# v0.1 trajectory and evaluation contract

Each case is one HDF5 file plus one release-manifest record. SI units are mandatory. Arrays use a padded identity axis and an explicit `valid[T,N]` mask; missing values are NaN/-1 fill values and must never be scored or interpreted as zero.

Required root attributes: `schema_version`, `case_id`, `family`, `solver`, `identity_key`, `trajectory_semantics`, `world_frame`, `time_units`, `length_units`, `mass_units`. Required datasets: `time[T]`, `particle_id[N]`, `particle_zone[N]`, `valid[T,N]`, `position[T,N,3]`, `velocity[T,N,3]`, `density[T,N]`, `pressure[T,N]`, `mass[T,N]`, `type[T,N]`, `mk[T,N]`. Time must be finite and strictly increasing. Values under `valid` must be finite.

For the fixed-resolution closed-domain core, `(particle_zone, particle_id)` is numerical identity and zone is normally zero. Material truth is stored separately under `material/`: immutable tracer ID, initial source label, represented initial-mass weight, position and a cumulative valid mask. `material/mass_weight[K]` must be finite, nonnegative and sum to the represented initial fluid mass; material fractions use these weights rather than tracer counts. Solver particles must not be relabelled as material tracers merely because their IDs persist.

Independent tracers disclose four separate controls: fluid spatial resolution, saved velocity cadence, tracer integration substeps and tracer count/selection. A nearest-sample or support-radius check measures coverage only; it is not sufficient evidence of interpolation accuracy. Boundary-bearing cases additionally provide finite world/body-frame triangle sidecars and a time-dependent visibility rule so interpolation cannot cross solid walls. Visibility is recomputed at every integration substep—initial connectivity is never frozen—and attempted wall crossings invalidate the affected trajectory. A material target without these boundary sidecars remains a candidate even when its support-distance gate passes.

Moving geometry uses `control/<name>_world_from_body[T,4,4]`, a proper rigid transform. Region specifications explicitly state `world` or a named body frame. All destinations plus `in_domain_unclassified` and `numerical_loss` must close against initial mass; surviving mass must not be renormalized to one.

Each manifest record separates five causal namespaces: `physics`, `geometry`, `control`, `numerics`, and `observation`. Split assignment is inherited by the full `lineage_group_id`, including time windows, alternate output cadence, resolutions, numerical formulations and derived tracer products.

Evaluation has four tracks defined in `benchmark-tasks.json`. Particle rollout and material transport are not interchangeable. External probe/body metrics are only scored within their declared `validation_scope`; visually plausible unvalidated pressure is not ground truth.

Every submission must disclose conditioning length, rollout horizon, parameter count, training/inference wall time, peak accelerator memory, hardware and all random seeds. Autonomous rollout means predictions, not reference states, feed subsequent scored steps.
