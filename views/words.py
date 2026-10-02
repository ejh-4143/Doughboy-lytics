"""Words page: how often catchphrases come up, from podscripts.co transcripts."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common import PODSCRIPTS, correlation, data_stamp, filter_bar, load, load_words, style, theme

# Categorical slots 1-5 (adjacent-pair validated for lines), per theme.
PHRASE_COLORS = {"light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"],
                 "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"]}
SMOOTH_N = 25

stamp = data_stamp()
df = load(stamp)

st.title("💬 Words")
st.caption("How often the show's catchphrases come up, counted in machine-made transcripts from "
           f"[podscripts.co]({PODSCRIPTS}). Counts are approximate (transcription garbles words) "
           "and can't tell who said what. Rates are per 10,000 words, so long and short episodes "
           "compare fairly.")

words = load_words(stamp)
if words is None:
    st.info("No transcript data yet. Run `uv run python -m scraper.transcripts` and then "
            "`uv run python -m scraper.phrases` to build it.")
    st.stop()
t_eps, t_counts = words

view, _ = filter_bar(df, stamp, scores=False)
eps = view.drop_duplicates("page")[["page", "label", "restaurant", "date", "avg_v"]] \
    .merge(t_eps[["page", "words"]], on="page")

phrases = list(t_counts.groupby("phrase")["count"].sum().sort_values(ascending=False).index)
default = [p for p in ("wow",) if p in phrases]  # "wow" dwarfs everything else, so chart it alone
chosen = st.multiselect("Phrases", phrases, default=default, max_selections=5, key="phrases",
                        help="Up to five at a time. To add phrases, edit data/phrases.csv and "
                             "re-run scraper.phrases.")
st.caption(f"{len(eps)} of the {len(view.drop_duplicates('page'))} episodes in this view have a "
           "transcript (podscripts.co has most main episodes, plus Doubles that were re-released "
           "for free).")

if eps.empty:
    st.info("No transcribed episodes match these filters.")
    st.stop()

# Per-episode counts for every tracked phrase (the table shows them all; the
# picker above only decides what goes on the chart).
wide = t_counts.pivot_table(index="slug", columns="phrase", values="count", aggfunc="sum")
per_ep = t_eps[["slug", "page"]].join(wide, on="slug").groupby("page")[phrases].sum()
eps = eps.join(per_ep, on="page").fillna({p: 0 for p in phrases}).sort_values("date")

if not chosen:
    st.info("Pick at least one phrase to chart.")
else:
    fig = go.Figure()
    for color, phrase in zip(PHRASE_COLORS[theme()], chosen):
        rate = eps[phrase] / eps.words * 10_000
        fig.add_trace(go.Scatter(
            x=eps.date, y=rate, mode="markers", name=phrase, legendgroup=phrase,
            marker=dict(size=6, color=color, opacity=0.35),
            customdata=np.stack([eps.restaurant, eps.label, eps[phrase],
                                 eps.date.dt.strftime("%b %d, %Y")], axis=1),
            hovertemplate=(f"<b>%{{customdata[0]}}</b> · %{{customdata[1]}} · %{{customdata[3]}}<br>"
                           f"“{phrase}”: %{{customdata[2]:.0f}} times "
                           "(%{y:.1f} per 10k words)<extra></extra>")))
        # Break the line across long gaps in transcript coverage (podscripts is
        # missing roughly Sept 2025 to May 2026) instead of bridging them.
        smooth = rate.rolling(SMOOTH_N, min_periods=5).mean()
        smooth[eps.date.diff() > pd.Timedelta(days=60)] = np.nan
        fig.add_trace(go.Scatter(
            x=eps.date, y=smooth, mode="lines", connectgaps=False,
            name=phrase, legendgroup=phrase, showlegend=False,
            line=dict(color=color, width=2.5),
            hovertemplate=f"“{phrase}” {SMOOTH_N}-episode avg: %{{y:.1f}} per 10k words"
                          "<extra></extra>"))
    style(fig, None, "Uses per 10,000 words", height=520)
    # Larger text than the other charts: this one is the page's main event.
    fig.update_layout(legend_font_size=15)
    fig.update_xaxes(tickfont_size=14, title_font_size=15)
    fig.update_yaxes(tickfont_size=14, title_font_size=15)
    st.plotly_chart(fig, width="stretch", theme="streamlit")
    st.caption(f"Dots are episodes; lines are {SMOOTH_N}-episode rolling averages. Lines break "
               "where transcripts are missing (podscripts.co has none for most episodes from "
               "late 2025 to spring 2026).")

st.subheader("All tracked phrases")
st.caption("Every phrase in data/phrases.csv, for the episodes matching the filters above, "
           "most used first. Each count includes the phrase's known transcription variants.")
summary = []
for phrase in phrases:
    rate = eps[phrase] / eps.words * 10_000
    used = eps[eps[phrase] > 0]
    by_year = eps.groupby(eps.date.dt.year)[phrase].sum()
    r = correlation(rate, eps.avg_v) if eps.avg_v.notna().sum() >= 3 else None
    summary.append({
        "Phrase": phrase, "Total uses": int(eps[phrase].sum()),
        "Episodes using it": len(used) / len(eps),
        "Per episode": eps[phrase].mean(), "Per 10k words": rate.mean(),
        "First used": used.date.min().year if len(used) else None,
        "Peak year": int(by_year.idxmax()) if by_year.max() > 0 else None,
        "r with episode score": r,
        "Most in": (f"{eps.loc[eps[phrase].idxmax(), 'restaurant']} "
                    f"({int(eps[phrase].max())})") if len(used) else "–",
    })
summary = pd.DataFrame(summary).sort_values("Total uses", ascending=False)
st.dataframe(summary, hide_index=True, width="stretch", height=min(38 + 35 * len(summary), 900),
             column_config={
    "Episodes using it": st.column_config.NumberColumn(format="percent"),
    "Per episode": st.column_config.NumberColumn(format="%.1f"),
    "Per 10k words": st.column_config.NumberColumn(format="%.2f"),
    "First used": st.column_config.NumberColumn(format="%d"),
    "Peak year": st.column_config.NumberColumn(format="%d"),
    "r with episode score": st.column_config.NumberColumn(
        format="%.2f", help="Correlation between how often the phrase is said in an "
                            "episode and that episode's average fork score."),
})
