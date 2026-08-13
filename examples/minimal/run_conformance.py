"""Run the core conformance suite against the minimal example provider.

Usage: pip install ../../conformance && python run_conformance.py
Exit code 0 when every vector passes; failures print their ids and details.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from provider import FakeProvider  # noqa: E402

from uap_core.conformance import run_core_conformance  # noqa: E402


def main() -> int:
    report = asyncio.run(run_core_conformance(FakeProvider()))
    for result in report.results:
        state = "SKIP" if result.skipped else ("PASS" if result.passed else "FAIL")
        line = f"{state:4} {result.id}"
        if result.detail:
            line += f" — {result.detail}"
        print(line)
    print(f"{'PASS' if report.passed else 'FAIL'}: {report.provider}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
