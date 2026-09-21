"""Causal dual-increment baselines with full-field neighbors and exact halos.

The public model contract is deliberately small: a :class:`State` and the
current :class:`KnownInputs` produce a six-vector per particle containing
``(dx, dv)``. Graph models build their neighborhood on the complete current
particle field. A sampled loss center only limits the loss rows; it never
turns the input field into a sampled or disconnected graph.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import torch
from scipy.spatial import cKDTree
from torch import nn

from scripts.core_contract import Predictor, StepPrediction, validate_prediction

MODEL_VERSION = "core.dual_increment.v1"
FEATURE_VERSION = "core.finite_triangle_features.v1"
NORMALIZATION_VERSION = "core.train_normalization.v1"
INITIALIZATION_VERSION = "core.paired_initialization.common_encoder_head.v1"
FEATURE_DIM = 23
OUTPUT_DIM = 6
MODEL_KINDS = ("mlp", "graph_raw", "graph_residual")
NEIGHBOR_RADIUS_OVER_H = 2.0
MAX_NEIGHBORS = 64


def _readonly_array(value: Any, *, dtype=np.float32, shape=None) -> np.ndarray:
    result = np.asarray(value, dtype=dtype).copy()
    if shape is not None and result.shape != shape:
        raise ValueError(f"expected array shape {shape}, got {result.shape}")
    if not np.isfinite(result).all():
        raise ValueError("normalization values must be finite")
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class Normalization:
    """Train-only affine normalization for node features and six targets."""

    feature_mean: np.ndarray
    feature_std: np.ndarray
    target_mean: np.ndarray
    target_std: np.ndarray
    source_split: str = "train"
    version: str = NORMALIZATION_VERSION
    target_reference: str = "raw_dual_increment_train_shared"

    def __post_init__(self):
        if self.version != NORMALIZATION_VERSION or self.source_split != "train":
            raise ValueError("normalization must be the versioned train split")
        if self.target_reference != "raw_dual_increment_train_shared":
            raise ValueError("raw/residual baselines must share the train target scale")
        object.__setattr__(self, "feature_mean", _readonly_array(self.feature_mean, shape=(FEATURE_DIM,)))
        object.__setattr__(self, "feature_std", _readonly_array(self.feature_std, shape=(FEATURE_DIM,)))
        object.__setattr__(self, "target_mean", _readonly_array(self.target_mean, shape=(OUTPUT_DIM,)))
        object.__setattr__(self, "target_std", _readonly_array(self.target_std, shape=(OUTPUT_DIM,)))
        if np.any(self.feature_std <= 0) or np.any(self.target_std <= 0):
            raise ValueError("normalization standard deviations must be positive")

    def normalize_features(self, value):
        if torch.is_tensor(value):
            mean = torch.tensor(self.feature_mean, dtype=value.dtype, device=value.device)
            std = torch.tensor(self.feature_std, dtype=value.dtype, device=value.device)
            return (value - mean) / std
        return (value - self.feature_mean) / self.feature_std

    def normalize_target(self, value):
        if torch.is_tensor(value):
            mean = torch.tensor(self.target_mean, dtype=value.dtype, device=value.device)
            std = torch.tensor(self.target_std, dtype=value.dtype, device=value.device)
            return (value - mean) / std
        return (value - self.target_mean) / self.target_std

    def denormalize_target(self, value):
        if torch.is_tensor(value):
            mean = torch.tensor(self.target_mean, dtype=value.dtype, device=value.device)
            std = torch.tensor(self.target_std, dtype=value.dtype, device=value.device)
            return value * std + mean
        return value * self.target_std + self.target_mean

    def as_dict(self):
        return {
            "version": self.version,
            "source_split": self.source_split,
            "feature_mean": self.feature_mean.tolist(),
            "feature_std": self.feature_std.tolist(),
            "target_mean": self.target_mean.tolist(),
            "target_std": self.target_std.tolist(),
            "target_reference": self.target_reference,
        }

    @classmethod
    def from_dict(cls, payload):
        return cls(payload["feature_mean"], payload["feature_std"],
                   payload["target_mean"], payload["target_std"],
                   payload.get("source_split", "train"), payload.get("version", NORMALIZATION_VERSION),
                   payload.get("target_reference", "raw_dual_increment_train_shared"))


def neighbor_table(state, h, limit=MAX_NEIGHBORS):
    """Return deterministic complete-field neighbors within ``2h``.

    Rows contain source indices sorted by squared distance, then the public
    composite particle identity. The cKDTree query is expanded at the cutoff
    so equal-distance contenders are included before the fixed ``limit`` is
    applied. ``-1`` is padding only; invalid/survivor filtering is rejected.
    """
    if not np.isfinite(h) or h <= 0:
        raise ValueError("positive finite smoothing length is required")
    if isinstance(limit, bool) or not isinstance(limit, (int, np.integer)) or limit < 1:
        raise ValueError("positive integer neighbor limit is required")
    if not state.valid.all():
        raise ValueError("closed-system graph requires complete active particle axis")
    x = np.asarray(state.position, dtype=np.float64)
    n = len(x)
    if n < 1 or x.ndim != 2 or x.shape[1] != 3:
        raise ValueError("state must contain a nonempty [N,3] position field")
    tree = cKDTree(x)
    radius = float(NEIGHBOR_RADIUS_OVER_H * h)
    radius2 = radius * radius
    k = min(n, int(limit) + 1)  # self plus up to limit sources
    distance, index = tree.query(x, k=k, distance_upper_bound=radius, workers=1)
    distance = np.asarray(distance).reshape(n, k)
    index = np.asarray(index).reshape(n, k)
    neighbors = np.full((n, int(limit)), -1, dtype=np.int64)
    truncated = 0
    for i in range(n):
        ids = index[i][(index[i] < n) & (index[i] != i)]
        if len(ids) >= int(limit):
            # query() is distance ordered but does not promise deterministic
            # ordering among ties. Expand the boundary before ID sorting.
            d2 = np.sum((x[ids] - x[i]) ** 2, axis=1)
            cutoff = float(np.partition(d2, int(limit) - 1)[int(limit) - 1])
            expanded_radius = np.nextafter(min(radius, np.sqrt(max(cutoff, 0.0))), np.inf)
            ids = np.asarray(tree.query_ball_point(x[i], expanded_radius), dtype=np.int64)
            ids = ids[(ids != i) & (np.sum((x[ids] - x[i]) ** 2, axis=1) <= radius2 * (1.0 + 1e-12))]
        d2 = np.sum((x[ids] - x[i]) ** 2, axis=1)
        # np.lexsort uses the final key as primary: distance, then ID, then
        # zone for the rare case where IDs are reused across zones.
        order = np.lexsort((state.particle_zone[ids], state.particle_id[ids], d2))
        ids = ids[order]
        if len(ids) > int(limit):
            truncated += 1
            ids = ids[: int(limit)]
        neighbors[i, : len(ids)] = ids
    return neighbors, {
        "neighbor_truncation_fraction": float(truncated / n),
        "field_particle_count": int(n),
        "neighbor_radius_over_h": NEIGHBOR_RADIUS_OVER_H,
        "max_neighbors": int(limit),
    }


def two_hop_halo(centers, neighbors, n=None):
    """Return the exact center, one-hop, and two-hop source index union.

    ``neighbors`` describes the complete particle axis.  A caller may select
    a center chunk, but it cannot pass a truncated neighbor table or silently
    introduce an out-of-axis source: doing so would make a graph chunk depend
    on which chunk happened to be evaluated first.
    """
    if torch.is_tensor(neighbors):
        if neighbors.ndim != 2 or not neighbors.dtype in (
                torch.int8, torch.int16, torch.int32, torch.int64,
                torch.uint8):
            raise ValueError("neighbors must be an integer [N,K] table")
        rows = int(neighbors.shape[0])
        total = rows if n is None else int(n)
        if total != rows or total < 0:
            raise ValueError("halo particle axis must match neighbor table")
        raw_centers = torch.as_tensor(centers, device=neighbors.device)
        if raw_centers.dtype not in (torch.int8, torch.int16, torch.int32,
                                     torch.int64, torch.uint8):
            raise ValueError("centers must be integer indices")
        centers = raw_centers.to(dtype=torch.long).reshape(-1)
        if torch.any((centers < 0) | (centers >= total)):
            raise ValueError("center index outside particle field")
        if torch.any((neighbors < -1) | (neighbors >= total)):
            raise ValueError("neighbor index outside particle field")
        s1 = torch.unique(torch.cat((centers, neighbors[centers].reshape(-1))))
        s1 = s1[s1 >= 0]
        s2 = torch.unique(torch.cat((s1, neighbors[s1].reshape(-1))))
        return s1, s2[s2 >= 0]
    neighbors = np.asarray(neighbors)
    if neighbors.ndim != 2 or neighbors.dtype.kind not in "iu":
        raise ValueError("neighbors must be an integer [N,K] table")
    rows = int(neighbors.shape[0])
    total = rows if n is None else int(n)
    if total != rows or total < 0:
        raise ValueError("halo particle axis must match neighbor table")
    centers = np.asarray(centers)
    if centers.dtype.kind not in "iu":
        raise ValueError("centers must be integer indices")
    centers = centers.astype(np.int64, copy=False).reshape(-1)
    if np.any((centers < 0) | (centers >= total)):
        raise ValueError("center index outside particle field")
    if np.any((neighbors < -1) | (neighbors >= total)):
        raise ValueError("neighbor index outside particle field")
    s1 = np.unique(np.concatenate((centers, neighbors[centers].reshape(-1))))
    s1 = s1[s1 >= 0]
    s2 = np.unique(np.concatenate((s1, neighbors[s1].reshape(-1))))
    return s1, s2[s2 >= 0]


def nearest_geometry(position, geometry):
    """Exact closest finite-triangle point, not an infinite-wall approximation."""
    n = len(position)
    best = np.full(n, np.inf, dtype=np.float64)
    rel = np.zeros((n, 3), dtype=np.float64)
    normals = np.zeros_like(rel)
    velocity = np.zeros_like(rel)
    for triangle_index, triangle in enumerate(geometry.triangles):
        a, b, c = np.asarray(triangle, dtype=np.float64)
        ab, ac = b - a, c - a
        normal = np.cross(ab, ac)
        normal /= np.linalg.norm(normal)
        projected = position - np.sum((position - a) * normal, axis=1)[:, None] * normal
        p = projected - a
        aa, cc, cross = ab @ ab, ac @ ac, ab @ ac
        denominator = aa * cc - cross * cross
        u = (np.sum(p * ab, axis=1) * cc - np.sum(p * ac, axis=1) * cross) / denominator
        v = (np.sum(p * ac, axis=1) * aa - np.sum(p * ab, axis=1) * cross) / denominator
        inside = (u >= 0) & (v >= 0) & (u + v <= 1)
        candidate = projected.copy()
        dist = np.where(inside, np.sum((projected - position) ** 2, axis=1), np.inf)
        for start, end in ((a, b), (b, c), (c, a)):
            edge = end - start
            t = np.clip((position - start) @ edge / (edge @ edge), 0, 1)
            point = start + t[:, None] * edge
            d = np.sum((point - position) ** 2, axis=1)
            take = d < dist
            candidate[take] = point[take]
            dist[take] = d[take]
        take = dist < best
        best[take] = dist[take]
        rel[take] = candidate[take] - position[take]
        normals[take] = normal
        # A prescribed rigid snapshot carries its angular velocity alongside
        # the finite triangles.  Evaluate at the exact closest surface point;
        # using the triangle-centroid value here would be wrong for particles
        # at different radii from the rotation axis.  Keep the static path
        # allocation-free because it is used by every F3 training step.
        if geometry.rigid_axis_point is None:
            velocity[take] = geometry.wall_velocity[triangle_index]
        else:
            velocity[take] = geometry.wall_velocity_at(candidate, triangle_index)[take]
    return rel, normals, velocity


def node_features(state, known, dt):
    """Construct current-state causal features for every particle."""
    h = float(known.numerics["h_m"])
    dp = float(known.numerics["dp_m"])
    # Dynamic F2 uses only the declared current pose and wall speed.  The
    # geometry object itself contains no reference trajectory and materializes
    # a finite snapshot at the current state time.
    geometry = known.geometry_at(state.time_s)
    vertices = geometry.triangles.reshape(-1, 3)
    length = max(float(np.ptp(vertices, axis=0).max()) if len(vertices) else dp, dp)
    center = (vertices.max(0) + vertices.min(0)) / 2 if len(vertices) else np.zeros(3)
    speed = max(np.sqrt(9.81 * length), 1e-12)
    rel, normal, wall_v = nearest_geometry(state.position, geometry)
    acceleration = known.control.acceleration(state)
    scalar = np.array([
        dp / length,
        h / length,
        dt * speed / length,
        float(known.physics.get("reference_density_kgm3", 1000.0)) / 1000.0,
        float(known.numerics.get("viscosity_coefficient", 0.0)),
    ])
    features = np.column_stack((
        (state.position - center) / length,
        state.velocity / speed,
        rel / h,
        normal,
        wall_v / speed,
        acceleration / 9.81,
        np.broadcast_to(scalar, (state.count, 5)),
    )).astype(np.float32)
    if features.shape != (state.count, FEATURE_DIM) or not np.isfinite(features).all():
        raise ValueError("causal node features are not finite [N,23]")
    return features, acceleration


def _mlp(nin, nout, hidden=64):
    # Two hidden SiLU layers, with the final linear projection kept explicit.
    return nn.Sequential(
        nn.Linear(nin, hidden), nn.SiLU(),
        nn.Linear(hidden, hidden), nn.SiLU(),
        nn.Linear(hidden, nout),
    )


class DualIncrementModel(nn.Module):
    """MLP and two-message-passing dual-increment baselines."""

    def __init__(self, kind="graph_raw", hidden=64):
        super().__init__()
        if kind not in MODEL_KINDS:
            raise ValueError(f"unknown baseline {kind}")
        if isinstance(hidden, bool) or int(hidden) < 1:
            raise ValueError("hidden width must be positive")
        self.kind = str(kind)
        self.hidden = int(hidden)
        # Construct the common modules before graph-only modules.  With the
        # same pre-construction seed, MLP/graph baselines therefore share the
        # exact encoder and output-head initialization; graph layers consume
        # the remaining stream afterwards.  Raw and residual already share
        # the complete graph topology and remain bitwise paired.
        self.encoder = _mlp(FEATURE_DIM, self.hidden, self.hidden)
        self.head = _mlp(self.hidden, OUTPUT_DIM, self.hidden)
        if self.kind != "mlp":
            # 2H node embeddings plus relative position(3), relative
            # velocity(3), and distance(1).
            self.messages = nn.ModuleList([_mlp(2 * self.hidden + 7, self.hidden, self.hidden) for _ in range(2)])
            self.updates = nn.ModuleList([_mlp(2 * self.hidden, self.hidden, self.hidden) for _ in range(2)])
        self.register_buffer("target_scale", torch.ones(OUTPUT_DIM))

    def forward(self, features, position, neighbors, h, centers=None):
        """Predict normalized ``(dx,dv)`` rows with complete two-hop halos."""
        features = torch.as_tensor(features)
        position = torch.as_tensor(position, dtype=features.dtype, device=features.device)
        raw_neighbors = torch.as_tensor(neighbors, device=features.device)
        if raw_neighbors.dtype not in (torch.int8, torch.int16, torch.int32,
                                        torch.int64, torch.uint8):
            raise ValueError("neighbors must be an integer [N,K] table")
        neighbors = raw_neighbors.to(dtype=torch.long)
        if features.ndim != 2 or features.shape[1] != FEATURE_DIM:
            raise ValueError("features must have shape [N,23]")
        n = features.shape[0]
        if neighbors.ndim != 2 or neighbors.shape[0] != n:
            raise ValueError("neighbors must have shape [N,K]")
        if not torch.isfinite(features).all():
            raise ValueError("features must be finite")
        if position.shape != (n, 3) or not torch.isfinite(position).all():
            raise ValueError("position must be finite [N,3]")
        try:
            smoothing_length = float(h)
        except (TypeError, ValueError) as error:
            raise ValueError("positive finite smoothing length is required") from error
        if not np.isfinite(smoothing_length) or smoothing_length <= 0:
            raise ValueError("positive finite smoothing length is required")
        if centers is None:
            centers = torch.arange(n, device=features.device)
        else:
            raw_centers = torch.as_tensor(centers, device=features.device)
            if raw_centers.dtype not in (torch.int8, torch.int16, torch.int32,
                                         torch.int64, torch.uint8):
                raise ValueError("centers must be integer indices")
            centers = raw_centers.to(dtype=torch.long).reshape(-1)
        if centers.numel() and (torch.any(centers < 0) or torch.any(centers >= n)):
            raise ValueError("center index outside particle field")
        encoded = self.encoder(features)
        if self.kind == "mlp":
            return self.head(encoded[centers]) * self.target_scale

        s1, s2 = two_hop_halo(centers, neighbors, n=n)
        values = encoded[s2]
        sources = s2
        for layer, destinations in enumerate((s1, centers)):
            lookup = torch.full((n,), -1, dtype=torch.long, device=features.device)
            lookup[sources] = torch.arange(len(sources), device=features.device)
            nei = neighbors[destinations]
            valid = nei >= 0
            safe = nei.clamp_min(0)
            source_index = lookup[safe].clamp_min(0)
            target_index = lookup[destinations]
            if torch.any(target_index < 0) or torch.any(source_index < 0):
                raise RuntimeError("two-hop halo omitted a required source")
            src = values[source_index]
            dst = values[target_index]
            relative_position = (position[safe] - position[destinations, None]) / smoothing_length
            relative_velocity = features[safe, 3:6] - features[destinations, None, 3:6]
            distance = torch.linalg.vector_norm(relative_position, dim=-1, keepdim=True)
            edge = torch.cat((dst[:, None].expand_as(src), src,
                              relative_position, relative_velocity, distance), dim=-1)
            message = self.messages[layer](edge) * valid[..., None]
            aggregate = message.sum(1) / valid.sum(1).clamp_min(1)[:, None]
            values = dst + self.updates[layer](torch.cat((dst, aggregate), dim=-1))
            sources = destinations
        return self.head(values) * self.target_scale


def tensors(state, known, dt, device):
    """Build inputs and the SI-unit known-force prior ``(dx_m, dv_mps)``."""
    features, acceleration = node_features(state, known, dt)
    neighbors, diagnostics = neighbor_table(state, float(known.numerics["h_m"]))
    args = (
        torch.as_tensor(features, dtype=torch.float32, device=device),
        torch.tensor(np.asarray(state.position), dtype=torch.float32, device=device),
        torch.as_tensor(neighbors, dtype=torch.long, device=device),
        float(known.numerics["h_m"]),
    )
    prior = np.column_stack((
        state.velocity * dt + 0.5 * acceleration * dt * dt,
        acceleration * dt,
    ))
    return args, torch.as_tensor(prior, dtype=torch.float32, device=device), diagnostics


class CausalPredictorAdapter:
    """Validate and expose the shared current-state ``predict_step`` API.

    The wrapped object may be a learned predictor, an analytic baseline, or a
    test double.  The adapter forwards exactly ``(state, known, dt)`` and
    rejects legacy outputs that do not carry independent displacement and
    native velocity increments.  In particular, it has no reference-state or
    trajectory-reader argument that could make a rollout non-causal.
    """

    def __init__(self, predictor: Predictor):
        method = getattr(predictor, "predict_step", None)
        if not callable(method):
            raise TypeError("predictor must expose predict_step(state, known, dt)")
        self.predictor = predictor

    def predict_step(self, state, known, dt):
        prediction = self.predictor.predict_step(state, known, dt)
        return validate_prediction(state, prediction, dt)


class ModelPredictor:
    """Causal inference adapter that commits both displacement and velocity."""

    def __init__(self, model, device="cpu", chunk_size=256, normalization=None):
        if int(chunk_size) < 1:
            raise ValueError("positive chunk size required")
        self.model = model.to(device).eval()
        self.device = torch.device(device)
        self.chunk_size = int(chunk_size)
        self.normalization = normalization

    def predict_step(self, state, known, dt):
        args, prior, diagnostics = tensors(state, known, dt, self.device)
        if self.normalization is not None:
            features = self.normalization.normalize_features(args[0])
            args = (features, *args[1:])
        output = np.empty((state.count, OUTPUT_DIM), dtype=np.float64)
        with torch.no_grad():
            for start in range(0, state.count, self.chunk_size):
                centers = torch.arange(start, min(start + self.chunk_size, state.count), device=self.device)
                result = self.model(*args, centers=centers)
                if self.normalization is not None:
                    # The head is trained in normalized raw-target units for
                    # both raw and residual families.  Decode those units
                    # before adding the unnormalized SI prior back.
                    result = result * torch.tensor(self.normalization.target_std, device=self.device) + torch.tensor(
                        self.normalization.target_mean, device=self.device)
                if self.model.kind == "graph_residual":
                    result = result + prior[centers]
                output[start:start + len(centers)] = result.detach().cpu().numpy()
        prediction = StepPrediction(output[:, :3], output[:, 3:], diagnostics)
        return validate_prediction(state, prediction, dt)


class AnalyticPredictor:
    """Known-force and constant-velocity references for diagnostics."""

    def __init__(self, kind="constant_velocity"):
        if kind not in ("constant_velocity", "known_force", "knownforce"):
            raise ValueError("unknown analytic baseline")
        self.kind = "known_force" if kind == "knownforce" else kind

    def predict_step(self, state, known, dt):
        acceleration = known.control.acceleration(state) if self.kind == "known_force" else np.zeros_like(state.velocity)
        prediction = StepPrediction(
            state.velocity * dt + 0.5 * acceleration * dt * dt,
            acceleration * dt,
            {"baseline": self.kind, "known_force_prior": self.kind == "known_force"},
        )
        return validate_prediction(state, prediction, dt)
