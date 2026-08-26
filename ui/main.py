"""Entry point for the Streamlit client.

Two pages: the conversation itself, and the divergence view that checks whether
the three agents are actually distinct. `st.navigation` is used rather than a
`pages/` directory so the labels are explicit rather than derived from filenames.
"""

import streamlit as st

st.set_page_config(page_title="Other Minds", page_icon="🌀", layout="centered")

st.navigation(
    [
        st.Page("streamlit_app.py", title="Conversation", icon="💬", default=True),
        st.Page("analytics_page.py", title="Divergence", icon="📊"),
    ]
).run()
