"""The build stamp, and what it is for.

A round of prompt tuning was invalidated by a uvicorn process that had been
running since before the prompts changed. The transcript it produced was read
as evidence about the current code; it was evidence about a build nobody could
name. These tests hold the two properties that make that detectable.
"""

import pytest
from fastapi.testclient import TestClient

import app.build as build
from app.build import BUILD, fingerprint
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_reports_the_loaded_build(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["build"] == BUILD
    assert isinstance(body["started_at"], int)
    # The model belongs here for the same reason: tuning measured on one model
    # and shipped on another is the same mistake wearing different clothes.
    assert body["model"]


def test_the_stamp_is_frozen_at_import():
    """BUILD must NOT track the disk.

    This is the whole mechanism. If the constant recomputed itself, a stale
    process would report the fingerprint of code it does not have — agreeing
    with disk in exactly the case the check exists to catch.
    """
    prompt = build.APP_DIR / "agents" / "prompts" / "introspector.md"
    original = prompt.read_bytes()
    before = fingerprint()
    try:
        prompt.write_bytes(original + b"\nan edit that is not loaded\n")
        assert fingerprint() != before, "editing a prompt must change the fingerprint"
        assert BUILD == before, "BUILD tracked the disk; it must be frozen at import"
    finally:
        prompt.write_bytes(original)
    assert fingerprint() == before


def test_prompts_are_part_of_the_build():
    """The prompts ARE the product.

    Hashing only .py would let a prompt edit ship silently — and a prompt edit
    without a restart leaves no other trace anywhere in the system.
    """
    assert any(pattern.endswith("*.md") for pattern in build.SOURCES)


def test_line_endings_do_not_change_the_build():
    """A CRLF checkout is the same build as an LF one.

    Without normalisation this fires on every Windows clone, and a check that
    cries wolf is worse than no check. The file is converted THROUGH LF rather
    than by a blind newline substitution: this checkout is already CRLF, and
    doubling the carriage returns would test a file shape nobody ships.
    """
    src = build.APP_DIR / "config.py"
    original = src.read_bytes()
    before = fingerprint()
    as_lf = original.replace(b"\r\n", b"\n")
    try:
        src.write_bytes(as_lf)
        assert fingerprint() == before, "LF changed the fingerprint"
        src.write_bytes(as_lf.replace(b"\n", b"\r\n"))
        assert fingerprint() == before, "CRLF changed the fingerprint"
    finally:
        src.write_bytes(original)
