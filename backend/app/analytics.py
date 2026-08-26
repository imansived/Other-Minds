"""Do the three agents actually think differently?

That is the entire premise of the app, and until now there was no way to check
it except by reading. This module answers it from the stored corpus.

The headline metric is **separability**: train a classifier to guess which agent
wrote a turn, from the turn's text alone. If it cannot do better than chance,
the three prompts are producing one voice in three costumes, and no amount of
reading a few transcripts would reliably tell you that.

Everything here reads; nothing here writes. It is safe to run against the live
database.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline

from app.agents.registry import AGENT_IDS
from app.config import settings
from app.store import connect

# Below this, the numbers are noise dressed up as findings.
MIN_TURNS_PER_AGENT = 8
# Folds for the separability check; reduced automatically for a small corpus.
MAX_FOLDS = 5
# Fewer speaker transitions than this and the repeat-rate check has no power:
# the confidence interval is wider than the effect it is looking for.
MIN_TRANSITIONS = 20


# ── Loading ─────────────────────────────────────────────────────────────────


def turns_frame() -> pd.DataFrame:
    """One row per agent turn. The user's own messages are not turns."""
    with connect() as conn:
        df = pd.read_sql_query(
            """
            SELECT m.conversation_id, m.turn_index, m.role AS agent, m.content
              FROM messages m
             WHERE m.role != 'user'
             ORDER BY m.conversation_id, m.turn_index
            """,
            conn,
        )
    if df.empty:
        return df
    df["char_count"] = df["content"].str.len()
    df["word_count"] = df["content"].str.split().str.len()
    return df


def generations_frame() -> pd.DataFrame:
    """Telemetry for every generated turn, including ones never saved."""
    with connect() as conn:
        return pd.read_sql_query(
            """SELECT agent_id AS agent, model, latency_ms, char_count,
                      word_count, transcript_len, created_at
                 FROM generations""",
            conn,
        )


# ── Metrics ─────────────────────────────────────────────────────────────────


def length_profile(turns: pd.DataFrame) -> dict:
    """How long each agent's turns run.

    The prompts tell every agent that length should follow what it has to say,
    with no target. Wildly similar distributions would suggest they are all
    converging on one comfortable paragraph shape regardless.
    """
    g = turns.groupby("agent")["word_count"]
    return {
        agent: {
            "turns": int(g.count()[agent]),
            "mean_words": round(float(g.mean()[agent]), 1),
            "median_words": float(g.median()[agent]),
            "std_words": round(float(g.std()[agent]), 1) if g.count()[agent] > 1 else 0.0,
            "min_words": int(g.min()[agent]),
            "max_words": int(g.max()[agent]),
        }
        for agent in g.count().index
    }


def turn_taking(turns: pd.DataFrame) -> dict:
    """Does the observed speaker rotation match the configured rule?

    The orchestrator repeats the previous speaker with probability
    `double_turn_chance`. This checks the corpus against that, which is really a
    test of the orchestrator rather than of the agents — but it is cheap, and it
    would catch a turn rule that silently stopped being applied.
    """
    repeats = 0
    transitions = 0
    for _, convo in turns.groupby("conversation_id"):
        agents = convo.sort_values("turn_index")["agent"].tolist()
        for prev, nxt in zip(agents, agents[1:]):
            transitions += 1
            if prev == nxt:
                repeats += 1
    observed = repeats / transitions if transitions else None
    expected = settings.double_turn_chance
    # Standard error of a proportion, for judging whether a gap is meaningful.
    se = float(np.sqrt(expected * (1 - expected) / transitions)) if transitions else None
    return {
        "transitions": transitions,
        "repeats": repeats,
        "observed_rate": round(observed, 3) if observed is not None else None,
        "expected_rate": expected,
        "within_2_standard_errors": (
            bool(abs(observed - expected) <= 2 * se) if observed is not None and se else None
        ),
        # Without this the previous field lies by omission. Below ~20
        # transitions the interval is so wide that even a corpus with zero
        # repeats sits "within 2 SE" of a 25% rate — the check passes because
        # it cannot fail, not because the rule is being followed.
        "sufficient_data": transitions >= MIN_TRANSITIONS,
        "min_transitions_for_a_verdict": MIN_TRANSITIONS,
    }


