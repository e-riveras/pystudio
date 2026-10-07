"""Exploratory analysis of a movies dataset, written by the pystudio assistant.

Expects "Top Movies dataset.csv" in ~/Downloads. Run it cell by cell, or with \\f.
"""

# %% EDA imports and load
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

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
figure, axes = plt.subplots(1, 3, figsize=(14, 4))

# popularity and vote count are heavily right-skewed, so plot their logs
axes[0].hist(np.log10(df["Popularity"].clip(lower=0.01)), bins=40, color="#4c78a8")
axes[0].set_title("log10 popularity")

axes[1].hist(np.log10(df["Vote_Count"] + 1), bins=40, color="#f58518")
axes[1].set_title("log10 (vote count + 1)")

# a rating of 0 usually means the film has no votes
axes[2].hist(df["Vote_Average"], bins=40, color="#54a24b")
axes[2].set_title("vote average")

figure.tight_layout()
plt.show()
print("films with zero votes:", (df["Vote_Count"] == 0).sum())

# %% EDA releases over time
per_year = df.groupby("Year").size()

figure, axes = plt.subplots(figsize=(9, 4))
per_year.plot(ax=axes, color="#4c78a8")
axes.set_title("films per release year")
axes.set_xlabel("year")
axes.set_ylabel("films")
figure.tight_layout()
plt.show()

# %% EDA languages
languages = df["Original_Language"].value_counts()
print(languages.head(10))

figure, axes = plt.subplots(figsize=(7, 4))
languages.head(10).sort_values().plot.barh(ax=axes, color="#4c78a8")
axes.set_title("top 10 original languages")
figure.tight_layout()
plt.show()

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

figure, axes = plt.subplots(figsize=(7, 5))
genre_stats["films"].sort_values().plot.barh(ax=axes, color="#4c78a8")
axes.set_title("films per genre")
figure.tight_layout()
plt.show()

# %% EDA relationships
rated = df[df["Vote_Count"] >= 50]  # ignore ratings based on very few votes
print(rated[["Popularity", "Vote_Count", "Vote_Average", "Year"]].corr(method="spearman").round(2))

figure, axes = plt.subplots(1, 2, figsize=(12, 4))
axes[0].scatter(rated["Vote_Count"], rated["Vote_Average"], s=6, alpha=0.4, color="#f58518")
axes[0].set_xscale("log")
axes[0].set_xlabel("vote count (log)")
axes[0].set_ylabel("vote average")

axes[1].scatter(rated["Popularity"], rated["Vote_Average"], s=6, alpha=0.4, color="#54a24b")
axes[1].set_xscale("log")
axes[1].set_xlabel("popularity (log)")
axes[1].set_ylabel("vote average")

figure.tight_layout()
plt.show()

# %% EDA top titles
print(df.nlargest(10, "Popularity")[["Title", "Year", "Popularity", "Vote_Average"]])
print(rated.nlargest(10, "Vote_Average")[["Title", "Year", "Vote_Count", "Vote_Average"]])
