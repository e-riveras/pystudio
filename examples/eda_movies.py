"""Exploratory analysis of a movies dataset, written by the pystudio assistant.

Expects "Top Movies dataset.csv" in ~/Downloads. Run it cell by cell, or with \\f.
"""

# %% EDA imports and load
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd

# pystudio's plot pane shows PNG output, and the dataset is larger than Altair's 5000-row default
alt.renderers.enable("png", scale_factor=2)
alt.data_transformers.disable_max_rows()

BLUE = "#2a78d6"  # colour never encodes a variable here, so every mark shares one hue
INK, MUTED, GRID = "#0b0b0b", "#898781", "#e1e0d9"


@alt.theme.register("eda", enable=True)
def eda_theme() -> alt.theme.ThemeConfig:
    return {
        "config": {
            "background": "#fcfcfb",
            "view": {"stroke": None},
            "title": {"color": INK, "anchor": "start", "fontSize": 13},
            "axis": {
                "labelColor": MUTED,
                "titleColor": MUTED,
                "titleFontWeight": "normal",
                "gridColor": GRID,
                "domainColor": "#c3c2b7",
                "tickColor": "#c3c2b7",
            },
            "bar": {"color": BLUE},
            "line": {"color": BLUE, "strokeWidth": 2},
            "circle": {"color": BLUE},
        }
    }


path = Path.home() / "Downloads" / "Top Movies dataset.csv"
raw = pd.read_csv(path)
raw.shape

# %% EDA first look
raw.head()

# %% EDA dtypes and missing values
# Vote_Count and Vote_Average load as text, which points to malformed rows
summary = pd.DataFrame({"dtype": raw.dtypes.astype(str), "missing": raw.isna().sum(), "unique": raw.nunique()})
print(summary)
print("Poster_Url identical to Working URL:", (raw["Poster_Url"] == raw["Working URL"]).mean())

# %% EDA clean malformed rows
# Some overviews contain line breaks, so fragments such as ' - Just Desserts' ended up
# as rows of their own. They have no valid date or vote count, so they are dropped.
df = raw.copy()
df["Release_Date"] = pd.to_datetime(df["Release_Date"], format="%d/%m/%Y", errors="coerce")
for col in ["Vote_Count", "Vote_Average"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

bad = df["Release_Date"].isna() | df["Vote_Count"].isna() | df["Title"].isna()
print(f"dropping {bad.sum()} of {len(df)} rows")

df = df.loc[~bad].drop(columns=["Poster_Url", "Working URL"]).reset_index(drop=True)
df["Vote_Count"] = df["Vote_Count"].astype(int)
df["Year"] = df["Release_Date"].dt.year
print(df.isna().sum())
df.dtypes

# %% EDA duplicates
print("fully duplicated rows:", df.duplicated().sum())
print("duplicated titles:", df["Title"].duplicated().sum())
df[df.duplicated(["Title", "Release_Date"], keep=False)].sort_values("Title").head(10)

# %% EDA numeric summary
df[["Popularity", "Vote_Count", "Vote_Average", "Year"]].describe().T

# %% EDA numeric distributions
# popularity and vote count are heavily right-skewed, so plot their logs
distributions = pd.DataFrame(
    {
        "log10 popularity": np.log10(df["Popularity"].clip(lower=0.01)),
        "log10 (vote count + 1)": np.log10(df["Vote_Count"] + 1),
        # a rating of 0 usually means the film has no votes
        "vote average": df["Vote_Average"],
    }
)

alt.Chart(distributions).mark_bar().encode(
    alt.X(alt.repeat("column"), type="quantitative", bin=alt.Bin(maxbins=40)),
    alt.Y("count()", title="films"),
).properties(width=260, height=200).repeat(column=list(distributions.columns)).show()
print("films with zero votes:", (df["Vote_Count"] == 0).sum())

# %% EDA releases over time
per_year = df.groupby("Year").size().rename("films").reset_index()

alt.Chart(per_year, title="films per release year").mark_line().encode(
    alt.X("Year:Q", title="year", axis=alt.Axis(format="d", grid=False)),
    alt.Y("films:Q"),
).properties(width=560, height=240).show()

# %% EDA languages
languages = df["Original_Language"].value_counts()
print(languages.head(10))

top_languages = languages.head(10).reset_index()
alt.Chart(top_languages, title="top 10 original languages").mark_bar(cornerRadiusEnd=4).encode(
    alt.X("count:Q", title="films"),
    alt.Y("Original_Language:N", sort="-x", title=None),
).properties(width=420, height=240).show()

# %% EDA genres
# Genre holds a comma-separated list, so one row per film and genre
genres = df.assign(Genre=df["Genre"].str.split(", ")).explode("Genre")
genres = genres.dropna(subset=["Genre"])

genre_stats = genres.groupby("Genre").agg(
    films=("Title", "size"),
    median_rating=("Vote_Average", "median"),
    median_popularity=("Popularity", "median"),
).sort_values("films", ascending=False)
print(genre_stats)

alt.Chart(genre_stats.reset_index(), title="films per genre").mark_bar(cornerRadiusEnd=4).encode(
    alt.X("films:Q"),
    alt.Y("Genre:N", sort="-x", title=None),
).properties(width=420, height=340).show()

# %% EDA relationships
rated = df[df["Vote_Count"] >= 50]  # ignore ratings based on very few votes
print(rated[["Popularity", "Vote_Count", "Vote_Average", "Year"]].corr(method="spearman").round(2))

relationships = rated.rename(
    columns={
        "Vote_Count": "vote count (log)",
        "Popularity": "popularity (log)",
        "Vote_Average": "vote average",
    }
)

alt.Chart(relationships).mark_circle(size=12, opacity=0.3).encode(
    alt.X(
        alt.repeat("column"),
        type="quantitative",
        scale=alt.Scale(type="log"),
        axis=alt.Axis(grid=False),  # log minor gridlines crowd the points
    ),
    alt.Y("vote average:Q", scale=alt.Scale(zero=False)),
).properties(width=380, height=260).repeat(column=["vote count (log)", "popularity (log)"]).show()

# %% EDA top titles
print(df.nlargest(10, "Popularity")[["Title", "Year", "Popularity", "Vote_Average"]])
print(rated.nlargest(10, "Vote_Average")[["Title", "Year", "Vote_Count", "Vote_Average"]])
