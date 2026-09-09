"""Q1 probe alignment and descriptive errors, without pressure support imputation."""

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scripts.l1r_continuation_evidence import OUT, write
from scripts import r4_f1_test02_event_window as ref


def main():
    exp = pd.read_excel(ref.EXPERIMENT, sheet_name="Experimental_data")
    et = exp["Time (s)"].to_numpy(float)
    metrics = {}
    fig, axes = plt.subplots(4, 2, figsize=(12, 12), sharex=True)
    for kind, prefix, count, unit in [
        ("elevation", "H", 4, "m"),
        ("pressure", "P", 8, "Pa"),
    ]:
        frame = ref.read_measure_csv(
            OUT
            / "q1-measure"
            / (
                "elevation_Elevation.csv"
                if kind == "elevation"
                else "pressure_Press.csv"
            )
        )
        st = frame["Time [s]"].to_numpy(float)
        cols = [
            c
            for c in frame
            if c.startswith("Elevation_" if kind == "elevation" else "Press_")
        ]
        for i, c in enumerate(cols[:count]):
            name = f"{prefix}{i+1}"
            ev = exp[f"{name} ({unit})"].to_numpy(float)
            sv = frame[c].to_numpy(float)
            em = np.isfinite(et) & np.isfinite(ev)
            m = np.isfinite(sv) & (st >= et[em].min()) & (st <= et[em].max())
            target = np.interp(st[m], et[em], ev[em])
            err = sv[m] - target
            metrics[name] = {
                "rmse": float(np.sqrt(np.mean(err**2))),
                "mae": float(np.mean(abs(err))),
                "unit": unit,
                "overlap_samples": int(m.sum()),
                "finite_sim_samples": int(np.isfinite(sv).sum()),
                "sampling_interval_max_s": float(np.diff(st).max()),
                "acceptance_status": (
                    (
                        "limited_macro_anchor_only"
                        if name in ("H2", "H4")
                        else "not_qualified_external_mismatch"
                    )
                    if kind == "elevation"
                    else "not_qualified_support_and_peak_cadence_unresolved"
                ),
                "zero_values_semantics": "native tool output; not replaced or assumed valid pressure support",
            }
            if kind == "elevation":
                axes[i, 0].plot(et[em], ev[em], label="experiment", lw=1)
                axes[i, 0].plot(st, sv, label="Q1", lw=1)
                axes[i, 0].set_ylabel(name + " (m)")
                axes[i, 1].plot(st[m], err, lw=1)
                axes[i, 1].set_ylabel(name + " error (m)")
    axes[0, 0].legend()
    axes[0, 0].set_xlim(0, 6)
    axes[-1, 0].set_xlabel("time (s)")
    axes[-1, 1].set_xlabel("time (s)")
    fig.tight_layout()
    fig.savefig(OUT / "Q1-ELEVATION-COMPARISON.png", dpi=160)
    plt.close(fig)
    write(
        "Q1-OBSERVABLES.json",
        {
            "experimental_workbook": ref.sha256(ref.EXPERIMENT),
            "alignment": {
                "units": "metres, seconds, pascals",
                "time_zero": "native simulation t=0 and workbook Time (s); no fitted time shift",
                "probes": "official elevation.txt and pressure.txt; exact positions in CSV headers",
                "interpolation": "experimental values linearly interpolated only within finite overlap to native saved times",
            },
            "metrics": metrics,
            "qualification": "H2/H4 retain only the limited macro-observable use established in W05-CONCLUSION.md, with current errors explicitly reported. No new scalar pass threshold or full physical positive-control acceptance is inferred; H1/H3 show substantial mismatches.",
            "pressure_support": "kcusedummy disabled but native zero is not proof of supported sampling; pressure qualification withheld",
        },
    )


if __name__ == "__main__":
    main()
