"""Divergence view — do the three agents actually think differently?

Reads `/analytics/divergence` and shows the answer. The headline is
separability: whether a classifier can tell the agents apart from their text
alone. Everything else on this page is context for that number.
"""

import pandas as pd
import streamlit as st

import api

AGENT_COLOURS = {
    "introspector": "#6366f1",
    "behaviorist": "#d97706",
    "gardener": "#059669",
}

st.title("Divergence")
st.caption(
    "The premise is that these three think differently. This is the check — "
    "not a reading of a few transcripts, which is exactly the judgement that drifts."
)

try:
    report = api.divergence()
except api.ApiError as err:
    st.error(str(err))
    st.stop()

if not report.get("available"):
    st.info(report.get("reason", "Nothing to analyse yet."))
    st.stop()

corpus = report["corpus"]
c1, c2 = st.columns(2)
c1.metric("conversations", corpus["conversations"])
c2.metric("agent turns", corpus["turns"])
st.caption(
    "turns per agent: "
    + ", ".join(f"{a} {n}" for a, n in sorted(corpus["turns_per_agent"].items()))
)

# ── The headline ────────────────────────────────────────────────────────────

st.subheader("Can a classifier tell them apart?")
sep = report["separability"]

if not sep.get("available"):
    st.warning(f"Not enough data yet — {sep['reason']}")
else:
    verdict_style = {
        "distinct": ("✅", "These read as three different minds."),
        "weak": ("⚠️", "Distinguishable, but the voices are blurring."),
        "not distinguishable": ("❌", "One voice in three costumes — the prompts are not landing."),
    }
    icon, sentence = verdict_style.get(sep["verdict"], ("", ""))

    a, b, c = st.columns(3)
    a.metric("accuracy", f"{sep['accuracy']:.0%}")
    b.metric("chance", f"{sep['chance']:.0%}")
    c.metric("lift", f"+{sep['lift_over_chance']:.0%}")
    st.markdown(f"### {icon} {sep['verdict']}")
    st.write(sentence)
    st.caption(
        f"{sep['folds']}-fold cross-validated over {sep['n_turns']} turns, so the "
        "score is on turns the model has not seen."
    )

    st.markdown("**Where it gets confused**")
    labels = sep["labels"]
    st.dataframe(
        pd.DataFrame(sep["confusion_matrix"], index=labels, columns=labels),
        width="stretch",
    )
    st.caption("rows = who actually spoke, columns = who the classifier guessed")
    if sep.get("most_confused"):
        st.caption(f"most often: {sep['most_confused']} ({sep['most_confused_count']}x)")

# ── Supporting detail ───────────────────────────────────────────────────────

length_tab, terms_tab, rhythm_tab = st.tabs(
    ["Turn length", "Distinctive terms", "Turn taking"]
)

with length_tab:
    lengths = pd.DataFrame(report["length"]).T
    st.dataframe(lengths, width="stretch")
    st.bar_chart(lengths["mean_words"])
    st.caption(
        "The prompts tell every agent that length follows what it has to say, with "
        "no target. Near-identical distributions would suggest they have all settled "
        "on one comfortable paragraph shape regardless."
    )

with terms_tab:
    st.caption(
        "What makes each agent recognisable. If The Gardener's list fills with "
        "gardening imagery, its 'no nature metaphors' rule has stopped biting."
    )
    for agent, terms in report["distinctive_terms"].items():
        colour = AGENT_COLOURS.get(agent, "#666")
        st.markdown(
            f"<span style='color:{colour};font-weight:600'>{agent}</span>",
            unsafe_allow_html=True,
        )
        st.write(", ".join(t["term"] for t in terms) or "—")

with rhythm_tab:
    t = report["turn_taking"]
    x, y = st.columns(2)
    x.metric("same speaker again", f"{t['observed_rate']:.0%}" if t["observed_rate"] is not None else "—")
    y.metric("configured", f"{t['expected_rate']:.0%}")
    if not t["sufficient_data"]:
        st.warning(
            f"Only {t['transitions']} speaker transitions — too few to judge. Below "
            f"{t['min_transitions_for_a_verdict']} the interval is wider than the "
            "effect, so this check passes because it cannot fail, not because the "
            "rule is being followed."
        )
    elif t["within_2_standard_errors"]:
        st.success("Matches the configured rate, within two standard errors.")
    else:
        st.error("Off target — the orchestrator is not producing the configured rate.")

lat = report.get("latency", {})
if lat.get("available"):
    st.caption(
        f"median latency {lat['overall_median_ms']}ms over "
        f"{lat['total_generations']} generations"
    )
