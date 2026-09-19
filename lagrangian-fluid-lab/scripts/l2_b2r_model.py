#!/usr/bin/env python3
"""The prospective L2-R B2 graph model and its causal input contract.

This module is deliberately independent from the historical ``l2_b2_learning``
registration script.  It contains a real particle-graph message-passing model,
but it does not contain a launcher or a training loop.  B2R preparation can
therefore be reviewed and tested while R2 is still open.

The two controlled routes use the same message-passing trunk and differ only in
the declared output operator:

* ``raw`` predicts the next displacement directly.  There is no clipping,
  projection, or unreported wall correction.
* ``hybrid`` predicts an acceleration residual around the known-control
  semi-implicit displacement prior.  The prior is an explicit physical
  operator, not a post-hoc wall projection; the residual and its cost are
  returned for accounting.

Both routes consume only the current particle state, current prescribed
control, current material/geometry features, and the current graph.  A future
fluid or free-body state is never accepted by the input validator.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

import torch
from torch import nn


MODEL_SCHEMA = "l2r.b2r.graph_model.v1"
MODEL_FAMILY = "current_state_particle_graph_message_passing"
ROUTES = ("raw", "hybrid")
DEFAULT_HIDDEN = 64
DEFAULT_MESSAGE_STEPS = 2

_FUTURE_MARKERS = (
    "future",
    "next_state",
    "state_t1",
    "frame1",
    "rollout_target",
)
_FUTURE_STATE_TERMS = (
    "fluid",
    "body",
    "free_body",
    "particle",
    "pressure",
    "density",
    "position",
    "velocity",
    "state",
    "reference",
    "trajectory",
    "label",
)


class B2RInputContractError(ValueError):
    """Raised when a graph input violates the current-state contract."""


class B2RDependencyError(RuntimeError):
    """Raised by a caller that tries to execute before the B2R gate is open."""


@dataclass(frozen=True)
class GraphBatch:
    """One current-state particle graph.

    ``node_features`` must contain the declared current material/geometry
    features (for example boundary distance and normal summaries).  Position,
    velocity and current control remain explicit fields so the model contract
    cannot silently replace them with a precomputed future-aware feature table.

    ``edge_index`` has the PyG-style ``[2, E]`` convention: row zero is the
    source particle and row one is the destination particle.  Edge attributes
    are current relative geometry/velocity features.
    """

    position: torch.Tensor
    velocity: torch.Tensor
    node_features: torch.Tensor
    edge_index: torch.Tensor
    edge_features: torch.Tensor
    interval_s: float | torch.Tensor
    control_acceleration: torch.Tensor
    particle_id: torch.Tensor | None = None


def _finite_tensor(value: torch.Tensor, name: str) -> None:
    if not isinstance(value, torch.Tensor) or not value.is_floating_point():
        raise B2RInputContractError(f"{name} must be a floating-point tensor")
    if not torch.isfinite(value).all():
        raise B2RInputContractError(f"{name} contains non-finite values")


def _normalise_key(value: object) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _future_paths(value: object, prefix: str = "") -> list[str]:
    """Find explicit future fluid/free-body aliases in a nested payload."""

    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalised = _normalise_key(key)
            path = f"{prefix}.{key}" if prefix else str(key)
            has_marker = any(marker in normalised for marker in _FUTURE_MARKERS)
            has_state_term = any(term in normalised for term in _FUTURE_STATE_TERMS)
            if has_marker and has_state_term:
                found.append(path)
            found.extend(_future_paths(item, path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(_future_paths(item, f"{prefix}[{index}]"))
    return found


def validate_causal_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate metadata describing the inputs supplied to a B2R run."""

    if not isinstance(payload, Mapping):
        raise B2RInputContractError("causal input payload must be a mapping")
    forbidden = _future_paths(payload)
    if forbidden:
        raise B2RInputContractError(
            "future fluid/free-body state is forbidden in B2R inputs: "
            + ", ".join(forbidden)
        )
    return {
        "valid": True,
        "forbidden_future_state_paths": [],
        "allowed_current_inputs": [
            "current particle position",
            "current particle velocity",
            "current particle identity and mass/material properties",
            "current geometry/boundary features",
            "current prescribed control",
            "current time and interval",
        ],
        "future_fluid_or_free_body_state_allowed": False,
    }


def _scalar_interval(interval_s: float | torch.Tensor, *, device: torch.device, dtype: torch.dtype) -> torch.Tensor:
    value = torch.as_tensor(interval_s, device=device, dtype=dtype)
    if value.numel() != 1 or not torch.isfinite(value).all() or float(value) <= 0:
        raise B2RInputContractError("interval_s must be one finite positive scalar")
    return value.reshape(())


