"""Registered F3 spatial observations; never extrapolate short source runs."""

import json
from pathlib import Path
import h5py, numpy as np
from scripts.l1r_continuation_evidence import LAB, OUT, write
from scripts.l1r_cpu_slots import cpu_slot


def observe(record, times, *, path=None):
    path = path or LAB / "campaigns/l1-resume/data/continuation" / (record["id"] + ".h5")
    result = []
    with h5py.File(path, "r") as h:
        native = h["time"][:]
        initial = np.nansum(h["mass"][0])
        edges = [
            np.arange(-0.45, 0.451, 0.06),
            np.arange(-0.09, 0.091, 0.06),
            np.r_[np.arange(0, 0.51, 0.06), 0.51],
        ]
        for target in times:
            if target < native[0] or target > native[-1]:
                raise ValueError("observation outside actual trajectory")
            fi = int(np.argmin(abs(native - target)))
            valid = h["valid"][fi]
            p = h["position"][fi][valid]
            v = h["velocity"][fi][valid]
            m = h["mass"][fi][valid].astype(float)
            bins = np.histogramdd(p, bins=edges, weights=m)[0].ravel() / initial
            outside = m.sum() / initial - bins.sum()
            hist = np.r_[bins, outside, 1 - m.sum() / initial]
            result.append(
                {
                    "target_s": target,
                    "actual_s": float(native[fi]),
                    "hist": hist,
                    "com": np.average(p, axis=0, weights=m),
                    "q90": float(np.quantile(p[:, 0], 0.9)),
                    "mean_velocity": np.average(v, axis=0, weights=m),
                    "mass_fraction": float(m.sum() / initial),
                }
            )
    return result


def main():
    gates = json.loads((OUT / "F3-GATES.json").read_text())
    records = json.loads((OUT / "F3-INPUT-REPAIR-READY.json").read_text())["records"]
    pairs = []
    for background in gates["backgrounds"]:
        group = [r for r in records if r["background_id"] == background]
        values = [observe(r, gates["observation_times_s"]) for r in group]
        for i in range(2):
            rows = []
            for a, b in zip(values[i], values[i + 1]):
                rows.append(
                    {
                        "requested_s": a["target_s"],
                        "actual_time_s": [a["actual_s"], b["actual_s"]],
                        "tv": float(0.5 * np.abs(a["hist"] - b["hist"]).sum()),
                        "com_l2_over_length": float(
                            np.linalg.norm(a["com"] - b["com"]) / 0.9
                        ),
                        "front_q90_difference_over_length": abs(a["q90"] - b["q90"])
                        / 0.9,
                        "mean_velocity_difference_over_sqrt_gH": float(
                            np.linalg.norm(a["mean_velocity"] - b["mean_velocity"])
                            / np.sqrt(9.81 * 0.09)
                        ),
                    }
                )
            maxima = {
                key: max(r[key] for r in rows)
                for key in (
                    "tv",
                    "com_l2_over_length",
                    "front_q90_difference_over_length",
                    "mean_velocity_difference_over_sqrt_gH",
                )
            }
            pairs.append(
                {
                    "background": background,
                    "cases": [group[i]["id"], group[i + 1]["id"]],
                    "maxima": maxima,
                    "registered_screen_pass": all(v <= 0.05 for v in maxima.values()),
                    "observations": rows,
                }
            )
    write(
        "F3-SPATIAL-RESULTS.json",
        {
            "pairs": pairs,
            "qualification_scope": "registered spatial observations only; hard gates, time qualification and material fidelity remain separate",
        },
    )


if __name__ == "__main__":
    with cpu_slot():
        main()