def _vectorizer() -> TfidfVectorizer:
    # Stop words are deliberately KEPT. Function words ("you", "what", "would")
    # are among the strongest authorship signals there are, and the agents'
    # differences are as much in how they address someone as in what they name.
    return TfidfVectorizer(
        lowercase=True,
        ngram_range=(1, 2),
        min_df=2,
        sublinear_tf=True,
    )


def lexical_similarity(turns: pd.DataFrame) -> dict:
    """Cosine similarity between the agents' pooled vocabulary.

    Lower means more distinct. This is a blunt instrument — three agents
    discussing the same questions will always share a lot of words — so treat it
    as a trend to watch across prompt edits, not as an absolute score.
    """
    pooled = turns.groupby("agent")["content"].apply(" ".join)
    agents = list(pooled.index)
    matrix = cosine_similarity(_vectorizer().fit_transform(pooled.tolist()))
    pairs = {}
    for i, a in enumerate(agents):
        for j, b in enumerate(agents):
            if i < j:
                pairs[f"{a}__{b}"] = round(float(matrix[i][j]), 3)
    return {
        "pairwise_cosine": pairs,
        "mean_pairwise": round(float(np.mean(list(pairs.values()))), 3) if pairs else None,
    }


def separability(turns: pd.DataFrame) -> dict:
    """Can a classifier tell the agents apart from their text alone?

    The headline result. Accuracy near chance (~0.33) means the prompts are not
    producing distinguishable voices, whatever the transcripts feel like when
    you read them.

    Cross-validated, so the score is on turns the model has not seen. The
    confusion matrix matters as much as the accuracy: it names *which* two
    agents blur together, which is what you would act on.
    """
    counts = turns["agent"].value_counts()
    if len(counts) < 2 or counts.min() < MIN_TURNS_PER_AGENT:
        return {
            "available": False,
            "reason": (
                f"needs at least {MIN_TURNS_PER_AGENT} turns per agent; "
                f"smallest class has {int(counts.min()) if len(counts) else 0}"
            ),
        }

    X = turns["content"].tolist()
    y = turns["agent"].to_numpy()
    folds = int(min(MAX_FOLDS, counts.min()))

    model = make_pipeline(
        _vectorizer(),
        LogisticRegression(max_iter=2000, class_weight="balanced"),
    )
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=0)
    predicted = cross_val_predict(model, X, y, cv=cv)

    labels = sorted(counts.index)
    cm = confusion_matrix(y, predicted, labels=labels)
    accuracy = float((predicted == y).mean())
    chance = 1.0 / len(labels)

    per_agent = {
        agent: round(float(cm[i][i] / cm[i].sum()), 3) if cm[i].sum() else None
        for i, agent in enumerate(labels)
    }

    # Which pair blurs together most — the actionable part.
    worst_pair, worst_count = None, 0
    for i, a in enumerate(labels):
        for j, b in enumerate(labels):
            if i != j and cm[i][j] > worst_count:
                worst_count, worst_pair = cm[i][j], f"{a} mistaken for {b}"

    return {
        "available": True,
        "accuracy": round(accuracy, 3),
        "chance": round(chance, 3),
        "lift_over_chance": round(accuracy - chance, 3),
        "folds": folds,
        "n_turns": int(len(y)),
        "recall_per_agent": per_agent,
        "labels": labels,
        "confusion_matrix": cm.tolist(),
        "most_confused": worst_pair,
        "most_confused_count": int(worst_count),
        "verdict": (
            "distinct" if accuracy >= chance + 0.30
            else "weak" if accuracy >= chance + 0.15
            else "not distinguishable"
        ),
    }


def mask_agent_names(turns: pd.DataFrame) -> pd.DataFrame:
    """Replace every mention of an agent's name with a neutral word.

    The prompts tell the agents to refer to each other by name, which hands the
    classifier a shortcut: "mentions The Introspector" is a decent clue that the
    speaker is not The Introspector. That would inflate the separability score
    without the voices being any more distinct.

    Running the check both ways separates the two. If accuracy survives masking,
    the agents are being recognised by how they speak rather than by who they
    name.
    """
    masked = turns.copy()
    masked["content"] = masked["content"].str.replace(
        r"\b(the\s+)?(introspector|behaviorist|gardener)\b",
        "someone",
        regex=True,
        case=False,
    )
    return masked


