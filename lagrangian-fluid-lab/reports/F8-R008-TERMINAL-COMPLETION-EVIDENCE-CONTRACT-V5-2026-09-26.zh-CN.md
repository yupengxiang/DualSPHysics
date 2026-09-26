# F8 R008 Terminal Completion Evidence Contract v5

**Status:** additive proposal only; diagnostic only; no execution, readiness, or qualification authority. Effective contract = v3 plus v4 plus these replacements. V1–V4 and review records remain immutable. No trust infrastructure, mount-seal supervisor, locale monitor, or verifier is available.

## 1. Remove trust-registry self-hashing

The registry must not contain a digest of its own payload. V3's receipt still has exactly seven dependency pins. Six are stored in the signed trust registry: source pack, build closure, output inventory, input-trace profile, supervisor profile, and runtime environment. The seventh, trust-registry pin, is stored only in the externally pinned genesis anchor and receipt; it is excluded from the registry's dependency_pins array.

The genesis anchor exact schema becomes:

~~~text
{schema,trust_root_id,registry_key_id,registry_public_key_base64,
 registry_payload_sha256,time_key_id,time_public_key_base64,
 dependency_pin_set_id,signature_base64}
~~~

registry_payload_sha256 is the SHA-256 of canonical registry JSON after removing only signature_base64. The external task policy pins both the canonical genesis-anchor digest and this registry payload digest. The registry signature authenticates its canonical payload; the externally pinned genesis digest authenticates the registry digest/key mapping. The receipt's trust_registry dependency pair must be exactly {schema_id:"core.cfd.f8.r008.supervisor_trust_registry.v1",canonical_payload_sha256:registry_payload_sha256}. The signed registry contains exactly six non-self-referential dependency records. Registry validity/revocation, trusted time, monotone external sequence state, exact canonical bytes, and signature domains remain as specified in v4.

No receipt-supplied object may update the external genesis digest, registry digest, trusted keys, or highest accepted registry sequence. Equal sequence requires equal registry payload digest; lower sequence rejects; a greater authenticated sequence is persisted by the trusted verifier before evidence is accepted.

## 2. Replace the vague output seal with a fixed Linux protocol and exact evidence

Output is created empty on a fresh tmpfs mount inside a fresh Linux mount namespace whose propagation is private and whose namespace is inaccessible to processes other than the trusted supervisor and the child process tree. The child is the sole writer cgroup. The supervisor records the namespace inode, mount ID/device, root device/inode, mount propagation, cgroup ID, and complete PID/start-tick membership. Input roots are separate read-only mounts.

After child exit, the supervisor waits for the writer cgroup to become empty, confirms every recorded descendant is reaped, closes all supervisor write-capable descriptors, then uses Linux mount_setattr with MOUNT_ATTR_RDONLY|AT_RECURSIVE on the held output mount. It verifies the same mount ID is read-only and obtains zero remaining write-capable descriptors/actors for that mount. Unsupported kernel/filesystem semantics, non-private propagation, any surviving writer, failed remount, or missing observation is reject; there is no unspecified equivalent mechanism.

Add top-level exact object output_seal and append output_seal to the v3 top-level required-key set. Its complete keys are:

~~~text
{schema,method,namespace_inode,mount_id,mount_major,mount_minor,
 propagation,filesystem,root_dev,root_ino,writer_cgroup_id,
 child_pid,child_start_ticks,process_group_id,descendants_reaped,
 writer_cgroup_empty,write_fds_before_seal,write_fds_after_seal,
 seal_monotonic_ns,read_only_after_seal,watch_start_monotonic_ns,
 watch_stop_monotonic_ns,hash_start_monotonic_ns,hash_stop_monotonic_ns,
 sealed_tree_manifest_sha256}
~~~

schema is core.cfd.f8.r008.output_seal.v1; method is linux_mount_setattr_recursive_readonly; propagation is private; filesystem is tmpfs; descendants_reaped, writer_cgroup_empty, and read_only_after_seal are exact true booleans; both write_fds_before_seal and write_fds_after_seal are exact integer zero. namespace_inode, mount_id, root_dev/root_ino, child_start_ticks, and seal/watch/hash monotonic timestamps are exact integers in 1..2^64−1 for identities and 1..2^63−1 for times; mount_major/mount_minor are exact integers in 0..2^32−1; child_pid/process_group_id are positive exact integers ≤2^31−1; writer_cgroup_id is the exact positive cgroup-v2 inode number ≤2^64−1. sealed_tree_manifest_sha256 is 64 lowercase hex. The supervisor signs this object as part of the canonical receipt payload. Its namespace/mount/cgroup observations must come from held kernel descriptors and trusted kernel interfaces, not caller fields. The child has no mount-namespace administration capability and cannot call mount, umount, or mount_setattr.

