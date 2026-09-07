#!/usr/bin/env python3
"""Audit destination-region specifications before enabling material tasks.

Boundary sidecars answer *where a solid surface may block interpolation*;
they do not answer which world/body-space regions count as captured, retained,
spilled, or an open-system exit.  This audit keeps those contracts separate
and makes the current zero-linked-destination state explicit.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.transport_metrics import validate_transport_spec
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from transport_metrics import validate_transport_spec


LAB = Path(__file__).resolve().parents[1]
PROTOCOL = LAB / "protocol"
EXAMPLES_PATH = PROTOCOL / "transport-region-examples.json"
SCHEMA_PATH = PROTOCOL / "transport-regions.schema.json"
RELEASE_MANIFEST = LAB / "release" / "v0.1-development" / "manifest.json"
DEFAULT_REPORT = LAB / "campaigns" / "v0.1-candidate" / "r3-g2-transport-spec-audit.json"
DEFAULT_CONCLUSION = LAB / "campaigns" / "v0.1-candidate" / "R3-G2-TRANSPORT-SPEC-CONCLUSION.md"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def audit_examples(path: Path = EXAMPLES_PATH) -> list[dict[str, Any]]:
    payload = _load(path)
    rows = []
    for name, spec in sorted(payload.items()):
        try:
            validate_transport_spec(spec)
        except (TypeError, ValueError) as exc:
            rows.append({"name": name, "valid": False, "error": str(exc)})
        else:
            rows.append({
                "name": name,
                "valid": True,
                "lifecycle_model": spec["lifecycle_model"],
                "destination_frame": spec["destination_frame"],
                "destination_count": len(spec["destinations"]),
            })
    return rows


def _sidecar_path(release_root: Path, entry: dict[str, Any]) -> Path | None:
    relative = entry.get("boundary_sidecar") or (entry.get("geometry") or {}).get("boundary_sidecar")
    if not isinstance(relative, str) or not relative:
        return None
    path = (release_root / relative).resolve()
    try:
        path.relative_to(release_root.resolve())
    except ValueError:
        return None
    return path


def audit_release(manifest_path: Path = RELEASE_MANIFEST) -> list[dict[str, Any]]:
    manifest_path = Path(manifest_path).resolve()
    release_root = manifest_path.parent
    manifest = _load(manifest_path)
    rows = []
    for entry in manifest.get("cases", []):
        spec = entry.get("destination_spec") or (entry.get("material") or {}).get("destination_spec")
        sidecar = _sidecar_path(release_root, entry)
        row: dict[str, Any] = {
            "case_id": entry.get("case_id"),
            "family": entry.get("family"),
            "destination_spec_present": spec is not None,
            "destination_spec_valid": False,
            "destination_spec_error": None,
            "boundary_sidecar_present": bool(sidecar and sidecar.is_file()),
            "wall_visibility": (entry.get("material") or {}).get("wall_visibility"),
        }
        if spec is not None:
            try:
                validate_transport_spec(spec)
            except (TypeError, ValueError) as exc:
                row["destination_spec_error"] = str(exc)
            else:
                row["destination_spec_valid"] = True
        row["t2_contract_ready"] = bool(
            row["destination_spec_valid"]
            and row["boundary_sidecar_present"]
            and row["wall_visibility"] is True
        )
        rows.append(row)
    return rows


def build_report(
    examples_path: Path = EXAMPLES_PATH,
    manifest_path: Path = RELEASE_MANIFEST,
) -> dict[str, Any]:
    examples = audit_examples(examples_path)
    cases = audit_release(manifest_path)
    linked = [row for row in cases if row["destination_spec_present"]]
    valid = [row for row in linked if row["destination_spec_valid"]]
    ready = [row for row in cases if row["t2_contract_ready"]]
    return {
        "schema_version": 1,
        "acceptance_scope": "R3 G2 destination-region contract closure",
        "schema_artifact": str(Path(SCHEMA_PATH).relative_to(LAB)),
        "examples": {
            "path": str(Path(examples_path).relative_to(LAB)) if Path(examples_path).is_relative_to(LAB) else str(examples_path),
            "count": len(examples),
            "valid_count": sum(row["valid"] for row in examples),
            "all_valid": bool(examples) and all(row["valid"] for row in examples),
            "cases": examples,
        },
        "release": {
            "manifest": str(Path(manifest_path).relative_to(LAB)) if Path(manifest_path).is_relative_to(LAB) else str(manifest_path),
            "case_count": len(cases),
            "destination_spec_linked_count": len(linked),
            "destination_spec_valid_count": len(valid),
            "boundary_sidecar_count": sum(row["boundary_sidecar_present"] for row in cases),
            "wall_visibility_true_count": sum(row["wall_visibility"] is True for row in cases),
            "t2_contract_ready_count": len(ready),
            "cases": cases,
        },
        "formal_ready": False,
        "validation_claim": "schema/runtime contract audit only; no physical destination truth is claimed",
        "open_blockers": [
            "no development-release case links a destination specification, so T2 has zero executable destination labels",
            "open-face, rim, implicit-cap, receiver, tray, and out-of-domain semantics must be declared per case",
            "wall-aware visibility must be proven together with destination geometry; a sidecar alone is insufficient",
            "destination mass closure and resolution/saved-cadence/tracer-count convergence remain unverified",
        ],
    }


def render_conclusion(report: dict[str, Any]) -> str:
    examples = report["examples"]
    release = report["release"]
    return f"""# R3 G2 结论：材料输运 destination specification 审计

状态：**candidate contract only；当前开发 release 没有任何链接的 destination specification，因此 T2 material transport 仍为 0 个可执行案例。**

## 已验证

- `transport-regions.schema.json` 现在要求显式生命周期、坐标系和至少一个 destination，并按 `aabb`、`halfspace`、`sphere` 约束几何参数。
- 运行时 validator 拒绝缺少 half-space side、零法向量、反向 AABB、非正 sphere 半径、重复名称和非显式 lifecycle/frame。
- 两个协议示例通过运行时契约检查（{examples['valid_count']}/{examples['count']}）。

## 当前 release 覆盖

| 项目 | 数量 |
|---|---:|
| release cases | {release['case_count']} |
| linked destination specs | {release['destination_spec_linked_count']} |
| valid linked specs | {release['destination_spec_valid_count']} |
| existing boundary sidecars | {release['boundary_sidecar_count']} |
| `wall_visibility=true` | {release['wall_visibility_true_count']} |
| complete T2 contract | {release['t2_contract_ready_count']} |

边界 sidecar 只说明有限三角面和候选可见性，不能替代 destination 语义。当前报告因此保留 `formal_ready=false`，没有把现有 `captured/retained/spilled` 代理分类升级成正式任务标签。

机器可读明细见 `r3-g2-transport-spec-audit.json`；协议 schema 见 `protocol/transport-regions.schema.json`。
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=RELEASE_MANIFEST)
    parser.add_argument("--examples", type=Path, default=EXAMPLES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--conclusion", type=Path, default=DEFAULT_CONCLUSION)
    args = parser.parse_args()
    report = build_report(args.examples, args.manifest)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    args.conclusion.write_text(render_conclusion(report))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
