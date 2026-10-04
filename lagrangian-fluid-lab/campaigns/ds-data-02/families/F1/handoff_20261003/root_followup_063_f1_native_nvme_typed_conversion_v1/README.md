# F1 Stage 1 native to NVMe typed conversion handoff

This fresh063 package prepares Root reviewable, disabled CPU conversion requests for the two completed Root094 native visual outputs:

- `F1_STAGE1_ECC_H130_DP010`: `dp=0.01`, `[0,1.6] s`, `161` native frames, physical hash `16ba07faf7b61f7d97f4bfc9d88a315293292107f1390ca860c15825a3bdb36e`.
- `F1_STAGE1_DUAL_H260_DP020`: `dp=0.02`, `[0,4.0] s`, `401` native frames, physical hash `238906071b2bc9742a66966ea707ae2d0de0fd0029c204c29636f415bc4a551c`.

The owners copy the exact Root094 `physical_binding` and bind EOS constants, actual 3-D GenCase counts, QA031 type/UID semantics, and the completed 092 worker mass observations. ECC is `136276/34840`, native fluid mass `34.84 kg`, worker weight `0.001 kg`; DUAL is `120316/32500`, native fluid mass `260.000013 kg`, worker weight `0.0080000004 kg`, difference `1.3000000024021574e-05 kg`. Both retain native MassFluid with `mass_rescaling=false`.

The requests reuse the successful typed040 `ds_data02_nvme_convert_v1.py` command, including NVMe staging, direct typed conversion, full native timeline, and PartVTK validation. The conversion argv contains no mDBC option; the completed solver recipe is provenance only. Requests have `launch_allowed=false`, `execution_allowed=false`, and `source_only=true` until Root enables a reviewed actual conversion.

`build_f1_stage1_nvme_typed_requests.py` validates Root094/058/059 physical hash closure and existing completed receipts, then emits the owners, requests, and manifest. It only reads JSON/text metadata and hashes ordinary provenance files. It does not open or hash `Part_*.bi4`, does not run a solver/converter, and does not modify shared index or ledger.
