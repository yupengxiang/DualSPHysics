# F4 fresh108: Root690 renderer request contract repair

This source-only package preserves fresh107 byte-for-byte and derives disabled Root690 renderer request candidates with the fields required by the actual Root142/runtime contract. It does not enable, launch, hash, copy, decode, or inspect BI4/H5/VTK/CSV/DAT science payloads.

The defect found in Root690's current `q.update(...)` path is concrete: it adds `kind=cpu` and `max_wall_seconds=14400`, but does not add `launch_owner`, `worktree_root`, or `estimated_storage_bytes`. Root142 rejects the first field before runtime dispatch; runtime v2 requires the latter two. The repair uses the proven Root638 render values: integration worktree root, Root-owned launch, 24 CPU threads, 12 GiB reservation, 14,400 seconds, CPU environment variables at 2, and the Root142 Home-floor profile.

Every generated request remains disabled with `launch=false`, `launch_allowed=false`, `execution_allowed=false`, null manifest/XMF/output hashes, and the Root669 placeholder paths. Root must replace placeholders only after its own completed Root669 receipt and metadata-only preflight; this package does not produce an executable request.
