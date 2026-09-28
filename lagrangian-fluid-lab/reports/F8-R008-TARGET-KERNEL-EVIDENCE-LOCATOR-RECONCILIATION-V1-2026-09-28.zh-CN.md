# F8/R008 target-kernel evidence locator/reconciliation V1

状态：`diagnostic_only_target_kernel_locator_reconciliation_blocked`。

本模块只消费既有 bounded JSON reports，并列出可绑定 artifact、缺失 pin 与 identity/runtime blocker；它不跟随 external artifact path，不启动或控制任何 workload，也不修改 PLAN、registry、ledger、denominator、gate 或 completion。

## External binding

- external manifest：`external/f8-r008-target-kernel-evidence-manifest-v1.json`
- binding state：`blocked_missing_or_incomplete_external_target_evidence`
- complete：`False`
- verified artifact roles：`无`
- missing pins：`kernel_release, source_commit, source_tree, uapi, config, build_id`

若未来 target-kernel intake 已验证 source/UAPI/config/build 四类 external artifact 且六个 pin 全部为 true，本报告会将 external binding 标为 closed；这不等于 readiness 或 T1。

## Artifact candidates

- `external_target_evidence_manifest`：`reported_missing`，path=`external/f8-r008-target-kernel-evidence-manifest-v1.json`；the existing intake report says the external manifest is missing; no arbitrary search was performed
- `external_source_artifact`：`not_referenced_by_blocked_intake`，path=`None`；verified by the target-kernel intake report; locator does not follow the artifact path
- `external_uapi_artifact`：`not_referenced_by_blocked_intake`，path=`None`；verified by the target-kernel intake report; locator does not follow the artifact path
- `external_config_artifact`：`not_referenced_by_blocked_intake`，path=`None`；verified by the target-kernel intake report; locator does not follow the artifact path
- `external_build_artifact`：`not_referenced_by_blocked_intake`，path=`None`；verified by the target-kernel intake report; locator does not follow the artifact path
- `local_matching_boot_config`：`observed_local_config`，path=`/boot/config-6.8.0-138-generic`；matching /boot config is local host evidence only; it cannot satisfy external target config pin
- `local_matching_header_config`：`observed_local_header_config`，path=`/usr/src/linux-headers-6.8.0-138-generic/.config`；matching header .config agrees with /boot/config but remains local-only
- `local_matching_header_root`：`observed_local_header_metadata`，path=`/usr/src/linux-headers-6.8.0-138-generic`；matching header root and fixed metadata samples are not a complete authenticated source/UAPI tree
- `local_uapi_fixed_sample`：`observed_local_uapi_sample_only`，path=`/usr/src/linux-headers-6.8.0-138-generic/include/uapi`；fixed UAPI sample is present, but a sample hash is not a complete external UAPI tree pin
- `local_build_link_metadata`：`observed_local_build_link_metadata`，path=`/lib/modules/6.8.0-138-generic/build`；matching modules/build metadata identifies a header package only; it is not a kernel build identity
- `local_source_git_metadata`：`source_commit_metadata_not_observed`，path=`/usr/src/linux-headers-6.8.0-138-generic/.git`；bounded header-root source metadata does not expose an authenticated source commit or complete source-tree digest
- `local_source_marker_metadata`：`source_tree_marker_not_authenticated`，path=`/usr/src/linux-headers-6.8.0-138-generic/source`；a matching header package/source marker would still not authenticate the external target source tree

local inventory 的 `/boot/config`、matching headers 与固定 UAPI sample 只能作为本机观察，`local_candidates_are_external_pin_eligible=false`。

## Identity/runtime blockers

- `external_target_manifest_missing`（external_artifact）：The existing target-kernel intake report does not close a complete external manifest plus source/UAPI/config/build artifact set.
- `external_kernel_release_pin_missing`（identity）：Required external kernel_release pin is not verified; local observations cannot be promoted into an external target pin.
- `external_source_commit_pin_missing`（identity）：Required external source_commit pin is not verified; local observations cannot be promoted into an external target pin.
- `external_source_tree_hash_missing`（identity_hash）：Required external source_tree pin is not verified; local observations cannot be promoted into an external target pin.
- `external_complete_uapi_hash_missing`（identity_hash）：Required external uapi pin is not verified; local observations cannot be promoted into an external target pin.
- `external_config_hash_missing`（identity_hash）：Required external config pin is not verified; local observations cannot be promoted into an external target pin.
- `external_build_identity_missing`（identity）：Required external build_id pin is not verified; local observations cannot be promoted into an external target pin.
- `target_kernel_abi_runtime_conformance_missing`（runtime_identity）：No trusted evidence proves that the deployed target kernel ABI and selector/fanotify behavior conform to the R008 runtime contract.
- `target_source_callgraph_conformance_missing`（source_tree）：Static repository source reviews are not a trusted target source-to-binary or loaded-runtime callgraph proof.
- `target_kernel_runtime_identity_conformance_missing`（runtime_identity）：The loaded kernel/build/runtime identity and target-kernel runtime conformance remain unmeasured.
- `trusted_authority_identity_missing`（runtime_identity）：The trusted authority/worker/runtime identity contract is synthetic-only and does not authenticate production authority.
- `trusted_runtime_identity_missing`（runtime_identity）：The worker/runtime handoff is a synthetic contract; production runtime identity and measured loaded code are absent.

## Zero-authority boundary

- readiness / T1 / formal admission：`false`
- qualification credit：`0`
- runtime identity blockers closed：`false`
- locator 未读取 kernel image、procfs/sysfs、production BI4/HDF5/solver frame，未执行 privileged/fanotify/native/solver/worker/GPU/queue。

机器报告：[F8-R008-TARGET-KERNEL-EVIDENCE-LOCATOR-RECONCILIATION-V1-2026-09-28.json](F8-R008-TARGET-KERNEL-EVIDENCE-LOCATOR-RECONCILIATION-V1-2026-09-28.json)。
