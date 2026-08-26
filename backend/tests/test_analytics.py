"""Divergence analytics.

The corpus here is synthetic and deliberately so: these tests are about whether
the *metric* is trustworthy, not about what the real agents said. The load-
bearing test is `test_identical_voices_are_reported_as_not_distinguishable` —
a divergence check that always reports "distinct" would be worse than no check
at all, so it has to be shown failing when it should.
"""

import random

import pytest

from app import analytics, store
from app.config import settings
from app.schemas import ChatMessage


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "analytics.db"))
    store.init_db()
    yield


# Three vocabularies with no overlap beyond ordinary glue words, standing in for
# three genuinely different ways of talking.
VOICES = {
    "introspector": [
        "when you picture doing it what do you feel dread or relief",
        "you mentioned that twice and skipped past it both times",
        "the word you chose is stronger than the situation warrants",
        "imagine actually saying yes and notice what happens in you",
    ],
    "behaviorist": [
        "what have you actually tried and what followed from it",
        "six years is a record so let us look at the record",
        "pick one small thing you can do this week and do it",
        "you said you would call them last month did you call",
    ],
    "gardener": [
        "who else is affected by this and have you asked them",
        "you are treating the arrangement as fixed when it is not",
        "have you said any of this out loud to the people involved",
        "does this actually have to be settled right now",
    ],
}


def seed(voices: dict[str, list[str]], per_agent: int = 12) -> None:
    """Write `per_agent` turns for each agent, spread over conversations."""
    rng = random.Random(7)
    rows: list[tuple[str, str]] = []
    for agent, lines in voices.items():
        for i in range(per_agent):
            rows.append((agent, f"{rng.choice(lines)} {rng.choice(lines)}"))
    rng.shuffle(rows)

    per_convo = 6
    for c in range(0, len(rows), per_convo):
        chunk = rows[c : c + per_convo]
        transcript = [ChatMessage(role="user", content="a question")]
        transcript += [ChatMessage(role=a, content=t) for a, t in chunk]
        store.save_conversation(f"c{c}", "a question", transcript)


def test_empty_corpus_is_reported_not_crashed():
    report = analytics.divergence_report()
    assert report["available"] is False
    assert "no stored agent turns" in report["reason"]
    assert report["corpus"]["turns"] == 0


def test_user_messages_are_not_counted_as_turns():
    store.save_conversation(
        "c1", "t",
        [
            ChatMessage(role="user", content="hello"),
            ChatMessage(role="gardener", content="who else is in this"),
            ChatMessage(role="user", content="just me"),
        ],
    )
    turns = analytics.turns_frame()
    assert len(turns) == 1
    assert turns.iloc[0]["agent"] == "gardener"


def test_corpus_counts_and_length_profile():
    seed(VOICES, per_agent=10)
    report = analytics.divergence_report()
    assert report["available"] is True
    assert report["corpus"]["turns"] == 30
    assert report["corpus"]["turns_per_agent"] == {
        "introspector": 10, "behaviorist": 10, "gardener": 10,
    }
    for agent, stats in report["length"].items():
        assert stats["turns"] == 10
        assert stats["mean_words"] > 0
        assert stats["min_words"] <= stats["median_words"] <= stats["max_words"]


def test_separability_refuses_a_corpus_too_small_to_judge():
    seed(VOICES, per_agent=3)
    result = analytics.divergence_report()["separability"]
    assert result["available"] is False
    assert "at least" in result["reason"]


def test_distinct_voices_are_detected():
    seed(VOICES, per_agent=14)
    result = analytics.divergence_report()["separability"]
    assert result["available"] is True
    assert result["accuracy"] > result["chance"] + 0.30
    assert result["verdict"] == "distinct"
    # Every agent should be recognisable, not just one carrying the average.
    for agent, recall in result["recall_per_agent"].items():
        assert recall > 0.5, f"{agent} is not being recognised: {recall}"


