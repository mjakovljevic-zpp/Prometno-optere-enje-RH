"""Orkestrator: pokreni svih 5 koraka uzastopno.

  python scripts/run_pipeline.py

Svaki korak je samostalna skripta, pa se mogu pokretati i pojedinacno.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = [
    "01_load_clean_data.py",
    "02_match_counters_to_network.py",
    "03_assign_traffic_to_sections.py",
    "04_export_web_data.py",
    "05_quality_report.py",
]


def main():
    for step in STEPS:
        print(f"\n=== {step} ===", flush=True)
        rc = subprocess.run([sys.executable, str(HERE / step)]).returncode
        if rc != 0:
            print(f"!! {step} pao s exit-code {rc}", flush=True)
            sys.exit(rc)
    print("\nPipeline gotov.")


if __name__ == "__main__":
    main()
