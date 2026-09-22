# Core A8 checkpoint reproduction bundle

This immutable bundle uses the registered F3 v2 dataset and one seed17 update16
preprofile MLP checkpoint. The F3 H5/NPZ assets are shared hardlinks from
`ada-identical-h200-bundle-v3`; their content hashes are unchanged.

Run from this directory:

```sh
python code/scripts/core_package.py --verify-bundle .
python code/scripts/core_benchmark.py verify --manifest dataset.json --data-root . --case-id F3_DEV_08_a0p953125 --full-scan
python code/scripts/core_benchmark.py reproduce --manifest dataset.json --data-root . \
  --checkpoint models/checkpoint-000.pt --case-id F3_DEV_08_a0p953125 \
  --source-host h200 --device cuda --output-dir ../a8-attempt/reproduction
```

This is a diagnostic full-horizon product reproduction. It is not a formal
training run or scientific qualification. A full-product claim requires a
second report from an actually distinct host and the paired comparator.
