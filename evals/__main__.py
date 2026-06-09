"""Run the Highway Bites agent against the spec eval cases.

Usage:
    .venv/bin/python -m evals                # run all 8 cases
    .venv/bin/python -m evals 1 4 8          # run only cases 1, 4, 8
    .venv/bin/python -m evals --list         # list cases without running

Each run hits the real OpenAI API (~5-10 calls per case). Costs add up if you
loop on this — use case selection while iterating on prompts/tools, then run
the full suite before committing.
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from evals.cases import CASES, get_case
from evals.report import format_report
from evals.runner import run_case


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "case_ids", nargs="*", type=int,
        help="Specific case numbers to run (e.g. `1 4 8`). Default: all.",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List all eval cases and exit without running.",
    )
    args = parser.parse_args()

    if args.list:
        last_category = None
        for c in CASES:
            if c.category != last_category:
                print(f"\n  [{c.category}]")
                last_category = c.category
            print(f"    #{c.case_id:>2}  {c.name}")
            print(f"          ↳ {c.catches}")
        return 0

    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY is not set. Add it to .env or export it.",
              file=sys.stderr)
        return 1

    selected = [get_case(cid) for cid in args.case_ids] if args.case_ids else CASES
    print(f"Running {len(selected)} eval case(s) against model="
          f"{os.getenv('OPENAI_MODEL', 'gpt-4o-mini')}...")

    results = []
    for case in selected:
        print(f"  ▶ #{case.case_id} {case.name}...", end="", flush=True)
        result = run_case(case)
        results.append(result)
        print(" ✓" if result.passed else " ✗")

    print(format_report(results))

    return 0 if all(r.passed for r in results) else 2


if __name__ == "__main__":
    sys.exit(main())
