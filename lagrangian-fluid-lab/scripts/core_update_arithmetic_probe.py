#!/usr/bin/env python3
"""Replay a captured update MLP; diagnostic only, never changes a predictor."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--expected-sha256', required=True)
    p.add_argument('--device', choices=('cpu', 'cuda'), required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if sha(args.input) != args.expected_sha256:
        raise ValueError('replay input hash mismatch')
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    arrays, evidence = {}, {}
    with np.load(args.input, allow_pickle=False) as data, torch.no_grad():
        for label, dtype in [('float32', torch.float32), ('float64', torch.float64)]:
            x = torch.tensor(data['update_input'], dtype=dtype, device=args.device)
            for layer in (0, 2, 4):
                weight = torch.tensor(data[f'updates.0.{layer}.weight'], dtype=dtype, device=args.device)
                bias = torch.tensor(data[f'updates.0.{layer}.bias'], dtype=dtype, device=args.device)
                x = F.linear(x, weight, bias)
                arrays[f'{label}_linear_{layer}'] = x.cpu().numpy()
                if layer != 4:
                    x = F.silu(x)
                    arrays[f'{label}_silu_{layer}'] = x.cpu().numpy()
            x = x + torch.tensor(data['residual_input'], dtype=dtype, device=args.device)
            value = x.cpu().numpy()
            arrays[f'{label}_updated'] = value
            if not np.isfinite(value).all():
                raise ValueError('nonfinite update replay')
            evidence[label] = {host: {'exact_equal': bool(np.array_equal(value, data[f'{host}_updated'])),
                'max_abs_error': float(np.max(np.abs(value.astype(np.float64) - data[f'{host}_updated'])))}
                for host in ('ada', 'h200')}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    array_path = args.output.with_suffix('.npz')
    np.savez_compressed(array_path, **arrays)
    report = {'schema': 'core.update_arithmetic_probe.v1', 'input_sha256': sha(args.input),
        'code_sha256': sha(__file__), 'device': args.device, 'torch': torch.__version__,
        'cuda': torch.version.cuda, 'gpu_name': torch.cuda.get_device_name() if args.device == 'cuda' else None,
        'arrays': {'path': array_path.name, 'sha256': sha(array_path)}, 'captured_comparison': evidence,
        'scope': 'isolated update MLP, original float32 weights promoted for float64 diagnostic; no rollout or qualification claim'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