def validate_graph_batch(batch: GraphBatch) -> GraphBatch:
    """Validate shapes, finiteness, IDs and edge bounds before model execution."""

    if not isinstance(batch, GraphBatch):
        raise B2RInputContractError("GraphBatch is required")
    position = batch.position
    velocity = batch.velocity
    node_features = batch.node_features
    edge_index = batch.edge_index
    edge_features = batch.edge_features
    control = batch.control_acceleration
    if position.ndim != 2 or tuple(position.shape[1:]) != (3,) or position.shape[0] == 0:
        raise B2RInputContractError("position must have shape [N,3] and N>0")
    if velocity.shape != position.shape:
        raise B2RInputContractError("velocity must have the same [N,3] shape as position")
    if node_features.ndim != 2 or node_features.shape[0] != position.shape[0]:
        raise B2RInputContractError("node_features must have shape [N,F]")
    if edge_index.ndim != 2 or edge_index.shape[0] != 2:
        raise B2RInputContractError("edge_index must have shape [2,E]")
    if edge_index.dtype not in (torch.int32, torch.int64):
        raise B2RInputContractError("edge_index must be an integer tensor")
    if edge_features.ndim != 2 or edge_features.shape[0] != edge_index.shape[1]:
        raise B2RInputContractError("edge_features must have shape [E,K]")
    if control.ndim not in (1, 2) or control.shape[-1] != 3:
        raise B2RInputContractError("control_acceleration must have shape [3] or [N,3]")
    if control.ndim == 2 and control.shape[0] not in (1, position.shape[0]):
        raise B2RInputContractError("per-particle control must have one row or N rows")
    for name, value in (
        ("position", position),
        ("velocity", velocity),
        ("node_features", node_features),
        ("edge_features", edge_features),
        ("control_acceleration", control),
    ):
        _finite_tensor(value, name)
    if edge_index.numel():
        if int(edge_index.min()) < 0 or int(edge_index.max()) >= position.shape[0]:
            raise B2RInputContractError("edge_index contains an out-of-range node")
    interval = _scalar_interval(batch.interval_s, device=position.device, dtype=position.dtype)
    if edge_index.device != position.device or edge_features.device != position.device:
        raise B2RInputContractError("graph tensors must be on the same device")
    if velocity.device != position.device or node_features.device != position.device or control.device != position.device:
        raise B2RInputContractError("state tensors must be on the same device")
    if batch.particle_id is not None:
        ids = batch.particle_id
        if ids.ndim != 1 or ids.shape[0] != position.shape[0] or ids.dtype not in (torch.int32, torch.int64):
            raise B2RInputContractError("particle_id must be a unique integer [N] tensor")
        if torch.unique(ids).numel() != ids.numel():
            raise B2RInputContractError("particle_id must be unique")
    return GraphBatch(
        position=position,
        velocity=velocity,
        node_features=node_features,
        edge_index=edge_index,
        edge_features=edge_features,
        interval_s=interval,
        control_acceleration=control,
        particle_id=batch.particle_id,
    )