def test_identical_voices_are_reported_as_not_distinguishable():
    """The test that gives the metric its meaning.

    All three agents draw from one shared pool, so there is nothing to learn.
    If this still reported "distinct", every other result here would be
    worthless.
    """
    shared = sum(VOICES.values(), [])
    flat = {agent: shared for agent in VOICES}
    seed(flat, per_agent=14)

    result = analytics.divergence_report()["separability"]
    assert result["available"] is True
    assert result["accuracy"] < result["chance"] + 0.15, (
        f"identical voices scored {result['accuracy']} — the metric is not "
        f"measuring what it claims to"
    )
    assert result["verdict"] == "not distinguishable"


def test_identical_voices_also_look_lexically_similar():
    shared = sum(VOICES.values(), [])
    seed({agent: shared for agent in VOICES}, per_agent=12)
    same = analytics.divergence_report()["lexical_similarity"]["mean_pairwise"]

    store.init_db()
    with store.connect() as conn:
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM conversations")
    seed(VOICES, per_agent=12)
    distinct = analytics.divergence_report()["lexical_similarity"]["mean_pairwise"]

    assert same > distinct, (
        f"pooled similarity did not separate identical ({same}) from "
        f"distinct ({distinct}) voices"
    )


def test_distinctive_terms_pick_out_each_voice():
    seed(VOICES, per_agent=12)
    terms = analytics.divergence_report()["distinctive_terms"]
    gardener = " ".join(t["term"] for t in terms["gardener"])
    behaviorist = " ".join(t["term"] for t in terms["behaviorist"])
    introspector = " ".join(t["term"] for t in terms["introspector"])
    # Content words, not glue: the list is meant to be read by a person
    # deciding whether a prompt needs editing.
    assert any(w in gardener for w in ("affected", "involved", "asked", "settled"))
    assert any(w in behaviorist for w in ("record", "tried", "followed", "week"))
    assert any(w in introspector for w in ("dread", "relief", "picture", "notice"))


def test_turn_taking_measures_the_configured_repeat_rate():
    """A corpus with no repeats should read as 0, not as the configured rate."""
    transcript = [ChatMessage(role="user", content="q")]
    for agent in ["introspector", "behaviorist", "gardener"] * 4:
        transcript.append(ChatMessage(role=agent, content="something said"))
    store.save_conversation("c1", "q", transcript)

    result = analytics.divergence_report()["turn_taking"]
    assert result["transitions"] == 11
    assert result["repeats"] == 0
    assert result["observed_rate"] == 0.0
    assert result["expected_rate"] == settings.double_turn_chance
    # 11 transitions is too few to judge: at that size the interval around a
    # 25% rate is wider than 25%, so even zero repeats sits "within 2 SE". The
    # report has to say so rather than implying the rule was verified.
    assert result["sufficient_data"] is False


def test_turn_taking_flags_a_real_deviation_once_there_is_enough_data():
    """With enough transitions, an all-rotation corpus is correctly called out."""
    for c in range(6):
        transcript = [ChatMessage(role="user", content="q")]
        for agent in ["introspector", "behaviorist", "gardener"] * 3:
            transcript.append(ChatMessage(role=agent, content="something said"))
        store.save_conversation(f"c{c}", "q", transcript)

    result = analytics.divergence_report()["turn_taking"]
    assert result["transitions"] >= analytics.MIN_TRANSITIONS
    assert result["sufficient_data"] is True
    assert result["observed_rate"] == 0.0
    assert result["within_2_standard_errors"] is False


def test_report_is_json_safe():
    """The endpoint returns this straight to a client."""
    import json

    seed(VOICES, per_agent=12)
    json.dumps(analytics.divergence_report())


