"""Regenerate the machine-readable and Markdown canonical-geometry audits."""

from .probe import write_report


if __name__ == "__main__":
    report = write_report()
    print(
        "canonical geometry: "
        f"{report['status']} "
        f"({len(report['cases'])} cases)"
    )
