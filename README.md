# Doughboy-lytics
On the recent podcast episode of The Doughboys the Nick and Mitch requested a scatterplot of their fork ratings for the restaurants they cover. This script pulls data from https://doughboys.fandom.com/wiki/Episodes into a csv, manual corrections are applied, then the data is deployed as a Streamlit app.

## Data source and thanks

All episode data comes from the [Doughboys Wiki](https://doughboys.fandom.com/wiki/Doughboys_Wikia) on Fandom. Huge thanks to its editors: they've logged every episode since 2015, with orders, fork ratings and later score revisions, and this project wouldn't exist without them. If you spot a mistake, please fix it on the wiki so everyone benefits.

The wiki's text is licensed under [CC BY-SA](https://www.fandom.com/licensing). The CSVs in `data/` are derived from it and are shared under the same license, with attribution to the Doughboys Wiki contributors.

## Usage

```bash
uv sync
uv run python -m scraper.fetch   # download episode pages from the wiki's API into data/raw/
uv run python -m scraper.parse   # build data/episodes.csv and data/ratings.csv
uv run streamlit run app.py      # open the app at http://localhost:8501
```

Manual corrections live in `data/overrides.csv`, and are reapplied every time `parse` runs. Each restaurant's food category and canonical chain name live in `data/categories.csv`, which is hand-curated; `parse` lists any new restaurant that still needs a row.

## Original vs. revised scores

The hosts sometimes change a score after the episode, e.g. Mitch dropping In-N-Out to 3 forks in episode 47. `ratings.csv` has both versions:
- `rating_original`: the score given on the episode.
- `rating`: the revised (current) score.

`episodes.csv` has both versions of each host's score and of the average: `nick`/`nick_original`, `mitch`/`mitch_original`, `guest_avg`/`guest_avg_original` and `avg`/`avg_original`. The app shows revised scores by default.
