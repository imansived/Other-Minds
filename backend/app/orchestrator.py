"""Turn-taking.

Ported from app/page.tsx. This logic used to run in the browser, which meant the
client decided who spoke next; it belongs on the server, so it lives here now.

Turn order is semi-random rather than strict rotation, so the exchange feels
like an organic group discussion. Consecutive turns MOSTLY pass to a different
agent, but ~1 in 4 turns the same agent speaks again. The models never choose
the order themselves.
"""

import random
import re

from app.agents.registry import AGENT_IDS, AGENT_NAMES
from app.config import settings
from app.schemas import AgentId, ChatMessage

# How a person names the mind they want to hear from. Both the display name and
# the bare word, because "introspector, what do you think?" is typed at least as
# often as "The Introspector" — and an optional "the" in front of either.
#
# The bare word does mean "my gardener quit last week" summons The Gardener.
# That is accepted deliberately: the cost is one mind answering a message it was
# going to be eligible for anyway, against the cost of missing the lowercase
# summons, which is the common form and the whole point of the feature.
_SUMMONS: dict[AgentId, re.Pattern[str]] = {
    agent_id: re.compile(
        rf"\b(?:the\s+)?{re.escape(name.removeprefix('The '))}\b", re.I
    )
    for agent_id, name in AGENT_NAMES.items()
}


def last_agent_speaker(transcript: list[ChatMessage]) -> AgentId | None:
    """The last agent (not the user) to have spoken, or None."""
    for m in reversed(transcript):
        if m.role != "user":
            return m.role  # type: ignore[return-value]
    return None


def summoned(transcript: list[ChatMessage]) -> AgentId | None:
    """The mind the person asked for by name, or None if they asked for no one.

    Only the final message counts, and only when the person is the one who just
    spoke. Once a mind has answered, the summons has been served — otherwise
    "hear another mind" would keep re-electing the same one forever, because the
    name is still sitting there in the transcript.

    Exactly one name summons. Naming two is a topic, not a request ("I think the
    Gardener and the Behaviorist are both missing something"), so the ordinary
    draw handles it rather than picking one of them arbitrarily.
    """
    if not transcript:
        return None
    last = transcript[-1]
    if last.role != "user":
        return None
    named = [a for a, pattern in _SUMMONS.items() if pattern.search(last.content)]
    return named[0] if len(named) == 1 else None


def addressed(transcript: list[ChatMessage]) -> AgentId | None:
    """The one other mind the last agent turn names, or None.

    The mirror of `summoned`, one level down: there the person names a mind and
    it should answer; here a mind names another and that one has been called on.
    Same accepted trade-off — a bare word like "gardener" can match without
    being a challenge — and the same rule for two names: naming both minds is
    talking about them, not to either.

    Only counts while the last message is an agent turn. Once the person has
    spoken, they are who the room answers.
    """
    if not transcript:
        return None
    last = transcript[-1]
    if last.role == "user":
        return None
    named = [
        a
        for a, pattern in _SUMMONS.items()
        if a != last.role and pattern.search(last.content)
    ]
    return named[0] if len(named) == 1 else None


def _trading_blows(transcript: list[ChatMessage]) -> bool:
    """The last four messages are all minds, passed between only two of them.

    A quarrel between two is the point; a quarrel that has quietly shut the
    third out is not. Once it has run four turns the pull stands down and the
    ordinary draw — which treats the third mind as an equal — takes over.
    """
    tail = transcript[-4:]
    return (
        len(tail) == 4
        and all(m.role != "user" for m in tail)
        and len({m.role for m in tail}) == 2
    )


def right_of_reply(
    transcript: list[ChatMessage],
    *,
    rng: random.Random | None = None,
) -> AgentId | None:
    """The mind that was just called on, some of the time — otherwise None.

    This is what turns three monologues into an exchange. The draw is blind to
    what was said, so a mind challenged by name got the right of reply only as
    often as chance gave it: even odds after "hear another mind". Here the
    challenged mind is pulled forward by `settings.reply_pull`; when the roll
    fails the ordinary draw still runs, so the pull is never a guarantee and
    the third mind is never locked out.
    """
    target = addressed(transcript)
    if target is None or _trading_blows(transcript):
        return None
    r = rng or random
    return target if r.random() < settings.reply_pull else None


def choose_speaker(
    transcript: list[ChatMessage],
    *,
    allow_same: bool = True,
    rng: random.Random | None = None,
    address_to: AgentId | None = None,
) -> AgentId:
    """Who speaks next: the mind chosen, the mind named, the mind called on, else the draw.

    This is the entry point every client should use. Asking for a mind by name
    and getting a different one is the flaw it exists to close — the room was
    ignoring the one thing the person said unambiguously.

    `address_to` is the person choosing a mind without typing its name — replying
    to one of its messages. It is the plainest request there is, so nothing
    outranks it: not a different name in the text, not the draw, and not
    `allow_same`. An id that is not a mind is ignored rather than trusted.

    A summons beats `allow_same`: naming a mind that just spoke is a request for
    more from that mind, not a mistake to correct. Below it, a mind that was
    just challenged by another is pulled forward (see `right_of_reply`). The
    draw itself, `pick_next_speaker`, is untouched.
    """
    if address_to in AGENT_IDS:
        return address_to  # type: ignore[return-value]
    return (
        summoned(transcript)
        or right_of_reply(transcript, rng=rng)
        or pick_next_speaker(
            last_agent_speaker(transcript), allow_same=allow_same, rng=rng
        )
    )


def pick_next_speaker(
    last: AgentId | None,
    *,
    allow_same: bool = True,
    rng: random.Random | None = None,
) -> AgentId:
    """Who speaks next, given who spoke last (None when no agent has yet).

    `allow_same` is what separates the two ways a turn gets asked for, which are
    not the same request even though they run the same code.

    When the person writes a reply, the room carries on and whoever is mid-
    thought may well keep it — that is the double turn, and it is wanted.

    When the person presses "hear another mind", they have asked for someone
    else, in those words. Letting the draw return the same agent one time in
    four breaks the only promise the button makes, and it is visible: in the
    conversation that prompted this, The Introspector answered, was asked for
    another mind, and answered again. Nothing in the UI explained why.

    `rng` is injectable so tests can make the draw deterministic.
    """
    r = rng or random
    others = [a for a in AGENT_IDS if a != last]
    if last is None:
        return r.choice(AGENT_IDS)
    if allow_same and r.random() < settings.double_turn_chance:
        return last
    # A one-agent registry would leave nothing to switch to. Repeating is then
    # the only answer there is, and is better than raising.
    return r.choice(others or [last])
