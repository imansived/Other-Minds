"""Frontend invariants that have no JS test runner to live in.

There is no jest/vitest in this repo, and these three facts are each a bug that
already happened or was one edit away. test_parity.py established the pattern of
reading the frontend source from here; this keeps that in one obvious file
rather than growing the parity module sideways.

None of this renders anything. It reads the source, which is enough for the
class of regression involved: a value being changed back.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GLOBALS_CSS = (ROOT / "app" / "globals.css").read_text(encoding="utf-8")
LAYOUT_TSX = (ROOT / "app" / "layout.tsx").read_text(encoding="utf-8")
PAGE_TSX = (ROOT / "app" / "page.tsx").read_text(encoding="utf-8")
SIDEBAR_TSX = (ROOT / "app" / "components" / "Sidebar.tsx").read_text(encoding="utf-8")


def test_theme_color_matches_the_room():
    """The mobile address bar is painted from layout.tsx, the room from CSS.

    `--bg` cannot be read from a TS module, so the hex is duplicated — which
    means the two can drift and the only symptom is a mismatched bar on a phone
    that nobody testing on a desktop will ever see.
    """
    bg = re.search(r"--bg:\s*(#[0-9a-fA-F]{3,8});", GLOBALS_CSS)
    assert bg, "--bg disappeared from globals.css"
    theme = re.search(r'themeColor:\s*"(#[0-9a-fA-F]{3,8})"', LAYOUT_TSX)
    assert theme, "layout.tsx lost its themeColor — the phone bar goes default"
    assert theme.group(1).lower() == bg.group(1).lower(), (
        f"theme-color {theme.group(1)} no longer matches --bg {bg.group(1)}"
    )


def test_viewport_does_not_lock_zoom():
    """The iOS focus-zoom fix must stay the 16px input, not a scale lock.

    `maximumScale: 1` / `userScalable: false` would also stop the zoom, and
    would take pinch-zoom away from everyone who relies on it.
    """
    body = re.search(
        r"export const viewport: Viewport = \{(.*?)\n\};", LAYOUT_TSX, re.S
    )
    assert body, "the viewport export is gone"
    # Scoped to the object itself — the comment above it names both fields in
    # order to explain why they are absent.
    assert "maximumScale" not in body.group(1)
    assert "userScalable" not in body.group(1)


def test_composer_input_is_at_least_16px_on_touch():
    """Under 16px, iOS Safari zooms the viewport on focus and does not undo it.

    The field was 0.88rem, so this fired on every tap into the box. The rule is
    easy to "tidy up" back to the design value, hence the pin.
    """
    block = re.search(
        r"@media \(pointer: coarse\) \{[^}]*\.composer textarea \{([^}]*)\}",
        GLOBALS_CSS,
        re.S,
    )
    assert block, "the coarse-pointer composer font-size rule is gone"
    size = re.search(r"font-size:\s*(\d+)px", block.group(1))
    assert size and int(size.group(1)) >= 16, "composer input dropped below 16px"


def test_there_is_a_keyboard_focus_ring():
    """Tabbing through the room used to leave no visible trace at all."""
    assert ":focus-visible" in GLOBALS_CSS
    assert re.search(
        r":where\(button, a, \[tabindex\]\):focus-visible \{[^}]*outline:",
        GLOBALS_CSS,
        re.S,
    ), "the shared focus ring is gone; only ad-hoc per-control ones remain"


def test_arriving_messages_are_announced():
    """A screen reader got nothing when a mind spoke — the thread was a div."""
    assert 'role="log"' in PAGE_TSX and 'aria-live="polite"' in PAGE_TSX
    assert 'role="alert"' in PAGE_TSX, "errors are not announced"


def test_hear_another_mind_still_exists():
    """The sequential rhythm IS the product: one mind, then the reader chooses.

    Losing this button turns the app into "click three times for three answers".
    """
    assert "hear another mind" in PAGE_TSX
    # ...and it must ask for a DIFFERENT mind, which is what the button says.
    assert "runTurn(transcript, false)" in PAGE_TSX


def test_send_button_hits_the_touch_target_guideline():
    """Found by an actual headless-Chromium check at an iPhone-width viewport,
    not by reading the CSS: `.icon-btn` was correctly bumped to 44px under
    `(pointer: coarse)`, but `.send` — the composer's primary action — was left
    at 42px right below it. Every source-grep check in this file would have
    passed; only measuring the real rendered box caught the 2px gap.
    """
    block = re.search(
        r"@media \(pointer: coarse\) \{.*?\.send \{([^}]*)\}",
        GLOBALS_CSS,
        re.S,
    )
    assert block, "the coarse-pointer .send rule is gone"
    width = re.search(r"width:\s*(\d+)px", block.group(1))
    height = re.search(r"height:\s*(\d+)px", block.group(1))
    assert width and int(width.group(1)) >= 44, ".send width dropped below 44px"
    assert height and int(height.group(1)) >= 44, ".send height dropped below 44px"


def test_sidebar_hidden_state_accounts_for_the_mobile_viewport():
    """`aria-hidden={collapsed && !mobileOpen}` looked right and passed every
    prior test, because it happens to be correct on desktop, where `mobileOpen`
    never turns true. On an actual phone it was wrong for the "closed" half of
    the cycle, INCLUDING first render — collapsed and mobileOpen both start
    false, and the sidebar is in fact off-screen there the whole time via
    `transform: translateX(-100%)`. A headless-Chromium check caught it by
    literally calling `.focus()` on a button inside the visually-hidden
    sidebar and watching it succeed. Grepping source cannot catch a bug that is
    about which STATE means "shown" disagreeing between CSS and JS; this can
    only pin the shape of the actual fix.
    """
    assert "matchMedia" in SIDEBAR_TSX, (
        "the sidebar lost its real viewport check and is back to guessing "
        "visibility from `collapsed` alone"
    )
    # The bug, precisely: these two attributes driven straight off the
    # desktop-only formula. A mention of that formula in an explanatory
    # comment is fine and expected; it must not be what aria-hidden/inert
    # actually evaluate.
    assert not re.search(r"aria-hidden=\{collapsed && !mobileOpen\}", SIDEBAR_TSX), (
        "aria-hidden is back to the desktop-only formula — this is the exact regression"
    )
    assert not re.search(r"inert=\{collapsed && !mobileOpen\}", SIDEBAR_TSX), (
        "inert is back to the desktop-only formula — this is the exact regression"
    )
    assert re.search(r"aria-hidden=\{hidden\}", SIDEBAR_TSX)
    assert re.search(r"inert=\{hidden\}", SIDEBAR_TSX)
