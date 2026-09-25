"""Print the divergence report.

    npm run report
    npm run report -- --build current
    npm run report -- --build 4f2a1c9d0e3b
    npm run report -- --builds

Reads the stored corpus and answers the question the whole app rests on: are the
three agents actually thinking differently, or producing one voice in three
costumes?

`--build` exists because the corpus otherwise pools every prompt revision ever
run into one number. Before this a change to the prompts could only be checked
by spending fresh API quota on a new scenario run — the stored turns from
before and after the edit were indistinguishable. `current` means "this
checkout's fingerprint" (app/build.py); pass a specific hash from `--builds` to
look at an older revision instead.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.analytics import available_builds, print_report  # noqa: E402
from app.build import BUILD  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build",
        help='filter chat-feel to one prompt revision; "current" means this checkout',
    )
    parser.add_argument(
        "--builds",
        action="store_true",
        help="list every build fingerprint seen in the corpus, then exit",
    )
    args = parser.parse_args()

    if args.builds:
        rows = available_builds()
        if not rows:
            print("no generations recorded yet")
        for row in rows:
            here = "  <- this checkout" if row["build"] == BUILD else ""
            print(f"  {row['build']:14s} {row['turns']:>5} turns{here}")
        sys.exit(0)

    build = BUILD if args.build == "current" else args.build
    print_report(build=build)