def test_masking_agent_names_removes_the_shortcut():
    """The agents name each other, which would let a classifier cheat.

    Here each agent's text is nothing BUT a reference to another agent, so with
    names intact the classifier can separate them perfectly and with names
    masked there is nothing left to learn. If masking did not collapse this,
    it would not be masking.
    """
    cheat = {
        "introspector": ["what The Behaviorist just said about that"],
        "behaviorist": ["what The Gardener just said about that"],
        "gardener": ["what The Introspector just said about that"],
    }
    seed(cheat, per_agent=14)
    turns = analytics.turns_frame()

    intact = analytics.separability(turns)
    masked = analytics.separability(analytics.mask_agent_names(turns))

    assert intact["accuracy"] > 0.9, "names should be a perfect giveaway here"
    assert masked["accuracy"] < intact["accuracy"] - 0.3, (
        f"masking did not remove the shortcut: {intact['accuracy']} -> "
        f"{masked['accuracy']}"
    )


def test_masked_separability_is_included_in_the_report():
    seed(VOICES, per_agent=14)
    report = analytics.divergence_report()
    assert report["separability_names_masked"]["available"] is True
    # These voices never name each other, so masking should change nothing.
    assert report["separability_names_masked"]["accuracy"] == pytest.approx(
        report["separability"]["accuracy"], abs=0.05
    )


# ── Chat feel ───────────────────────────────────────────────────────────────
#
# These guard the metric that the divergence metrics missed: three agents can be
# perfectly distinguishable from each other and still all write essays.


