"""Doughboy-lytics: Nick and Mitch's fork ratings and the show's catchphrases.

Run locally: uv run streamlit run app.py
Pages live in views/ (not pages/, which Streamlit would auto-load); shared
loading, filters and styling are in common.py.
"""

import streamlit as st

from common import PODSCRIPTS, WIKI

st.set_page_config(page_title="Doughboy-lytics", page_icon="🍴", layout="wide")

page = st.navigation([
    st.Page("views/ratings.py", title="Fork ratings", icon="🍴", default=True),
    st.Page("views/words.py", title="Words", icon="💬"),
])
page.run()

st.divider()
st.markdown(
    f"**Data sources:** the [Doughboys Wiki]({WIKI}) on Fandom. Huge thanks to its "
    "editors, who have logged every episode, order and fork rating since 2015. "
    "Spotted a mistake? Please fix it on the wiki. Wiki content is licensed "
    "[CC BY-SA](https://www.fandom.com/licensing), and so is the data shown here. "
    "Word counts come from machine-made transcripts on "
    f"[podscripts.co]({PODSCRIPTS}); thanks to them too. Transcripts aren't republished here. "
    "Fan project, not affiliated with *Doughboys* or Headgum.")
