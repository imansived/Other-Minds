"""Print the divergence report.

    npm run report

Reads the stored corpus and answers the question the whole app rests on: are the
three agents actually thinking differently, or producing one voice in three
costumes?
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.analytics import print_report  # noqa: E402

if __name__ == "__main__":
    print_report()
