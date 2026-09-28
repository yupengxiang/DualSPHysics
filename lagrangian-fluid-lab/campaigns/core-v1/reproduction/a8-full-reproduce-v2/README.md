# Core development reader bundle

From this directory, run:

```sh
python code/scripts/core_package.py --verify-bundle .
python code/scripts/core_benchmark.py verify --manifest dataset.json --data-root .
# With a registered checkpoint and explicitly selected cases:
python code/scripts/core_benchmark.py reproduce --manifest dataset.json --data-root . --checkpoint models/checkpoint-000.pt --case-id CASE_ID --output-dir ../reproduction
```

The reader path needs NumPy, SciPy and h5py. Checkpoint-backed model reproduction additionally needs PyTorch.
Build versions are recorded in environment.json. Full product reproduction requires a paired report from a distinct host.
This bundle is not a completed or scientifically qualified Core release.