Replace the v3 termination_watch with this exact key set: {watcher_id,clock_id,watch_start_monotonic_ns,watch_stop_monotonic_ns,event_count,overflow,lost_events,events,seal_event_sequence,hash_start_monotonic_ns,hash_stop_monotonic_ns}. clock_id is CLOCK_MONOTONIC; overflow is false; lost_events is exact zero; event_count equals the array length and is bounded 1..4096. Events use the v3 exact keys {monotonic_ns,sequence,kind,path_before,path_after,actor_pid}, contiguous sequence 1..event_count, and kinds create/write/rename/unlink/seal. A seal control event occurs exactly once, has null paths, and its sequence/time/actor match output_seal; filesystem events have a valid relative output-root path in every applicable path field. Watch coverage starts before exec, is lossless, and ends after every sealed artifact is parsed and hashed. No output-tree mutation is permitted after child exit. Seal times satisfy child exit < seal < hash_start < hash_stop < watch_stop; output_seal and termination_watch times/IDs must match exactly. The sealed tree manifest lists every relative path, type, size, device/inode, link count, and SHA-256 in bytewise order. All file reads use held no-follow descriptors on the sealed mount with pre/post fstat identity equality. Any watcher gap, extra path, changed inode/size, nonzero post-seal write handle, or event after child exit rejects the attempt.

This protocol proves post-exit read stability only. It does not promise fsync, crash recovery, or power-loss durability.

## 3. Define the locale evidence wire schema

Append exact top-level object locale_attestation to the v3 required-key set. It is included in the supervisor-signed receipt payload and has exact keys:

~~~text
{schema,monitor_profile_sha256,runtime_closure_sha256,
 thread_count,threads,probe_count,probes,wrapper_event_count,
 wrapper_events,lost_events}
~~~

schema is core.cfd.f8.r008.locale_attestation.v1. Hashes are 64 lowercase hex. thread_count is 1..4096. threads is sorted by (start_monotonic_ns,tid); each exact row is {tid,start_monotonic_ns,first_probe_sequence,exit_monotonic_ns}, with tid a positive exact integer ≤2^32−1, start/exit exact monotonic integers ≤2^63−1, and first_probe_sequence a positive exact integer. probes is sorted by contiguous sequence and each exact row is {sequence,monotonic_ns,tid,phase,lc_all,lc_numeric,callsite_id}; sequence is 1..probe_count, monotonic_ns is a positive exact integer ≤2^63−1, tid is a registered thread, phase is one of definition_parse, argv_option_parse, or runparts_numeric_format, locale strings are ASCII and must both equal C, and callsite_id matches the pinned source-profile enum. There is exactly one probe immediately before Definition parse and option parse, and one probe for every source-pinned RunPARTs RealStr numeric callsite/row. Counts must match recomputation from the output and pinned source profile.

wrapper_events is sorted by contiguous sequence; each exact row is {sequence,monotonic_ns,tid,call,argument_locale,result_locale,child_tid}. Sequence is 1..wrapper_event_count, monotonic_ns is a positive exact integer ≤2^63−1, and tid is a registered thread. call is setlocale, uselocale, pthread_create, dlopen, or dlsym. Locale arguments/results are null or printable ASCII strings of 0..128 bytes; child_tid is null except for pthread_create, where it is a positive exact integer ≤2^32−1 registered before user code. The pinned link-wrapper profile captures all references to those symbols, rejects dynamic loading and symbol lookup that could bypass the wrappers, registers each new thread before its first application instruction, and probes that thread before parsing or formatting. One initial transition to C per thread is permitted; all later locale-setting calls, non-C observations, unknown threads, wrapper loss, or profile/hash mismatch reject.

monitor_profile_sha256 must match the exact monitor profile embedded in the pinned runtime_environment dependency; runtime_closure_sha256 must equal the pinned loaded-library closure. probe_count, wrapper_event_count, and lost_events are exact integers; lost_events is zero. Bounds are probe_count 1..1,000,000, wrapper_event_count 0..1,000,000, thread_count 1..4096, and each event array length equals its count. Every object has additionalProperties=false. Locale observations, wrappers, thread registration, and the whole receipt are covered by the trusted supervisor attestation. Environment variables alone are not evidence.

