"""Run the core conformance suite against the minimal example provider.

Usage: pip install ../../conformance && python run_conformance.py

Exit code 0 when the run EARNS assurance level A (verified semantic control): nothing failed, and no core vector went
ungraded. A skip is not a pass — a provider that offers nothing addressable can be probed by
nothing at all, and verdicting on "did anything fail" handed such a run a clean exit.
Skips of the optional-feature vectors (preview, cancellation, an undo never claimed) are
honest absences and do not disqualify.
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
    for result in report.unproven:
        print(f"UNPROVEN {result.id} — {result.detail}")
    earned = report.earns_control_ready
    print(f"{'PASS' if earned else 'FAIL'}: {report.provider}")
    return 0 if earned else 1


if __name__ == "__main__":
    raise SystemExit(main())
