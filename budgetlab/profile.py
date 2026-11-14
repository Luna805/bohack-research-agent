"""Deterministic development-data profile used in the proposer context (no model calls)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .tasks import field_availability


def _round(value: float, digits: int = 4) -> float:
    return float(round(float(value), digits))


def profile_development(
    features: pd.DataFrame,
    target: pd.Series,
    card: dict[str, Any],
    text_columns: tuple[str, ...] = (),
) -> dict[str, Any]:
    availability = field_availability(card, list(features.columns))
    descriptions = {field["name"]: field.get("description", "") for field in card.get("fields", [])}
    columns: list[dict[str, Any]] = []
    for name in features.columns:
        series = features[name]
        entry: dict[str, Any] = {
            "name": name,
            "availability": availability[name],
            "missing_rate": _round(series.isna().mean()),
            "n_unique": int(series.nunique(dropna=True)),
        }
        if descriptions.get(name):
            entry["description"] = descriptions[name]
        if name in text_columns:
            entry["kind"] = "text"
            entry["mean_length"] = _round(series.fillna("").astype(str).str.len().mean(), 1)
        elif pd.api.types.is_numeric_dtype(series):
            entry["kind"] = "numeric"
            clean = series.dropna()
            entry.update(
                min=_round(clean.min()),
                median=_round(clean.median()),
                max=_round(clean.max()),
                skew=_round(clean.skew(), 2) if len(clean) > 2 else 0.0,
            )
            top_value, top_share = _top(clean)
            if top_share >= 0.2:
                entry["most_common_value"] = top_value
                entry["most_common_share"] = top_share
                if _looks_like_sentinel(clean, top_value):
                    entry["possible_sentinel"] = top_value
        else:
            entry["kind"] = "categorical"
            counts = series.astype(str).value_counts(normalize=True).head(6)
            entry["top_values"] = {str(key): _round(share, 3) for key, share in counts.items()}
            unknown_share = float((series.astype(str).str.lower() == "unknown").mean())
            if unknown_share > 0:
                entry["unknown_label_share"] = _round(unknown_share, 3)
        if entry["availability"] == "available" and entry["kind"] != "text":
            rates = _target_rates(series, target, entry["kind"])
            if rates:
                entry["positive_rate_by_group"] = rates
        columns.append(entry)
    return {
        "rows": len(features),
        "positive_rate": _round(target.mean()),
        "columns": columns,
    }


def _looks_like_sentinel(series: pd.Series, value: float) -> bool:
    """A frequent extreme value far outside the range of every other value (e.g. 999)."""
    if value not in (series.max(), series.min()) or series.nunique() <= 2:
        return False
    others = series[series != value]
    gap = min(abs(value - others.max()), abs(value - others.min()))
    spread = float(others.max() - others.min())
    return gap > max(spread, 1.0)


def _top(series: pd.Series) -> tuple[float, float]:
    if series.empty:
        return 0.0, 0.0
    counts = series.value_counts(normalize=True)
    return float(counts.index[0]), _round(counts.iloc[0], 3)


def _target_rates(series: pd.Series, target: pd.Series, kind: str) -> dict[str, float] | None:
    """Positive rate per category (top 6) or per quartile bin; development data only."""
    try:
        if kind == "categorical":
            keys = series.astype(str)
            top = keys.value_counts().head(6).index
            grouped = target.groupby(keys).mean()
            return {str(key): _round(grouped[key], 3) for key in top}
        if series.nunique(dropna=True) < 4:
            grouped = target.groupby(series).mean()
            return {str(key): _round(value, 3) for key, value in grouped.head(6).items()}
        bins = pd.qcut(series, q=4, duplicates="drop")
        grouped = target.groupby(bins, observed=True).mean()
        return {str(key): _round(value, 3) for key, value in grouped.items()}
    except (ValueError, TypeError):
        return None