def distinctive_terms(turns: pd.DataFrame, top_n: int = 12) -> dict:
    """The terms most characteristic of each agent.

    Directly useful when editing a prompt: if The Gardener's list fills up with
    gardening imagery, the "do not speak in nature metaphors" rule has stopped
    biting.
    """
    counts = turns["agent"].value_counts()
    if len(counts) < 2 or counts.min() < 2:
        return {}
    # A DIFFERENT vectoriser from the classifier's, on purpose. The classifier
    # wants function words — they are strong authorship signal. A human reading
    # this list does not: "to this", "have to" and "right now" are true but
    # useless, and they crowd out the content words you would actually act on.
    vec = TfidfVectorizer(
        lowercase=True,
        ngram_range=(1, 2),
        min_df=2,
        sublinear_tf=True,
        stop_words="english",
    )
    matrix = vec.fit_transform(turns["content"].tolist())
    features = np.array(vec.get_feature_names_out())
    agents = turns["agent"].to_numpy()

    means = {a: np.asarray(matrix[agents == a].mean(axis=0)).ravel() for a in counts.index}
    out = {}
    for agent, vector in means.items():
        others = np.mean([v for a, v in means.items() if a != agent], axis=0)
        # How much more this agent uses a term than the others do.
        edge = vector - others
        top = np.argsort(edge)[::-1][:top_n]
        out[agent] = [
            {"term": str(features[i]), "edge": round(float(edge[i]), 4)}
            for i in top
            if edge[i] > 0
        ]
    return out


def latency_profile() -> dict:
    gens = generations_frame()
    if gens.empty:
        return {"available": False}
    g = gens.groupby("agent")["latency_ms"]
    return {
        "available": True,
        "total_generations": int(len(gens)),
        "overall_median_ms": int(gens["latency_ms"].median()),
        "per_agent_median_ms": {a: int(v) for a, v in g.median().items()},
    }


# ── Report ──────────────────────────────────────────────────────────────────


def divergence_report() -> dict:
    """Everything, in one JSON-safe dict."""
    turns = turns_frame()
    if turns.empty:
        return {
            "available": False,
            "reason": "no stored agent turns yet — have a conversation first",
            "corpus": {"conversations": 0, "turns": 0},
        }

    known = turns[turns["agent"].isin(AGENT_IDS)]
    return {
        "available": True,
        "corpus": {
            "conversations": int(turns["conversation_id"].nunique()),
            "turns": int(len(known)),
            "turns_per_agent": {a: int(n) for a, n in known["agent"].value_counts().items()},
        },
        "length": length_profile(known),
        "turn_taking": turn_taking(known),
        "lexical_similarity": lexical_similarity(known),
        "separability": separability(known),
        # The same check with every agent name removed, so the score cannot be
        # propped up by who the speaker name-drops. A large gap between the two
        # would mean the voices are less distinct than the headline suggests.
        "separability_names_masked": separability(mask_agent_names(known)),
        "distinctive_terms": distinctive_terms(known),
        "latency": latency_profile(),
    }


