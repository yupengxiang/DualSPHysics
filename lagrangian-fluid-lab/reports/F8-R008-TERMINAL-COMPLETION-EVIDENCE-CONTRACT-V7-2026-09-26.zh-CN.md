# F8 R008 Terminal Completion Evidence Contract v7

**Status:** additive proposal only; diagnostic-only; no solver/execution/readiness/qualification authority. Effective contract is v3 plus v4, v5, v6, and this amendment. V1–V6 and their review records remain immutable. Required trust service, Linux supervisor, audit monitor, locale monitor, and verifier are not currently deployed.

V7 addresses only the five open items from the Terra High-config V6 review. Where this amendment conflicts with an earlier version, V7 controls. All v3 source/invocation/horizon/save/initial-run rules and v4–v6 trust, scientific, zero-credit, and no-authorization restrictions remain in force.

## 1. Post-exit access: permit only verifier reads after the read-only seal

Replace V6 §§2 and 3's post-exit event rules. The watcher has three ordered phases on one `CLOCK_MONOTONIC` timeline:

1. **writer:** from before exec through the child's exit and complete descendant reap; only the frozen writer cgroup may mutate output paths.
2. **seal:** after the cgroup is empty and all writer descriptors are closed, the verifier performs the recorded recursive read-only `mount_setattr`; exactly one control event `seal` is emitted after successful read-only verification. No output-tree access by the verifier occurs before this seal event.
3. **verify:** after `seal`, the registered verifier may perform only no-follow metadata queries, directory enumeration, read-only opens, `read`/`pread64`, and `close` on paths beneath the held output-root descriptor. Every access must resolve to the sealed output mount and match the final manifest identity. `openat2` resolution must include `RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS|RESOLVE_NO_MAGICLINKS`; `openat` fallback is forbidden. Opens require `O_RDONLY|O_CLOEXEC|O_NOFOLLOW`; no writable, append, truncate, create, link, chmod, rename, unlink, mmap, or executable-open mode is permitted. Metadata calls are limited to `statx`, `fstat`, and `getdents64`; data calls are limited to `read`, `pread64`, and `close`.

The exact `termination_watch.events` union is now:

- writer events: `{sequence,monotonic_ns,kind,actor_pid,actor_start_ticks,path_before,path_after,fd,mount_id,open_flags,byte_count}`; `kind` is one of `create,write,rename,unlink,attrib,open,read,close`; non-applicable fields are null. Every path is output-root-relative and no-follow resolved. Before child exit, an event is allowed only when its actor belongs to the writer cgroup and the operation is consistent with the frozen output inventory. After child exit, any writer event or any actor other than the registered verifier is a hard reject.
- seal event: `{sequence,monotonic_ns,kind,actor_pid,actor_start_ticks,path_before,path_after,fd,mount_id,open_flags,byte_count}` with `kind=seal`, verifier identity, and all path/FD/access fields null.
- verifier events: same exact keys; `kind` is one of `statx,fstat,getdents64,open,read,pread64,close`; actor PID/start ticks equal the frozen verifier identity; paths/FDs resolve beneath the held output root and mount; open flags and byte counts obey this section. They occur strictly after seal. No extra or omitted event is allowed.

Sequence is contiguous, timestamps strictly increase, counts equal array lengths, loss/overflow are zero, and all events are emitted by the pinned monitor. The verifier events caused by the manifest/hash pass are expected and must be represented; the verifier's own reopen/read is not a forbidden mutation. All successful accesses and all denied mutation attempts are recorded. Any denied or unclassified write-capable request, non-verifier post-seal access, event gap, or watcher loss leaves evidence missing/open. The seal must precede `hash_start`, and `watch_stop > hash_stop`.

The fanotify profile is correspondingly replaced by the exact pinned union of `FAN_CREATE|FAN_DELETE|FAN_DELETE_SELF|FAN_MOVE|FAN_MODIFY|FAN_CLOSE_WRITE|FAN_ATTRIB|FAN_OPEN_PERM|FAN_OPEN_EXEC_PERM|FAN_ACCESS_PERM|FAN_OPEN|FAN_ACCESS|FAN_CLOSE_NOWRITE`, with `FAN_EVENT_ON_CHILD|FAN_ONDIR`, on the exact output mount. Every permission event is answered by the supervisor only after policy evaluation and is logged. Events are cross-linked to the syscall/FD trace by pidfd-resolved PID/start ticks, mount ID, path, operation, and monotonic time. The read-only mount is the primary mutation barrier; fanotify is an independent observation/enforcement layer. Unsupported event bits, unsupported pidfd reporting, unresolved actors, overflow, or an unbound event rejects.

## 2. Bind seal identities to raw kernel observations