If the exact monitor build/profile, signed event arrays, complete thread coverage, or required probes are absent, RealStr byte-comparison remains missing/open; do not infer locale from output tokens.

## 4. Pin a complete BI4 writer/decoder profile and producer byte order

Append exact top-level object bi4_format_profile to the v3 required-key set. Its digest is also included in the pinned output_inventory dependency. Exact keys:

~~~text
{schema,source_revision,source_closure_sha256,writer_profile_sha256,
 decoder_profile_sha256,producer_byteorder,files}
~~~

schema is core.cfd.f8.r008.bi4_format_profile.v1; source_revision is the exact frozen v5.4 revision identifier; the three digests are 64 lowercase hex; producer_byteorder is little or big and equals the trusted supervisor's recorded GetByteOrder() for the producing process. files is sorted by artifact path and has one exact row per BI4 artifact: {path,role,filecode,si64,required_item_schema_sha256,required_array_schema_sha256,writer_callsite_id}. path and role must equal the output inventory; filecode is 1..49 ASCII bytes; si64 is exact integer 0 or 1 and must equal the authenticated file header; both per-file schema hashes are 64 lowercase hex; writer_callsite_id matches the pinned profile enum. Item/array schema digests bind the full closed set of names, types, byte widths, dimensions, counts, and required/optional flags for that writer callsite. Unknown BI4 items/arrays or unlisted files reject.

The common 64-byte header grammar is fixed: bytes 0..57 are ASCII '#FileJBD ' plus the complete, untruncated ASCII filecode, then ASCII spaces to byte 57; byte 58 is LF; byte 59 is NUL; byte 60 is byteorder; byte 61 is si64; bytes 62..63 are zero. Filecode length is 1..49 ASCII bytes. si64 is 0 or 1. Normalize byteorder by subtracting 10 when si64=1; result must be 0 little or 1 big and must equal producer_byteorder. Decode all multibyte BI4 content according to this per-file header. Do not assume little-endian or host order without checking the authenticated producer profile.

writer_profile_sha256 binds every source file/callsite that creates the frozen R008 output types. decoder_profile_sha256 binds the exact bounded no-follow decoder and its complete schema tables. Both closures are included by hash in the existing pinned source/build/output dependencies and supervisor profile. A generic parser name, unpinned source URL, or caller-declared schema is insufficient. Source basis: JBinaryData::MakeFileHead writes the title/header at JBinaryData.cpp:1286–1296; the reader checks byte order at :1346–1351; header field offsets are in JBinaryData.h:189.

If any required source, writer, item/array schema, decoder, producer-byteorder observation, or profile digest is not available and externally pinned before receipt verification, BI4 terminal proof is missing/open.

## 5. Unified schema and verification updates

The effective v3 top-level exact-key set is v3's full set plus output_seal, locale_attestation, and bi4_format_profile. The v3 nested schema remains exact except output_root/termination_watch and dependency_pins.trust_registry, which are replaced above. All added objects use exact types, bounds, enums, required keys, and additionalProperties=false. Canonical JSON, signature domains, bounded parsing, and path rules from v3/v4 remain unchanged.

Verification order is: strict canonical parse; externally pinned genesis digest/root signature; fresh trusted-time token and registry signature/revocation/monotone sequence; receipt signature/attempt identity; source/build/output/input/runtime pins including six non-self-referential registry dependencies; actual argv, Definition, control, initial state, DsphConfig and input-access trace; process/locale/watcher/output-seal evidence; sealed manifest and byte-stable no-follow reads; exact BI4 grammar/producer byteorder and RunPARTs/log/positive terminal-save recomputation. Any missing or failed step is missing/open and zero credit.

This revision remains a paper contract. It creates no trust infrastructure, gate, candidate admission, execution authority, T1/T2 credit, or production artifact access. R008 remains T1_numerical=false and readiness=false.

## 6. Independent review checklist

1. Is the registry self-hash cycle removed while preserving seven receipt pins and a complete external trust chain?
2. Can the exact private-tmpfs, mount_setattr, cgroup-reap, descriptor-closure, watcher, and signed seal evidence be independently verified?
3. Are locale probe/wrapper schemas and thread-creation coverage closed and sufficient for exact numeric formatting?
4. Does the BI4 profile bind the complete writer and decoder grammar, filecode, SI64 width, and producer byte order?
5. Do the v3/v4 positive-horizon, automatic DsphConfig, parser, input-trace, freshness, and zero-credit guarantees remain unchanged?

Review is read-only only; no production input, GenCase, native decoder, solver, worker, GPU, queue, or registry/ledger mutation.