def print_report() -> None:
    """Human-readable version, for `python -m app.analytics`."""
    r = divergence_report()
    if not r["available"]:
        print(r["reason"])
        return

    c = r["corpus"]
    print(f"corpus: {c['turns']} agent turns across {c['conversations']} conversations")
    print(f"        {c['turns_per_agent']}\n")

    print("length (words per turn)")
    for agent, s in r["length"].items():
        print(f"  {agent:13s} mean {s['mean_words']:6.1f}  median {s['median_words']:5.0f}"
              f"  sd {s['std_words']:6.1f}  range {s['min_words']}-{s['max_words']}")

    t = r["turn_taking"]
    print(f"\nturn taking: same speaker again {t['observed_rate']} "
          f"(configured {t['expected_rate']}, n={t['transitions']}) "
          f"{'ok' if t['within_2_standard_errors'] else 'OFF TARGET'}")

    ls = r["lexical_similarity"]
    print(f"\nlexical similarity (lower = more distinct), mean {ls['mean_pairwise']}")
    for pair, v in ls["pairwise_cosine"].items():
        print(f"  {pair.replace('__', ' vs '):32s} {v}")

    s = r["separability"]
    print("\nseparability - can a classifier tell them apart?")
    if not s["available"]:
        print(f"  unavailable: {s['reason']}")
    else:
        print(f"  accuracy {s['accuracy']} vs chance {s['chance']} "
              f"(+{s['lift_over_chance']})  ->  {s['verdict'].upper()}")
        print(f"  per-agent recall: {s['recall_per_agent']}")
        if s["most_confused"]:
            print(f"  most confused:    {s['most_confused']} ({s['most_confused_count']}x)")
        m = r.get("separability_names_masked", {})
        if m.get("available"):
            drop = s["accuracy"] - m["accuracy"]
            print(f"  names masked:     {m['accuracy']} ({drop:+.3f}) "
                  f"- {'voice, not name-dropping' if abs(drop) < 0.1 else 'LEANS ON NAMES'}")

    print("\ndistinctive terms")
    for agent, terms in r["distinctive_terms"].items():
        print(f"  {agent:13s} {', '.join(t['term'] for t in terms[:10])}")

    lat = r["latency"]
    if lat.get("available"):
        print(f"\nlatency: median {lat['overall_median_ms']}ms "
              f"over {lat['total_generations']} generations")


if __name__ == "__main__":
    print_report()


# ── Chat feel ───────────────────────────────────────────────────────────────
#
# The divergence metrics answer "are these three different from each other".
# They can all be green while every turn is a 150-word essay, which is exactly
# what happened: 90% separability was reported as success while nothing in the
# transcript read like people talking. These metrics answer the other question:
# does this read like a group chat?
#
# Read from `generations`, not `messages`. That table is append-only and stamps
# the model on every row, so a turn can always be attributed to what produced
# it; `messages` is client-managed and its indices shift on re-save.

# Under this, a turn is a reaction rather than a statement.
SHORT_TURN_WORDS = 15
# Over this, it is an essay.
LONG_TURN_WORDS = 100

def generated_turns(model: str | None = None) -> pd.DataFrame:
    """Every generated turn whose text was recorded, newest last."""
    with connect() as conn:
        df = pd.read_sql_query(
            """SELECT id, conversation_id, agent_id AS agent, model, word_count,
                      transcript_len, created_at, text
                 FROM generations
                WHERE text IS NOT NULL
                ORDER BY created_at""",
            conn,
        )
    if model and not df.empty:
        df = df[df["model"] == model]
    return df



# A word appearing in more than this share of turns is too common for its
# reappearance to mean anything.
ECHO_MAX_DOCUMENT_FREQUENCY = 0.2
# ...and it must appear in at least this many turns before that share means
# anything. In a two-turn corpus every word occurs in 100% of turns, so a bare
# frequency test would dismiss the whole vocabulary as common.
ECHO_MIN_TURNS_FOR_COMMON = 5


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{5,}", str(text).lower()))


def _echo_share(turns: pd.DataFrame) -> float | None:
    """Share of turns reusing a DISTINCTIVE word from the previous agent's turn.

    Distinctiveness is measured against this corpus rather than a hand-written
    stopword list. A list is guesswork that fails quietly: "matter" is six
    letters and unremarkable, and counted as engagement until a test caught it.
    Document frequency has no such blind spot — whatever is common here is
    common, and is ignored, without anyone having to anticipate it.

    Only pairs where the previous turn belongs to a DIFFERENT agent count, so an
    agent repeating itself never registers as engagement.
    """
    if turns.empty:
        return None
    per_turn = [_words(t) for t in turns["text"]]
    n = len(per_turn)
    freq: dict[str, int] = {}
    for bag in per_turn:
        for w in bag:
            freq[w] = freq.get(w, 0) + 1
    common = {
        w
        for w, c in freq.items()
        if c >= ECHO_MIN_TURNS_FOR_COMMON and c / n > ECHO_MAX_DOCUMENT_FREQUENCY
    }

    eligible = echoed = 0
    for _, convo in turns.groupby("conversation_id"):
        convo = convo.sort_values("created_at")
        prev_agent, prev_words = None, set()
        for _, row in convo.iterrows():
            here = _words(row["text"]) - common
            if prev_agent is not None and prev_agent != row["agent"]:
                eligible += 1
                if here & prev_words:
                    echoed += 1
            prev_agent = row["agent"]
            prev_words = here
    return round(echoed / eligible, 3) if eligible else None