Extend `output_seal_evidence` with exact required fields `cgroup_dir_stat`, `process_group_observations`, and `syscall_monitor_identity`; nested objects use `additionalProperties=false`.

- `cgroup_dir_stat` is `{fd,dev,ino,mount_id,mode,path_bytes_base64,path_sha256}` from `fstat`/`statx` of the supervisor's held cgroup-v2 directory descriptor. `ino` equals `output_seal.writer_cgroup_inode`; the same descriptor identity is used for every `cgroup.procs` and `cgroup.events` read. Path bytes are the exact kernel-visible cgroup path, strict UTF-8, and resolve to that FD without symlinks.
- Each `task_snapshot_before/after` row adds `{pgrp,session,proc_stat_base64,proc_stat_sha256}`. The raw bytes are read from `/proc/<pid>/stat` through a held proc descriptor and parsed using the pinned Linux proc-stat grammar; parsed pid, pgrp, session, and start ticks must equal the row. The child leader's pgrp at exec equals `output_seal.process_group_id`; all writer descendants have the observed expected session/process-group membership from the pinned launch profile. Any PID reuse or inaccessible row rejects.
- `syscall_monitor_identity` is `{schema,monitor_sha256,build_id,audit_arch,trace_clock,coverage_start_ns,coverage_stop_ns,trace_sequence_first,trace_sequence_last,lost_records}`. The pinned monitor records raw syscall-entry arguments and exit results for the child, descendants, supervisor, and verifier, resolving each TID to PID/start ticks. Coverage brackets exec, exit, seal, and hash-stop; sequences are contiguous and `lost_records=0`.
- Replace `mount_setattr_record` with exact `{pid,pid_start_ticks,tid,tid_start_ticks,syscall_nr,audit_arch,raw_args_base64,dirfd,dirfd_dev,dirfd_ino,dirfd_mount_id,path_bytes_base64,flags,attr_bytes_base64,attr_set,attr_clr,propagation,userns_fd,size,result,errno,trace_entry_sequence,trace_exit_sequence,monitor_sha256,monotonic_ns}`. The trace proves the actual syscall ABI and entry/exit pair. The path bytes are exactly `.` relative to the held output-root FD; `flags=AT_RECURSIVE`; the raw 32-byte native-ABI `struct mount_attr` decodes to `attr_set=MOUNT_ATTR_RDONLY`, all other attributes zero, `size=32`, `result=0`, and `errno=0`. `dirfd` identity equals the held output root and mount. This call occurs only after child cgroup empty and writer output-mount write-FD count zero, and before the `seal` event and verifier reads. `syscall_nr`, `audit_arch`, argument layout, structure byte order, and monitor build are fixed by a named, hashed host ABI profile; absence of that profile means open/missing.

The exact `process_group_id`, `writer_cgroup_inode`, `mount_setattr_record`, and `watcher_id` values in `output_seal` must be independently derivable from these signed raw records and cross-equal. A verifier-signed summary without the raw records and monitor identity is insufficient.

## 3. Close the runtime loader and process-creation monitor boundary

Add `runtime_guard` to the signed `output_seal_evidence` exact-key set. It has exact keys `{schema,loader_profile_sha256,seccomp_profile_sha256,monitor_sha256,coverage_start_ns,coverage_stop_ns,initial_image_objects,loader_entrypoints,loader_events,process_syscalls,executable_mapping_events,thread_events,lost_records}`.

`initial_image_objects` is the bytewise path-sorted complete executable/shared-object set observed at the first instruction after `execve`, each bound to device/inode, build ID, file SHA-256, mapped ranges, and dynamic symbol/version table hash. The root executable, ELF interpreter, libc, and every dependency equal the frozen source/runtime closure. No object may be added, replaced, or removed during the guarded interval.

`loader_entrypoints` is the complete bytewise-sorted set from the pinned loader/libc symbol and version tables for `dlopen`, `dlmopen`, `dlsym`, `dlvsym`, and every loader-internal alias capable of those operations; each row binds symbol, version, object hash, and entry offset. The pinned loader profile supplies the explicit closed list and hash; “wrapper-only” interposition is not sufficient. The monitor records every entry into each listed address, including calls from internal aliases, with actor/caller identity, raw arguments, result, and policy action. Any successful post-exec load or symbol-resolution call, unlisted executable object, missing entrypoint, or unobservable alias rejects. All are denied after initial-image capture.

