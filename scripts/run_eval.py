#!/usr/bin/env python3
"""APIL Integrity Lab Evaluation CLI Runner.

Executes the 21-run benchmark matrix (7 scenarios x 3 system configurations)
and exports results to JSON.
"""

import asyncio
import json
import os
import sys

# Ensure backend app is in PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from app.lab.benchmark import IntegrityLab


async def main():
    print("=" * 70)
    print("  AGENT PAYMENT INTEGRITY LAYER (APIL) — BENCHMARK EVALUATOR")
    print("  Evaluating Scenarios A through G against Baselines A, B, and APIL")
    print("=" * 70)

    lab = IntegrityLab()
    report = await lab.run_full_benchmark()

    print("\nSYSTEM EVALUATION SUMMARY:")
    print("-" * 70)
    print(f"{'Configuration':<25} | {'Pass Rate':<12} | {'Unauth Spends':<15} | {'Avg Latency'}")
    print("-" * 70)

    for sys_name, metrics in report.summary_by_system.items():
        name_display = {
            "PROPOSED_APIL": "Proposed APIL",
            "BASELINE_A": "Baseline A (No Gate)",
            "BASELINE_B": "Baseline B (Static)",
        }.get(sys_name, sys_name)
        print(
            f"{name_display:<25} | {str(metrics['pass_rate_pct']) + '%':<12} | "
            f"{str(metrics['unauthorized_spend_count']):<15} | {metrics['avg_latency_ms']} ms"
        )

    print("-" * 70)

    output_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "docs", "BENCHMARK_RESULTS.json")
    )
    with open(output_path, "w") as f:
        json.dump(report.model_dump(), f, indent=2)

    print(f"\n[✓] Detailed evaluation metrics written to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