def build_radius_graph(
    position: torch.Tensor,
    velocity: torch.Tensor,
    particle_id: torch.Tensor,
    *,
    radius_m: float,
    max_neighbors: int | None = None,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Build a deterministic directed current-state graph.

    This small reference builder is intentionally explicit and deterministic;
    production training may replace it with an audited spatial index while
    retaining the returned edge semantics.  The edge attributes are
    ``relative_position[3], relative_velocity[3], distance[1]``.
    """

    if position.ndim != 2 or position.shape[1] != 3 or velocity.shape != position.shape:
        raise B2RInputContractError("position and velocity must be matching [N,3] tensors")
    if particle_id.ndim != 1 or particle_id.shape[0] != position.shape[0]:
        raise B2RInputContractError("particle_id must match the particle axis")
    if not math.isfinite(radius_m) or radius_m <= 0:
        raise B2RInputContractError("radius_m must be finite and positive")
    if max_neighbors is not None and (isinstance(max_neighbors, bool) or max_neighbors < 1):
        raise B2RInputContractError("max_neighbors must be positive when provided")
    _finite_tensor(position, "position")
    _finite_tensor(velocity, "velocity")
    if particle_id.dtype not in (torch.int32, torch.int64) or torch.unique(particle_id).numel() != len(particle_id):
        raise B2RInputContractError("particle_id must be unique integer IDs")

    n = position.shape[0]
    # The reference builder uses detached CPU values only for graph topology.
    p = position.detach().cpu()
    v = velocity.detach().cpu()
    ids = particle_id.detach().cpu()
    sources: list[int] = []
    destinations: list[int] = []
    attributes: list[torch.Tensor] = []
    for destination in range(n):
        delta = p - p[destination]
        distance = torch.linalg.vector_norm(delta, dim=1)
        candidates = [
            source for source in range(n)
            if source != destination and float(distance[source]) <= radius_m
        ]
        candidates.sort(key=lambda source: (float(distance[source]), int(ids[source])))
        if max_neighbors is not None:
            candidates = candidates[:max_neighbors]
        for source in candidates:
            sources.append(source)
            destinations.append(destination)
            attributes.append(torch.cat((delta[source], v[source] - v[destination], distance[source].reshape(1))))
    if not attributes:
        edge_index = torch.empty((2, 0), dtype=torch.long, device=position.device)
        edge_features = torch.empty((0, 7), dtype=position.dtype, device=position.device)
    else:
        edge_index = torch.tensor((sources, destinations), dtype=torch.long, device=position.device)
        edge_features = torch.stack(attributes).to(device=position.device, dtype=position.dtype)
    return edge_index, edge_features


class _MLP(nn.Module):
    def __init__(self, inputs: int, hidden: int, outputs: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(inputs, hidden),
            nn.SiLU(),
            nn.Linear(hidden, hidden),
            nn.SiLU(),
            nn.Linear(hidden, outputs),
        )

    def forward(self, value: torch.Tensor) -> torch.Tensor:
        return self.net(value)


class _MessagePassingBlock(nn.Module):
    def __init__(self, hidden: int, edge_hidden: int):
        super().__init__()
        self.edge_encoder = _MLP(edge_hidden, hidden, hidden)
        self.message = _MLP(3 * hidden, hidden, hidden)
        self.update = _MLP(2 * hidden, hidden, hidden)
        self.norm = nn.LayerNorm(hidden)

    def forward(self, node_state: torch.Tensor, edge_index: torch.Tensor, edge_features: torch.Tensor) -> torch.Tensor:
        source, destination = edge_index
        if edge_index.shape[1] == 0:
            aggregate = torch.zeros_like(node_state)
        else:
            encoded_edges = self.edge_encoder(edge_features)
            messages = self.message(torch.cat((node_state[source], node_state[destination], encoded_edges), dim=-1))
            aggregate = torch.zeros_like(node_state)
            aggregate.index_add_(0, destination, messages)
            counts = torch.zeros(node_state.shape[0], 1, device=node_state.device, dtype=node_state.dtype)
            counts.index_add_(0, destination, torch.ones_like(destination, dtype=node_state.dtype).unsqueeze(-1))
            aggregate = aggregate / counts.clamp_min(1.0)
        return self.norm(node_state + self.update(torch.cat((node_state, aggregate), dim=-1)))


class GraphDynamicsModel(nn.Module):
    """A current-state particle graph predictor for the two B2R routes."""

    def __init__(
        self,
        *,
        node_features: int,
        edge_features: int = 7,
        hidden: int = DEFAULT_HIDDEN,
        message_steps: int = DEFAULT_MESSAGE_STEPS,
        route: str = "raw",
    ):
        super().__init__()
        if route not in ROUTES:
            raise ValueError(f"unsupported B2R route: {route}")
        if isinstance(node_features, bool) or node_features < 0:
            raise ValueError("node_features must be a nonnegative integer")
        if isinstance(edge_features, bool) or edge_features < 1:
            raise ValueError("edge_features must be positive")
        if isinstance(hidden, bool) or hidden < 4:
            raise ValueError("hidden must be at least 4")
        if isinstance(message_steps, bool) or message_steps < 1:
            raise ValueError("message_steps must be positive")
        self.route = route
        self.node_features = int(node_features)
        self.edge_features = int(edge_features)
        self.hidden = int(hidden)
        self.message_steps = int(message_steps)
        # Position, velocity, declared node features and current control.
        self.encoder = _MLP(3 + 3 + self.node_features + 3, hidden, hidden)
        self.blocks = nn.ModuleList(
            _MessagePassingBlock(hidden, self.edge_features) for _ in range(message_steps)
        )
        self.decoder = _MLP(hidden, hidden, 3)

    def _control_rows(self, control: torch.Tensor, count: int) -> torch.Tensor:
        if control.ndim == 1:
            return control.expand(count, -1)
        if control.shape[0] == 1:
            return control.expand(count, -1)
        if control.shape[0] != count:
            raise B2RInputContractError("control rows do not match the particle axis")
        return control

    def forward(self, batch: GraphBatch, *, return_diagnostics: bool = False):
        batch = validate_graph_batch(batch)
        if batch.node_features.shape[1] != self.node_features:
            raise B2RInputContractError(
                f"model expects {self.node_features} node features, got {batch.node_features.shape[1]}"
            )
        if batch.edge_features.shape[1] != self.edge_features:
            raise B2RInputContractError(
                f"model expects {self.edge_features} edge features, got {batch.edge_features.shape[1]}"
            )
        control = self._control_rows(batch.control_acceleration, batch.position.shape[0])
        node_input = torch.cat((batch.position, batch.velocity, batch.node_features, control), dim=-1)
        node_state = self.encoder(node_input)
        for block in self.blocks:
            node_state = block(node_state, batch.edge_index, batch.edge_features)
        output = self.decoder(node_state)
        dt = _scalar_interval(batch.interval_s, device=batch.position.device, dtype=batch.position.dtype)
        if self.route == "raw":
            displacement = output
            prior = torch.zeros_like(displacement)
            correction = torch.zeros_like(displacement)
        else:
            # Known-control prior: x(t+dt)-x(t) = v(t)dt + 1/2 a_control dt².
            # The graph predicts only an acceleration residual.  No wall
            # projection or output clipping is applied here.
            prior = batch.velocity * dt + 0.5 * control * dt.square()
            correction = 0.5 * output * dt.square()
            displacement = prior + correction
        diagnostics = {
            "route": self.route,
            "prior_displacement": prior,
            "residual_displacement": correction,
            "correction_l2_mean": torch.linalg.vector_norm(correction, dim=-1).mean(),
            "correction_l2_max": torch.linalg.vector_norm(correction, dim=-1).max(),
            "residual_displacement_l2": torch.linalg.vector_norm(correction, dim=-1),
            "residual_trigger_count": int((torch.linalg.vector_norm(correction, dim=-1) > 0).sum()),
            # The operator cost is reported as tensors here; the runner will
            # add wall/CPU/GPU measurements around the same paired forward.
            "prior_and_residual_cost": {
                "prior_vector_ops_per_particle": 12,
                "residual_vector_ops_per_particle": 6,
                "message_passing_steps": self.message_steps,
            },
            "posthoc_wall_projection": False,
            "output_clipping": False,
        }
        return (displacement, diagnostics) if return_diagnostics else displacement


def model_for(*, route: str, node_features: int, edge_features: int = 7, hidden: int = DEFAULT_HIDDEN,
              message_steps: int = DEFAULT_MESSAGE_STEPS) -> GraphDynamicsModel:
    """Construct the same graph architecture for either controlled route."""

    return GraphDynamicsModel(
        node_features=node_features,
        edge_features=edge_features,
        hidden=hidden,
        message_steps=message_steps,
        route=route,
    )


def graph_model_contract(*, node_features: int, edge_features: int = 7, hidden: int = DEFAULT_HIDDEN,
                         message_steps: int = DEFAULT_MESSAGE_STEPS) -> dict[str, Any]:
    """Return the machine-readable contract bound into a future attempt."""

    if node_features < 0 or edge_features < 1:
        raise ValueError("invalid feature widths")
    return {
        "schema": MODEL_SCHEMA,
        "model_family": MODEL_FAMILY,
        "architecture": {
            "node_encoder": "MLP(position, velocity, current_node_features, current_control)",
            "message_passing": "directed edge messages with destination mean aggregation and residual LayerNorm update",
            "message_steps": message_steps,
            "hidden": hidden,
            "node_features": node_features,
            "edge_features": edge_features,
            "edge_semantics": "current relative position, current relative velocity, current distance",
        },
        "routes": {
            "raw": {
                "output": "direct displacement in metres",
                "posthoc_wall_projection": False,
                "output_clipping": False,
            },
            "hybrid": {
                "output": "acceleration residual integrated around known-control displacement prior",
                "prior": "velocity*dt + 0.5*current_control_acceleration*dt^2",
                "posthoc_wall_projection": False,
                "output_clipping": False,
                "required_reporting": [
                    "residual_displacement_l2",
                    "residual_trigger_count",
                    "prior_and_residual_cost",
                ],
            },
        },
        "causal_input_contract": {
            "allowed": [
                "current position",
                "current velocity",
                "current particle identity",
                "current mass/material properties",
                "current geometry/boundary features",
                "current prescribed control",
                "current time and interval",
            ],
            "prohibited": [
                "future fluid position/velocity/density/pressure",
                "future free-body state or pose",
                "future reference trajectory or label",
            ],
        },
        "qualification_claim": False,
    }