def chat_feel(turns: pd.DataFrame) -> dict:
    """Does this read like a group chat, or like three essays taking turns?

    Averages hide the thing that matters. A set of turns that are all 65 words
    and a set that swing between 5 and 150 have the same mean and feel nothing
    alike, so the spread is reported as prominently as the centre.
    """
    if turns.empty:
        return {"available": False, "reason": "no generated turns with recorded text"}

    words = turns["word_count"].to_numpy(dtype=float)
    n = len(words)
    mean = float(words.mean())
    std = float(words.std(ddof=1)) if n > 1 else 0.0

    # Does the turn name one of the OTHER agents? A literal, reliable signal —
    # and the agents are told to refer to each other by name, so a chat between
    # them should show it often.
    #
    # Whether a turn *responds* to another agent without naming one is not
    # detectable this way. That is a real limit of this number, not something to
    # paper over: treat it as a floor on engagement, not a measure of it.
    def mentions_another(row) -> bool:
        others = [a for a in AGENT_IDS if a != row["agent"]]
        pattern = r"\b(?:the\s+)?(?:" + "|".join(others) + r")\b"
        return bool(re.search(pattern, str(row["text"]), re.I))

    names_other = turns.apply(mentions_another, axis=1)

    # The specific thing a group chat does and a lecture does not: the same
    # voice coming back shorter (or longer) the second time. Measured only on
    # consecutive turns by the same agent in the same conversation.
    deltas = []
    for _, convo in turns.groupby("conversation_id"):
        convo = convo.sort_values("created_at")
        prev_agent, prev_words = None, None
        for _, row in convo.iterrows():
            if row["agent"] == prev_agent and prev_words is not None:
                deltas.append(abs(int(row["word_count"]) - int(prev_words)))
            prev_agent, prev_words = row["agent"], row["word_count"]

    # Picking up what the previous agent just said, WITHOUT naming them.
    #
    # This exists because the name-based signal undercounts badly. A real
    # observed exchange: "...the first thing you feel on a Tuesday morning..."
    # answered by "Tuesday mornings happen to the people in the next cubicle
    # too." That is unmistakable engagement and scores zero on a name check,
    # and short turns reference by content far more than by name — so judging
    # a terse conversation by callouts alone reads as silence.
    echoed = _echo_share(turns)

    return {
        "available": True,
        "turns": int(n),
        "models": sorted(turns["model"].dropna().unique().tolist()),
        "mean_words": round(mean, 1),
        "median_words": float(np.median(words)),
        "std_words": round(std, 1),
        # The uniformity number. Spread relative to size, so it is comparable
        # across corpora with different average lengths. Below ~0.4 the turns
        # are essentially one length wearing different words.
        "coefficient_of_variation": round(std / mean, 2) if mean else None,
        "min_words": int(words.min()),
        "max_words": int(words.max()),
        "short_turns": int((words < SHORT_TURN_WORDS).sum()),
        "short_share": round(float((words < SHORT_TURN_WORDS).mean()), 3),
        "long_turns": int((words > LONG_TURN_WORDS).sum()),
        "long_share": round(float((words > LONG_TURN_WORDS).mean()), 3),
        "addresses_another_agent_share": round(float(names_other.mean()), 3),
        "echoes_previous_agent_share": echoed,
        "same_agent_followups": len(deltas),
        "median_followup_delta": float(np.median(deltas)) if deltas else None,
        "thresholds": {"short_under": SHORT_TURN_WORDS, "long_over": LONG_TURN_WORDS},
    }


def chat_feel_report(model: str | None = None) -> dict:
    """chat_feel plus a per-agent breakdown."""
    turns = generated_turns(model)
    overall = chat_feel(turns)
    if not overall["available"]:
        return overall
    overall["per_agent"] = {
        agent: chat_feel(group)
        for agent, group in turns.groupby("agent")
        if len(group) >= 3
    }
    return overall