The seccomp/trace profile denies `fork`, `vfork`, `clone3`, `execve`, and `execveat` after initial exec. Legacy `clone` is allowed only when the pinned ABI-specific mask proves `CLONE_VM|CLONE_FS|CLONE_FILES|CLONE_SIGHAND|CLONE_THREAD` are all set, `CLONE_VFORK|CLONE_PARENT|CLONE_PIDFD|CLONE_PTRACE|CLONE_UNTRACED` and namespace-creation flags are clear, and every remaining allowed flag is explicitly enumerated in the profile. Each allowed clone yields a `thread_events` row and the new TID is stopped, registered, and locale-probed before application code runs. Any process-creating clone, unregistered thread, or identity mismatch rejects. The exact syscall policy is pinned by hash and raw syscall entry/exit trace; prose or seccomp installation claims alone do not establish enforcement.

After initial-image capture, `mmap`/`mprotect`/`pkey_mprotect` operations that introduce `PROT_EXEC` are denied and recorded; executable mappings must remain exactly the frozen initial image. The process trace also denies executable `memfd`/anonymous mappings and executable opens. This runtime guard is an evidence requirement, not a claim that the monitor is deployed. If its ABI-specific closed profile, kernel enforcement, or lossless trace cannot be provided, the attempt remains missing/open and zero credit.

## 4. Represent automatic runtime configuration as an input role

In v3 `input_access.events[].role`, extend the exact enum from `{definition,control,initial_state}` to `{definition,control,initial_state,runtime_config}`. `runtime_config` is the automatically discovered `<program-directory>/DsphConfig.xml`; it is never inferred from argv. Add exact `runtime_config_probe` to `input_access`:

~~~text
{schema,program_dir_fd,program_dir_dev,program_dir_ino,program_dir_mount_id,
 probe_path,probe_operation,result,errno,statx_record,input_event_sequences,
 directory_readonly_evidence_sha256}
~~~

`schema` is `core.cfd.f8.r008.runtime_config_probe.v1`; `probe_path` is exactly `DsphConfig.xml`; `probe_operation` is `openat2`; lookup is relative to the held program-directory FD with `RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS|RESOLVE_NO_MAGICLINKS` and `O_RDONLY|O_CLOEXEC|O_NOFOLLOW`. `result` is exactly `present` or `absent`.

For `present`, `errno=0`, `statx_record` binds a regular file's device/inode/mount/size, and exactly one or more successful `runtime_config` input events bind the child’s actual open/read/mmap and full-file SHA-256 to that identity. For `absent`, `errno=ENOENT`, `statx_record=null`, and `input_event_sequences=[]`; a successful lookup/open is forbidden. In both cases, a signed supervisor mount record proves the complete program directory and ancestor resolution chain was immutable/read-only from the probe through child exit, so absence cannot be raced into presence. The probe precedes exec and its held descriptor identity matches the program path used to resolve the executable. Missing/ambiguous path, symlink, mutable directory, or conflicting event is open/missing. All other v3 input rules remain unchanged.

## 5. Bind producer byte order to each exact BI4 file write

Replace V6's single `producer_byteorder_observation` with sorted `producer_byteorder_observations`, one exact row per BI4 file in the closed output inventory. Each row is `{path,child_pid,child_start_ticks,writer_tid,writer_tid_start_ticks,executable_sha256,source_module_sha256,writer_callsite_id,getbyteorder_value,raw_probe_base64,probe_sequence,first_header_write_sequence,first_header_write_offset,first_header_write_size,monitor_sha256}`.

The row's PID/TID and start ticks resolve to the registered child writer; `executable_sha256` and `source_module_sha256` belong to the frozen closure. `writer_callsite_id` is an enum in the hashed writer-source profile and identifies the actual call site in the BI4 writer path, not a generic process-start probe. `getbyteorder_value` is the source-pinned enum `LittleEndian` (numeric 0). `raw_probe_base64` decodes to exactly four bytes from native-memory representation of uint32 value 1 and equals `01 00 00 00`. `probe_sequence < first_header_write_sequence`; the syscall monitor binds the first write of that path at offset 0, exact header size, to the same writer process and FD identity. No byte of the file may be written before its probe. Every BI4 inventory path has exactly one observation and exactly one matching first-header event; no extra observation is allowed. V6's BI4 profile per-file byte order equals this row. Any mismatch, missing callsite binding, or write-before-probe leaves BI4 proof missing/open.

## 6. Review and scope

V7 is a contract amendment awaiting independent Terra High-config review. The reviewer must receive V3, V4, V6, V7 and the relevant pinned source excerpts; findings about exact schema or inherited requirements must be checked against those full inputs. Review remains read-only: no tests/programs, production HDF5/PART/BI4/bundles, GenCase/native decoder/solver/worker/GPU/queue, or registry/ledger mutation.

No amendment here installs trust services, creates supervisor/monitor artifacts, changes any gate/registry/ledger/denominator, or grants runtime authority. F8 remains `T1_numerical=false`, readiness=false, qualification credit zero until a separate authorization and every frozen scientific gate passes.
