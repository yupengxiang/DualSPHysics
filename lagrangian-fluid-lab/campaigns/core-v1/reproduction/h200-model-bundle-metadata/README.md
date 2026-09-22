# Core development reader bundle

From this directory, run:

```sh
python code/scripts/core_package.py --verify-bundle .
python code/scripts/core_benchmark.py verify --manifest dataset.json --data-root .
```

The bundled code needs NumPy, SciPy, h5py and PyTorch. Build versions are recorded in environment.json.
This bundle is not a completed or scientifically qualified Core release.
