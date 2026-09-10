"""Is the running API serving the code that is on disk?

    npm run check

Answers the one question that invalidated a whole round of prompt tuning: a
correct file is not a running server. Prints the model too, because tuning
measured against one model and shipped on another is the same class of mistake
made a different way.

Exit status is meaningful, so this can gate a test run:
    0  in step        2  behind (restart it)
    1  unreachable    3  reachable but too old to report a build
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.build import fingerprint  # noqa: E402
from app.config import settings  # noqa: E402

API_URL = os.environ.get("OTHER_MINDS_API_URL", "http://127.0.0.1:8000")


def main() -> int:
    on_disk = fingerprint()
    try:
        with urllib.request.urlopen(f"{API_URL}/health", timeout=5) as res:
            health = json.load(res)
    except (urllib.error.URLError, OSError) as err:
        print(f"unreachable  {API_URL}/health - {err}")
        print("\nNothing is running there. Start it with:\n  npm run dev:api")
        return 1

    running = health.get("build")
    if running is None:
        # A build old enough to predate this field is, by definition, behind.
        print(f"behind       {API_URL} answers /health but reports no build.")
        print(f"             That version predates the stamp itself. Restart it.")
        return 3

    print(f"disk         {on_disk}")
    print(f"running      {running}")
    print(f"model        {health.get('model')}  (config says {settings.model})")

    if running != on_disk:
        print(
            "\nBEHIND - the server is serving older code than you are reading.\n"
            "Anything you measure against it is evidence about the old build.\n"
            "Restart it:\n  npm run dev:api"
        )
        return 2

    print("\nin step - the API is running the code on disk.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
