"""Synthetic-only F3 two-hop neighbour provenance/capacity diagnostic.

This module is deliberately independent of ``core_models.py`` and of any
trajectory or HDF5 input.  It models the part of the graph contract that is
relevant to the observed F3 ``graph_raw`` failure:

* a row is stored with a fixed positive neighbour ``cap``;
* the row is marked truncated when the synthetic full row exceeds that cap;
* a requested two-hop halo reads the centre row and every one-hop row; and
* truncation in any of those required rows is fail-closed.

Rows outside that required closure may remain truncated.  The result records
that state explicitly as complete for the requested diagnostic centre but not
globally complete.  Increasing a cap here is an observation in a synthetic
diagnostic, never a formal-training policy or a production configuration.

The public ``run_diagnostic`` function returns a JSON-serialisable mapping and
``main`` prints it as canonical JSON.  No production file is read or written.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Integral
from typing import Any


SCHEMA = "f3.two_hop_neighbor_provenance_diagnostic.v1"
PROVENANCE_VERSION = "synthetic.neighbor_provenance.v1"
TWO_HOP_SOURCE_RULE = "center-plus-neighbors-of-center-and-one-hop.v1"
SYNTHETIC_GRAPH_ID = "f3.synthetic.required_row_cap.v1"
DEFAULT_NEIGHBOR_CAP = 64
# A short alias is useful to callers comparing this diagnostic with the
# production default without implying that the production constant is changed.
DEFAULT_CAP = DEFAULT_NEIGHBOR_CAP

_AUTO_PROVENANCE = object()


def _flags() -> dict[str, Any]:
    """Return the non-qualification flags required on every public result."""
    return {
        "diagnostic_only": True,
        "synthetic_only": True,
        "formal_training": False,
        "T1": False,
        "native_integrity": False,
        "gate": False,
        "credit": 0,
        "formal_use_allowed": False,
        "production_artifacts_touched": False,
        "solver_started": False,
        "worker_started": False,
        "gpu_used": False,
        "queue_used": False,
    }


def _positive_integer(value: Any, name: str) -> int:
    if isinstance(value, (bool,)) or not isinstance(value, Integral) or int(value) < 1:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _integer_tuple(value: Any, name: str, *, allow_empty: bool = True) -> tuple[int, ...]:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be an integer sequence")
    try:
        values = tuple(value)
    except TypeError as error:
        raise ValueError(f"{name} must be an integer sequence") from error
    result: list[int] = []
    for item in values:
        if isinstance(item, (bool,)) or not isinstance(item, Integral):
            raise ValueError(f"{name} must contain only integers")
        result.append(int(item))
    if not allow_empty and not result:
        raise ValueError(f"{name} must not be empty")
    return tuple(result)


def _normalise_rows(rows: Any) -> tuple[tuple[int, ...], ...]:
    if isinstance(rows, (str, bytes)):
        raise ValueError("synthetic adjacency must be a sequence of rows")
    try:
        raw_rows = tuple(rows)
    except TypeError as error:
        raise ValueError("synthetic adjacency must be a sequence of rows") from error
    if not raw_rows:
        raise ValueError("synthetic adjacency must contain at least one row")

    count = len(raw_rows)
    normalised: list[tuple[int, ...]] = []
    for row_index, row in enumerate(raw_rows):
        values = _integer_tuple(row, f"adjacency row {row_index}")
        if any(neighbour < 0 or neighbour >= count for neighbour in values):
            raise ValueError(f"adjacency row {row_index} contains an out-of-bounds neighbour")
        if row_index in values:
            raise ValueError(f"adjacency row {row_index} contains a self neighbour")
        if len(set(values)) != len(values):
            raise ValueError(f"adjacency row {row_index} contains duplicate neighbours")
        # The synthetic contract uses a deterministic row order.  This is an
        # identity-order stand-in for the production distance/identity order.
        normalised.append(tuple(sorted(values)))
    return tuple(normalised)


@dataclass(frozen=True)
class SyntheticAdjacency:
    """Validated directed row-wise adjacency for a manufactured graph."""

    rows: tuple[tuple[int, ...], ...]
    graph_id: str = SYNTHETIC_GRAPH_ID

    def __post_init__(self) -> None:
        object.__setattr__(self, "rows", _normalise_rows(self.rows))
        if not isinstance(self.graph_id, str) or not self.graph_id:
            raise ValueError("graph_id must be a non-empty string")

    @property
    def count(self) -> int:
        return len(self.rows)

    @property
    def degrees(self) -> tuple[int, ...]:
        return tuple(len(row) for row in self.rows)

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "row_count": self.count,
            "adjacency": [list(row) for row in self.rows],
            "row_degrees": list(self.degrees),
            "directed_row_semantics": True,
            "synthetic": True,
        }


def _coerce_adjacency(value: Any) -> SyntheticAdjacency:
    if isinstance(value, SyntheticAdjacency):
        return value
    if isinstance(value, Mapping):
        if "adjacency" in value:
            value = value["adjacency"]
        else:
            keys = tuple(value.keys())
            if not keys or any(isinstance(key, (bool,)) or not isinstance(key, Integral)
                               for key in keys):
                raise ValueError("adjacency mapping keys must be integer row indices")
            count = len(keys)
            if set(int(key) for key in keys) != set(range(count)):
                raise ValueError("adjacency mapping must bind every row from 0 to N-1")
            value = [value[index] for index in range(count)]
    return SyntheticAdjacency(value)


def _normalise_table_rows(rows: Any, cap: int, name: str) -> tuple[tuple[int, ...], ...]:
    if isinstance(rows, (str, bytes)):
        raise ValueError(f"{name} must be a sequence of fixed-width rows")
    try:
        raw_rows = tuple(rows)
    except TypeError as error:
        raise ValueError(f"{name} must be a sequence of fixed-width rows") from error
    normalised: list[tuple[int, ...]] = []
    for row_index, row in enumerate(raw_rows):
        values = _integer_tuple(row, f"{name} row {row_index}")
        if len(values) != cap:
            raise ValueError(f"{name} row {row_index} must have width {cap}")
        seen_padding = False
        for item in values:
            if item == -1:
                seen_padding = True
            elif item < 0:
                raise ValueError(f"{name} contains an invalid negative identity")
            elif seen_padding:
                raise ValueError(f"{name} padding is not canonical")
        normalised.append(values)
    return tuple(normalised)


def _boolean_tuple(value: Any, name: str, expected_length: int | None = None) -> tuple[bool, ...]:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a boolean sequence")
    try:
        values = tuple(value)
    except TypeError as error:
        raise ValueError(f"{name} must be a boolean sequence") from error
    result: list[bool] = []
    for item in values:
        if not isinstance(item, bool):
            raise ValueError(f"{name} must contain only booleans")
        result.append(item)
    if expected_length is not None and len(result) != expected_length:
        raise ValueError(f"{name} must have length {expected_length}")
    return tuple(result)


@dataclass(frozen=True)
class CappedNeighborTable:
    """A fixed-width synthetic neighbour table and its row truncation state."""

    cap: int
    rows: tuple[tuple[int, ...], ...]
    truncated_rows: tuple[bool, ...]
    full_row_counts: tuple[int, ...]

    def __post_init__(self) -> None:
        cap = _positive_integer(self.cap, "cap")
        rows = _normalise_table_rows(self.rows, cap, "neighbor_table")
        truncated_rows = _boolean_tuple(
            self.truncated_rows, "truncated_rows", expected_length=len(rows))
        full_row_counts = _integer_tuple(self.full_row_counts, "full_row_counts",
                                         allow_empty=False)
        if len(full_row_counts) != len(rows):
            raise ValueError("full_row_counts must match neighbor_table row count")
        if any(count < 0 for count in full_row_counts):
            raise ValueError("full_row_counts must be nonnegative")
        for row, count, truncated in zip(rows, full_row_counts, truncated_rows):
            retained = sum(item >= 0 for item in row)
            if retained > count:
                raise ValueError("neighbor_table retains more identities than full_row_counts")
            if truncated != (count > cap):
                raise ValueError("truncated_rows does not match full_row_counts and cap")
        object.__setattr__(self, "cap", cap)
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "truncated_rows", truncated_rows)
        object.__setattr__(self, "full_row_counts", full_row_counts)

    @property
    def neighbor_table(self) -> tuple[tuple[int, ...], ...]:
        return self.rows

    @property
    def retained_row_counts(self) -> tuple[int, ...]:
        return tuple(sum(item >= 0 for item in row) for row in self.rows)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cap": self.cap,
            "neighbor_table": [list(row) for row in self.rows],
            "truncated_rows": list(self.truncated_rows),
            "full_row_counts": list(self.full_row_counts),
            "retained_row_counts": list(self.retained_row_counts),
        }


def build_capped_neighbor_table(adjacency: Any, cap: Any) -> CappedNeighborTable:
    """Build a fixed-width table from synthetic full rows.

    This low-level constructor raises on an invalid cap.  The public
    ``diagnose_two_hop_provenance`` wrapper turns that error into a structured
    fail-closed result so callers cannot accidentally treat it as evidence of
    a valid halo.
    """
    graph = _coerce_adjacency(adjacency)
    limit = _positive_integer(cap, "cap")
    rows = []
    truncated = []
    for full_row in graph.rows:
        retained = full_row[:limit]
        rows.append(retained + (-1,) * (limit - len(retained)))
        truncated.append(len(full_row) > limit)
    return CappedNeighborTable(limit, tuple(rows), tuple(truncated), graph.degrees)


def _normalise_centers(centers: Any, graph: SyntheticAdjacency) -> tuple[int, ...]:
    if isinstance(centers, Integral) and not isinstance(centers, bool):
        values = (int(centers),)
    else:
        values = _integer_tuple(centers, "centers", allow_empty=False)
    if any(center < 0 or center >= graph.count for center in values):
        raise ValueError("center index outside synthetic particle field")
    if len(set(values)) != len(values):
        raise ValueError("centers must not contain duplicate identities")
    return tuple(sorted(values))


def _required_rows(graph: SyntheticAdjacency, centers: tuple[int, ...]) -> tuple[int, ...]:
    rows = set(centers)
    for center in centers:
        rows.update(graph.rows[center])
    return tuple(sorted(rows))


def _full_two_hop_sources(graph: SyntheticAdjacency, center: int) -> tuple[int, ...]:
    one_hop = {center, *graph.rows[center]}
    sources = set(one_hop)
    for row_index in one_hop:
        sources.update(graph.rows[row_index])
    return tuple(sorted(sources))


def _table_two_hop_sources(table: CappedNeighborTable, center: int) -> tuple[int, ...]:
    one_hop = {center}
    one_hop.update(item for item in table.rows[center] if item >= 0)
    sources = set(one_hop)
    for row_index in one_hop:
        sources.update(item for item in table.rows[row_index] if item >= 0)
    return tuple(sorted(sources))


@dataclass(frozen=True)
class SyntheticNeighborProvenance:
    """Synthetic, request-bound provenance metadata used by the assessor."""

    requested_centers: tuple[int, ...]
    required_rows: tuple[int, ...]
    required_two_hop_sources: tuple[tuple[int, ...], ...]
    cap: int
    neighbor_table: tuple[tuple[int, ...], ...]
    truncated_rows: tuple[bool, ...]
    bound_to_graph: bool = True
    version: str = PROVENANCE_VERSION
    source_rule: str = TWO_HOP_SOURCE_RULE

    def __post_init__(self) -> None:
        centers = _integer_tuple(self.requested_centers, "requested_centers", allow_empty=False)
        required_rows = _integer_tuple(self.required_rows, "required_rows")
        cap = _positive_integer(self.cap, "provenance cap")
        table = _normalise_table_rows(self.neighbor_table, cap, "provenance neighbor_table")
        truncated = _boolean_tuple(
            self.truncated_rows, "provenance truncated_rows", expected_length=len(table))
        source_rows = tuple(
            _integer_tuple(row, f"required_two_hop_sources[{index}]")
            for index, row in enumerate(self.required_two_hop_sources)
        )
        if len(source_rows) != len(centers):
            raise ValueError("required_two_hop_sources must match requested_centers")
        if not isinstance(self.bound_to_graph, bool):
            raise ValueError("bound_to_graph must be boolean")
        if not isinstance(self.version, str) or not isinstance(self.source_rule, str):
            raise ValueError("provenance version and source rule must be strings")
        object.__setattr__(self, "requested_centers", tuple(sorted(centers)))
        object.__setattr__(self, "required_rows", tuple(sorted(set(required_rows))))
        object.__setattr__(self, "required_two_hop_sources",
                           tuple(tuple(sorted(set(row))) for row in source_rows))
        object.__setattr__(self, "cap", cap)
        object.__setattr__(self, "neighbor_table", table)
        object.__setattr__(self, "truncated_rows", truncated)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "source_rule": self.source_rule,
            "bound_to_graph": self.bound_to_graph,
            "requested_centers": list(self.requested_centers),
            "required_rows": list(self.required_rows),
            "required_two_hop_sources": [list(row) for row in self.required_two_hop_sources],
            "cap": self.cap,
            "neighbor_table": [list(row) for row in self.neighbor_table],
            "truncated_rows": list(self.truncated_rows),
        }


def build_synthetic_provenance(
    adjacency: Any,
    table: CappedNeighborTable,
    centers: Any = (0,),
) -> SyntheticNeighborProvenance:
    """Bind full synthetic two-hop expectations to one capped table."""
    graph = _coerce_adjacency(adjacency)
    if not isinstance(table, CappedNeighborTable):
        raise ValueError("table must be a CappedNeighborTable")
    if len(table.rows) != graph.count:
        raise ValueError("table row count does not match synthetic adjacency")
    expected_table = build_capped_neighbor_table(graph, table.cap)
    if table != expected_table:
        raise ValueError("table is not the deterministic cap of synthetic adjacency")
    requested = _normalise_centers(centers, graph)
    return SyntheticNeighborProvenance(
        requested_centers=requested,
        required_rows=_required_rows(graph, requested),
        required_two_hop_sources=tuple(_full_two_hop_sources(graph, center)
                                       for center in requested),
        cap=table.cap,
        neighbor_table=table.rows,
        truncated_rows=table.truncated_rows,
    )


def _coerce_table(value: Any) -> CappedNeighborTable:
    if isinstance(value, CappedNeighborTable):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("table must be a CappedNeighborTable or mapping")
    missing = [key for key in ("cap", "neighbor_table", "truncated_rows", "full_row_counts")
               if key not in value]
    if missing:
        raise ValueError("incomplete neighbor table: missing " + ", ".join(missing))
    return CappedNeighborTable(
        cap=value["cap"],
        rows=value["neighbor_table"],
        truncated_rows=value["truncated_rows"],
        full_row_counts=value["full_row_counts"],
    )


def _coerce_provenance(value: Any) -> SyntheticNeighborProvenance:
    if isinstance(value, SyntheticNeighborProvenance):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("provenance must be a SyntheticNeighborProvenance or mapping")
    required = (
        "version", "source_rule", "bound_to_graph", "requested_centers", "required_rows",
        "required_two_hop_sources", "cap", "neighbor_table", "truncated_rows",
    )
    missing = [key for key in required if key not in value]
    if missing:
        raise ValueError("incomplete provenance: missing " + ", ".join(missing))
    return SyntheticNeighborProvenance(
        requested_centers=value["requested_centers"],
        required_rows=value["required_rows"],
        required_two_hop_sources=value["required_two_hop_sources"],
        cap=value["cap"],
        neighbor_table=value["neighbor_table"],
        truncated_rows=value["truncated_rows"],
        bound_to_graph=value["bound_to_graph"],
        version=value["version"],
        source_rule=value["source_rule"],
    )


def _context(
    graph: SyntheticAdjacency,
    centers: tuple[int, ...],
    cap: int | None,
    table: CappedNeighborTable | None,
) -> dict[str, Any]:
    required_rows = _required_rows(graph, centers)
    result: dict[str, Any] = {
        "graph_id": graph.graph_id,
        "synthetic_row_count": graph.count,
        "requested_centers": list(centers),
        "required_rows": list(required_rows),
        "required_two_hop_sources": [
            {"center": center, "sources": list(_full_two_hop_sources(graph, center))}
            for center in centers
        ],
        "cap": cap,
    }
    if table is not None:
        truncated = [index for index, flag in enumerate(table.truncated_rows) if flag]
        required_truncated = [index for index in truncated if index in required_rows]
        result.update({
            "full_row_counts": list(table.full_row_counts),
            "retained_row_counts": list(table.retained_row_counts),
            "truncated_rows": truncated,
            "required_truncated_rows": required_truncated,
            "non_required_truncated_rows": [
                index for index in truncated if index not in required_rows
            ],
            "observed_two_hop_sources": [
                {"center": center, "sources": list(_table_two_hop_sources(table, center))}
                for center in centers
            ],
        })
    return result


def _base_result(
    status: str,
    graph: SyntheticAdjacency | None = None,
    centers: tuple[int, ...] | None = None,
    cap: int | None = None,
    table: CappedNeighborTable | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": status,
        **_flags(),
        "fail_closed": status.startswith("fail_closed"),
        "failure_code": None,
        "failure_reason": None,
        "accepted_for_requested_centers": False,
        "provenance_complete_for_requested_centers": False,
        "global_provenance_complete": False,
        "cap_sufficient_for_requested_centers": False,
        "cap_increase_is_formal_strategy": False,
    }
    if graph is not None and centers is not None:
        result.update(_context(graph, centers, cap, table))
    else:
        result.update({"graph_id": None, "synthetic_row_count": None,
                       "requested_centers": None, "required_rows": None,
                       "required_two_hop_sources": None, "cap": cap})
    return result


def _input_failure(
    status: str,
    code: str,
    reason: str,
    *,
    graph: SyntheticAdjacency | None = None,
    centers: tuple[int, ...] | None = None,
    cap: Any = None,
) -> dict[str, Any]:
    result = _base_result(status, graph, centers, cap if isinstance(cap, int) else None)
    result["failure_code"] = code
    result["failure_reason"] = reason
    return result


def _provenance_error(
    graph: SyntheticAdjacency,
    table: CappedNeighborTable,
    provenance: SyntheticNeighborProvenance,
    centers: tuple[int, ...],
) -> str | None:
    expected_table = build_capped_neighbor_table(graph, table.cap)
    if provenance.version != PROVENANCE_VERSION:
        return "unknown synthetic neighbor provenance version"
    if provenance.source_rule != TWO_HOP_SOURCE_RULE:
        return "unknown synthetic two-hop source rule"
    if not provenance.bound_to_graph:
        return "neighbor provenance is not bound to the synthetic graph"
    if provenance.cap != table.cap:
        return "neighbor provenance cap does not match neighbor table"
    if provenance.neighbor_table != table.rows:
        return "neighbor provenance is not bound to this neighbor table"
    if provenance.truncated_rows != table.truncated_rows:
        return "neighbor provenance truncation state is incomplete or inconsistent"
    if provenance.requested_centers != centers:
        return "neighbor provenance request binding does not match requested centers"
    expected_required_rows = _required_rows(graph, centers)
    if provenance.required_rows != expected_required_rows:
        return "required row provenance is incomplete or inconsistent"
    expected_sources = tuple(_full_two_hop_sources(graph, center) for center in centers)
    if provenance.required_two_hop_sources != expected_sources:
        return "required two-hop source provenance is incomplete or inconsistent"
    if table != expected_table:
        return "neighbor table is not the deterministic cap of synthetic adjacency"
    return None


def _assess_valid(
    graph: SyntheticAdjacency,
    table: CappedNeighborTable,
    provenance: SyntheticNeighborProvenance,
    centers: tuple[int, ...],
) -> dict[str, Any]:
    result = _base_result("pending", graph, centers, table.cap, table)
    error = _provenance_error(graph, table, provenance, centers)
    if error is not None:
        result.update({
            "status": "fail_closed_incomplete_provenance",
            "fail_closed": True,
            "failure_code": "incomplete_provenance",
            "failure_reason": error,
        })
        return result

    required_rows = set(_required_rows(graph, centers))
    truncated_rows = set(index for index, flag in enumerate(table.truncated_rows) if flag)
    required_truncated = sorted(required_rows & truncated_rows)
    non_required_truncated = sorted(truncated_rows - required_rows)
    missing_sources = []
    for center in centers:
        expected = set(_full_two_hop_sources(graph, center))
        observed = set(_table_two_hop_sources(table, center))
        missing_sources.append({"center": center, "sources": sorted(expected - observed)})
    result["missing_required_sources"] = missing_sources

    if required_truncated:
        result.update({
            "status": "fail_closed_required_row_truncated",
            "fail_closed": True,
            "failure_code": "required_row_truncated",
            "failure_reason": "neighbor provenance is truncated for a required two-hop row",
            "required_truncated_rows": required_truncated,
            "non_required_truncated_rows": non_required_truncated,
        })
        return result

    result["accepted_for_requested_centers"] = True
    result["provenance_complete_for_requested_centers"] = True
    result["cap_sufficient_for_requested_centers"] = True
    result["global_provenance_complete"] = not truncated_rows
    result["required_truncated_rows"] = []
    result["non_required_truncated_rows"] = non_required_truncated
    if non_required_truncated:
        result["status"] = "complete_for_requested_centers_non_required_rows_truncated"
        result["failure_reason"] = (
            "non-required rows remain truncated; the requested two-hop provenance is complete"
        )
    else:
        result["status"] = "complete"
    return result


def assess_two_hop_provenance(
    adjacency: Any,
    table: Any,
    provenance: Any,
    centers: Any = (0,),
) -> dict[str, Any]:
    """Assess one synthetic table/provenance binding without raising on failure."""
    try:
        graph = _coerce_adjacency(adjacency)
        requested = _normalise_centers(centers, graph)
        capped = _coerce_table(table)
        if len(capped.rows) != graph.count:
            raise ValueError("table row count does not match synthetic adjacency")
        bound = _coerce_provenance(provenance)
    except ValueError as error:
        return _input_failure(
            "fail_closed_incomplete_provenance", "incomplete_provenance", str(error),
            graph=locals().get("graph"), centers=locals().get("requested"),
            cap=locals().get("capped").cap if isinstance(locals().get("capped"), CappedNeighborTable)
            else None,
        )
    return _assess_valid(graph, capped, bound, requested)


def diagnose_two_hop_provenance(
    adjacency: Any,
    *,
    cap: Any = DEFAULT_NEIGHBOR_CAP,
    centers: Any = (0,),
    provenance: Any = _AUTO_PROVENANCE,
) -> dict[str, Any]:
    """Run one synthetic cap/provenance diagnostic and return a safe result.

    With the default ``provenance`` sentinel, complete synthetic provenance is
    constructed for the requested graph and cap.  Passing ``None`` models a
    missing provenance object.  Passing a mapping or
    :class:`SyntheticNeighborProvenance` exercises explicit binding checks.
    """
    try:
        graph = _coerce_adjacency(adjacency)
        requested = _normalise_centers(centers, graph)
    except ValueError as error:
        return _input_failure("fail_closed_invalid_synthetic_input", "invalid_input", str(error))
    try:
        limit = _positive_integer(cap, "cap")
    except ValueError as error:
        return _input_failure(
            "fail_closed_invalid_cap", "invalid_cap", str(error),
            graph=graph, centers=requested, cap=cap,
        )

    table = build_capped_neighbor_table(graph, limit)
    if provenance is None:
        result = _base_result("fail_closed_missing_provenance", graph, requested, limit, table)
        result.update({
            "fail_closed": True,
            "failure_code": "missing_provenance",
            "failure_reason": "required two-hop provenance is missing; formal use fails closed",
        })
        return result
    if provenance is _AUTO_PROVENANCE:
        bound = build_synthetic_provenance(graph, table, requested)
    else:
        try:
            bound = _coerce_provenance(provenance)
        except ValueError as error:
            result = _base_result("fail_closed_incomplete_provenance",
                                  graph, requested, limit, table)
            result.update({
                "fail_closed": True,
                "failure_code": "incomplete_provenance",
                "failure_reason": str(error),
            })
            return result
    return _assess_valid(graph, table, bound, requested)


# Descriptive alias for callers that prefer the verb used by the diagnostic.
evaluate_two_hop_provenance = diagnose_two_hop_provenance


def synthetic_f3_adjacency() -> SyntheticAdjacency:
    """Return the manufactured graph used by the canonical diagnostic suite.

    Rows 1 and 69 each have 65 neighbours.  Therefore cap 64 truncates row 1
    (required for centre 0) and row 69 (unrelated to centre 0), while cap 65
    retains every row.  Centre 66 has no neighbours, making row 69 a clean
    non-required-truncation example at cap 64.
    """
    row_count = 70
    rows: list[tuple[int, ...]] = [tuple() for _ in range(row_count)]
    rows[0] = (1, 2)
    rows[1] = (0, *range(2, 66))  # 65 neighbours; required by centre 0.
    rows[2] = (0, 1)
    rows[69] = tuple(range(65))  # 65 neighbours; unrelated to centre 0/66.
    return SyntheticAdjacency(tuple(rows))


def _incomplete_provenance_example(
    graph: SyntheticAdjacency,
    centers: tuple[int, ...],
    cap: int,
) -> dict[str, Any]:
    table = build_capped_neighbor_table(graph, cap)
    payload = build_synthetic_provenance(graph, table, centers).to_dict()
    # Deliberately remove a required field.  The public assessor must report a
    # structured fail-closed result rather than infer or repair it.
    del payload["required_two_hop_sources"]
    return payload


def run_diagnostic() -> dict[str, Any]:
    """Run all bounded synthetic cases and return canonical-JSON-compatible data."""
    graph = synthetic_f3_adjacency()
    scenarios = {
        "cap_insufficient_required_row": diagnose_two_hop_provenance(
            graph, cap=DEFAULT_NEIGHBOR_CAP, centers=(0,)),
        "raised_cap_complete": diagnose_two_hop_provenance(
            graph, cap=65, centers=(0,)),
        "non_required_row_truncation": diagnose_two_hop_provenance(
            graph, cap=DEFAULT_NEIGHBOR_CAP, centers=(66,)),
        "invalid_cap": diagnose_two_hop_provenance(graph, cap=0, centers=(0,)),
        "missing_provenance": diagnose_two_hop_provenance(
            graph, cap=65, centers=(0,), provenance=None),
        "incomplete_provenance": diagnose_two_hop_provenance(
            graph, cap=65, centers=(0,),
            provenance=_incomplete_provenance_example(graph, (0,), 65)),
    }
    negative_statuses = {
        "invalid_cap", "missing_provenance", "incomplete_provenance",
    }
    negative_cases_fail_closed = all(
        scenarios[name]["fail_closed"] for name in negative_statuses)
    return {
        "schema": SCHEMA,
        "status": "completed",
        "mode": "synthetic_only_two_hop_neighbor_provenance_capacity",
        **_flags(),
        "default_cap": DEFAULT_NEIGHBOR_CAP,
        "raised_cap_observation": 65,
        "synthetic_graph": graph.to_dict(),
        "scenarios": scenarios,
        "summary": {
            "required_row_truncation_reproduced": scenarios[
                "cap_insufficient_required_row"]["status"]
                == "fail_closed_required_row_truncated",
            "raised_cap_restores_complete_provenance": scenarios[
                "raised_cap_complete"]["status"] == "complete",
            "non_required_truncation_is_explicit": scenarios[
                "non_required_row_truncation"]["status"]
                == "complete_for_requested_centers_non_required_rows_truncated",
            "negative_cases_fail_closed": negative_cases_fail_closed,
        },
        "policy": {
            "cap_increase_is_formal_strategy": False,
            "production_neighbor_cap_changed": False,
            "formal_training_eligible": False,
            "gate_effect": False,
            "credit_awarded": 0,
        },
        "scope_note": (
            "Synthetic diagnostic evidence only. The raised-cap case demonstrates "
            "capacity sufficiency in this manufactured graph; it does not propose "
            "or authorize a production cap change."
        ),
    }


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Serialize a diagnostic payload deterministically without whitespace noise."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    print(canonical_json(run_diagnostic()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