def gen(agent, text, conversation="c1", model="test-model", at=None):
    """Write one generation row directly — this metric reads generations."""
    from app.store import connect, _now_ms
    with connect() as conn:
        conn.execute(
            """INSERT INTO generations (conversation_id, agent_id, model, latency_ms,
                   char_count, word_count, transcript_len, created_at, text)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (conversation, agent, model, 100, len(text), len(text.split()),
             0, at or _now_ms(), text),
        )


def words(n, extra=""):
    return " ".join(["word"] * n) + (" " + extra if extra else "")


def test_no_recorded_text_is_reported_not_guessed():
    r = analytics.chat_feel_report()
    assert r["available"] is False
    assert "no generated turns" in r["reason"]


def test_uniform_turns_show_low_variation():
    """The 61/66/67/67 case: same mean as a varied set, completely different feel."""
    for i, n in enumerate([61, 66, 67, 67, 65, 64]):
        gen("behaviorist", words(n), conversation=f"c{i}")
    r = analytics.chat_feel(analytics.generated_turns())
    assert r["coefficient_of_variation"] < 0.1, r
    assert r["short_share"] == 0.0
    assert r["long_share"] == 0.0


def test_varied_turns_show_high_variation_at_the_same_mean():
    """Same average as above, but swinging — the metric must separate them."""
    for i, n in enumerate([4, 130, 8, 150, 5, 90]):
        gen("behaviorist", words(n), conversation=f"c{i}")
    r = analytics.chat_feel(analytics.generated_turns())
    assert r["coefficient_of_variation"] > 0.7, r
    assert r["short_share"] > 0.4
    assert r["long_share"] > 0.3


def test_short_and_long_thresholds_are_counted_at_the_boundary():
    gen("gardener", words(14), conversation="a")    # short
    gen("gardener", words(15), conversation="b")    # not short
    gen("gardener", words(101), conversation="c")   # long
    gen("gardener", words(100), conversation="d")   # not long
    r = analytics.chat_feel(analytics.generated_turns())
    assert r["short_turns"] == 1
    assert r["long_turns"] == 1


def test_addressing_counts_only_OTHER_agents():
    """An agent naming itself is not engagement with anyone."""
    gen("behaviorist", "The Introspector is wrong about that", conversation="a")
    gen("behaviorist", "As The Behaviorist I would say no", conversation="b")
    gen("behaviorist", "What have you actually tried so far", conversation="c")
    r = analytics.chat_feel(analytics.generated_turns())
    assert r["addresses_another_agent_share"] == pytest.approx(1 / 3, abs=0.01)


def test_same_agent_followup_delta_measures_consecutive_turns_only():
    """The group-chat move: the same voice coming back at a different length."""
    from app.store import _now_ms
    base = _now_ms()
    gen("behaviorist", words(100), conversation="c1", at=base)
    gen("behaviorist", words(10), conversation="c1", at=base + 1)   # follow-up: 90
    gen("gardener", words(50), conversation="c1", at=base + 2)      # different agent
    gen("behaviorist", words(60), conversation="c1", at=base + 3)   # not consecutive
    r = analytics.chat_feel(analytics.generated_turns())
    assert r["same_agent_followups"] == 1
    assert r["median_followup_delta"] == 90.0


def test_model_filter_selects_a_single_corpus():
    gen("gardener", words(20), conversation="a", model="flash")
    gen("gardener", words(200), conversation="b", model="lite")
    assert analytics.chat_feel(analytics.generated_turns("flash"))["turns"] == 1
    assert analytics.chat_feel(analytics.generated_turns("lite"))["mean_words"] == 200


def test_echo_detects_engagement_that_naming_misses():
    """The reason this metric exists.

    An observed exchange: "...what you feel on a Tuesday morning..." answered by
    "Tuesday mornings happen to the people in the next cubicle too." Obvious
    engagement, zero names. Judging terse conversation by callouts alone reads
    as silence, and did — 2% by name against 48% by content.
    """
    from app.store import _now_ms
    base = _now_ms()
    gen("introspector", "the first thing you feel on a Tuesday morning is dread",
        conversation="c1", at=base)
    gen("gardener", "Tuesday mornings happen to the people in the next cubicle too",
        conversation="c1", at=base + 1)
    r = analytics.chat_feel(analytics.generated_turns())
    assert r["addresses_another_agent_share"] == 0.0, "no names are used here"
    assert r["echoes_previous_agent_share"] == 1.0, "but the reply clearly picks it up"


def test_echo_ignores_an_agent_repeating_itself():
    """Talking to yourself is not engagement."""
    from app.store import _now_ms
    base = _now_ms()
    gen("behaviorist", "your marathon training record matters here", conversation="c1", at=base)
    gen("behaviorist", "the marathon training record is the whole point", conversation="c1", at=base + 1)
    r = analytics.chat_feel(analytics.generated_turns())
    assert r["echoes_previous_agent_share"] is None, "no cross-agent pairs to judge"


def test_echo_needs_a_distinctive_word_not_just_filler():
    """Shared filler must not read as engagement.

    Needs a real corpus: distinctiveness is judged against how often a word
    occurs here, and nothing can be called common on the evidence of two turns.
    """
    from app.store import _now_ms
    base = _now_ms()
    # "matter" runs through the whole corpus, so its reappearance proves nothing.
    for i in range(6):
        gen("introspector", f"whether that would really matter to you here {i}",
            conversation=f"c{i}", at=base + i * 10)
        gen("gardener", f"people around you would matter more than that {i}",
            conversation=f"c{i}", at=base + i * 10 + 1)
    r = analytics.chat_feel(analytics.generated_turns())
    assert r["echoes_previous_agent_share"] == 0.0, (
        "a word this common should not count as picking something up"
    )


def test_echo_still_fires_on_a_genuinely_rare_word_in_that_corpus():
    from app.store import _now_ms
    base = _now_ms()
    for i in range(6):
        gen("introspector", f"whether that would really matter to you here {i}",
            conversation=f"c{i}", at=base + i * 10)
        gen("gardener", f"people around you would matter more than that {i}",
            conversation=f"c{i}", at=base + i * 10 + 1)
    # One exchange carries a word that appears nowhere else.
    gen("introspector", "the cubicle beside you is the thing", conversation="z", at=base + 500)
    gen("gardener", "that cubicle has someone in it too", conversation="z", at=base + 501)
    r = analytics.chat_feel(analytics.generated_turns())
    assert r["echoes_previous_agent_share"] > 0.0
