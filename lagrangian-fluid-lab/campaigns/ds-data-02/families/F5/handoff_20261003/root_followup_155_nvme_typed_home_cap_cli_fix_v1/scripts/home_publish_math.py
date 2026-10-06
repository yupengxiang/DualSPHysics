"""Pure Home-publish boundary math for the fresh154 wrapper."""
from __future__ import annotations
import json

class HomePublishGuardError(RuntimeError):
    pass

def serialized_json_bytes(value) -> int:
    return len((json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"))

def planned_publish_bytes(h5_bytes: int, report_bytes: int) -> int:
    if h5_bytes < 0 or report_bytes < 0:
        raise ValueError("publish byte sizes must be non-negative")
    return int(h5_bytes) + int(report_bytes)

def other_reserved_storage_bytes(ledger: dict, current_attempt_id: str | None = None) -> int:
    total = 0
    for row in ledger.get("reservations", []):
        if current_attempt_id and row.get("id") == current_attempt_id:
            continue
        total += int(row.get("new_storage_bytes", 0))
    return total

def evaluate_publish(*, h5_bytes: int, report_bytes: int, cap_bytes: int,
                     home_free_bytes: int, home_floor_bytes: int,
                     other_reserved_bytes: int, headroom_bytes: int) -> dict:
    total = planned_publish_bytes(h5_bytes, report_bytes)
    if total > cap_bytes:
        raise HomePublishGuardError(
            f"Home publish cap exceeded: {total} > {cap_bytes} bytes")
    remaining = home_free_bytes - other_reserved_bytes - total - headroom_bytes
    if remaining < home_floor_bytes:
        raise HomePublishGuardError(
            "Home floor would be crossed: "
            f"free={home_free_bytes} other_reserved={other_reserved_bytes} "
            f"publish={total} headroom={headroom_bytes} floor={home_floor_bytes}")
    return {
        "planned_publish_bytes": total,
        "home_free_bytes": int(home_free_bytes),
        "home_floor_bytes": int(home_floor_bytes),
        "other_reserved_storage_bytes": int(other_reserved_bytes),
        "headroom_bytes": int(headroom_bytes),
        "remaining_after_publish_and_reservations": int(remaining),
        "cap_bytes": int(cap_bytes),
    }
