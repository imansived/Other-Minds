"""What code this process is actually running.

Exists because of a failure that cost a whole round of prompt work: the app was
tested against a uvicorn process started before the prompts changed, and the
transcript it produced was read as evidence about the current code. It was not.
Turns measured at 149/142/209 words came back at 60/11/29 when the same
transcript was replayed through what was on disk.

A file being correct is not the same as the server having it, and nothing in
the app made the difference visible. So the process stamps, at import time, a
fingerprint of the source it loaded. `/health` reports that stamp; anything that
can read the disk can recompute the fingerprint and compare. A mismatch means
the process is behind, and says so instead of quietly serving stale prompts.

Frozen at import ON PURPOSE. Recomputing it inside the handler would read the
NEW files from disk and report the very build the process does not have — the
number would agree with disk precisely when it matters least.
"""

import hashlib
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent

# Everything whose contents change agent behaviour. The prompts are included
# because they are the product: editing a .md and not restarting is exactly the
# failure this module exists to catch, and it leaves no other trace.
SOURCES = ("**/*.py", "agents/prompts/*.md")


def fingerprint() -> str:
    """A short hash of the source on disk right now.

    Path-and-content, sorted, so it is stable across platforms and independent
    of filesystem order. Newlines are normalised: a checkout with CRLF endings
    is the same build as one with LF, and treating it as different would make
    this fire on Windows for no reason.
    """
    h = hashlib.sha256()
    seen: set[Path] = set()
    for pattern in SOURCES:
        for path in sorted(APP_DIR.glob(pattern)):
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            h.update(str(path.relative_to(APP_DIR)).replace("\\", "/").encode())
            h.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:12]


# The two facts a stale process cannot fake: what it loaded, and when.
BUILD = fingerprint()
STARTED_AT = int(time.time() * 1000)
