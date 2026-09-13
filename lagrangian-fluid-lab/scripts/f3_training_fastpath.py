"""Runtime-only GPU training update for complete-axis cached batches."""

from __future__ import annotations

import numpy as np
import torch

from scripts import f3_training_core as core
from scripts.f3_learning_inputs import SPEED, features
from scripts.f3_local_neighbors import exact_local_summary_selected


def local_step(state, loader):
    """Mirror one core update while querying local features for selected rows."""
    core._live(state)
    if state.early_stop or state.global_step >= state.config.max_steps:
        raise ValueError("early stop or declared maximum step bound reached")
    try:
        with core._rng_scope(state), torch.enable_grad():
            if state.cursor == len(state.order):
                state.epoch += 1
                state.cursor = 0
                state.order = list(range(len(state.transitions)))
                if state.config.shuffle:
                    state.rng.shuffle(state.order)
            transition = state.transitions[state.order[state.cursor]]
            batch = loader(transition)
            p, v, ids, displacement = core._batch_tensors(state, batch)
            candidates = (np.arange(len(p), dtype=np.int64)
                          if transition.target_indices is None
                          else np.asarray(transition.target_indices, dtype=np.int64))
            if candidates.max() >= len(p):
                raise ValueError("declared target row is outside the complete particle axis")
            count = (len(candidates) if state.config.max_targets is None
                     else min(len(candidates), state.config.max_targets))
            selected = (candidates if count == len(candidates)
                        else state.rng.choice(candidates, size=count, replace=False))
            row = torch.as_tensor(selected, dtype=torch.long, device=state.device)
            base = features(p[row], v[row], time_s=batch.time_s, interval_s=batch.interval_s,
                            dp_m=batch.dp_m, amplitude=batch.amplitude, control=batch.control)
            local = exact_local_summary_selected(p, v, ids, row.detach().cpu().numpy(),
                                                  dp_m=batch.dp_m, interval_s=batch.interval_s)
            state.model.train()
            state.optimizer.zero_grad(set_to_none=True)
            raw = state.model(base, local)
            target = displacement[row] / (SPEED * batch.interval_s)
            if raw.shape != target.shape or not core._finite(raw) or not core._finite(target):
                raise ValueError("invalid raw prediction or normalized target")
            loss = (raw - target).square().mean()
            if not core._finite(loss):
                raise ValueError("nonfinite training loss")
            loss.backward()
            if any(parameter.grad is None or not core._finite(parameter.grad)
                   for parameter in state.model.parameters()):
                raise ValueError("missing or nonfinite gradients")
            state.optimizer.step()
            if not core._finite(state.model.state_dict()) or not core._finite(state.optimizer.state_dict()):
                raise ValueError("nonfinite parameters or AdamW state")
            state.optimizer.zero_grad(set_to_none=True)
            state.cursor += 1
            state.global_step += 1
            return dict(case_id=transition.case_id, frame=transition.frame,
                        target_indices=selected.tolist(),
                        sampled_particle_ids=[int(value) for value in ids[selected]],
                        particle_count=len(p), epoch=state.epoch, global_step=state.global_step,
                        loss=float(loss.detach().cpu()))
    except BaseException as error:
        state.failed_reason = f"{type(error).__name__}: {error}"
        raise
