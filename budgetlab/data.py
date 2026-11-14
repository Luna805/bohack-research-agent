from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd
from sklearn.datasets import load_breast_cancer
from sklearn.model_selection import StratifiedKFold

from .contracts import stable_hash


@dataclass(frozen=True)
class DatasetBundle:
    dataset_ref: str
    features: pd.DataFrame
    target: pd.Series
    row_ids: tuple[str, ...]
    dataset_hash: str
    target_column: str


def load_dataset(dataset_ref: str = "sklearn:breast_cancer") -> DatasetBundle:
    if dataset_ref != "sklearn:breast_cancer":
        raise ValueError(f"unsupported offline dataset: {dataset_ref}")
    raw = load_breast_cancer(as_frame=True)
    features = raw.data.copy()
    target = raw.target.astype(int).rename("target")
    row_hashes = pd.util.hash_pandas_object(features, index=True).astype(str)
    row_ids = tuple(f"breast-cancer:{index}:{digest}" for index, digest in row_hashes.items())
    digest = hashlib.sha256()
    digest.update(features.to_csv(index=False, float_format="%.17g").encode("utf-8"))
    digest.update(target.to_csv(index=False).encode("utf-8"))
    return DatasetBundle(
        dataset_ref=dataset_ref,
        features=features,
        target=target,
        row_ids=row_ids,
        dataset_hash=digest.hexdigest(),
        target_column="target",
    )


def numeric_minima(features: pd.DataFrame) -> dict[str, float]:
    return {
        column: float(features[column].min(skipna=True))
        for column in features.select_dtypes(include="number").columns
    }


def split_manifest(
    bundle: DatasetBundle, seeds: Iterable[int], cv_folds: int
) -> tuple[dict[str, object], str]:
    manifests: list[dict[str, object]] = []
    for seed in seeds:
        splitter = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=seed)
        folds = []
        for fold_index, (train, valid) in enumerate(splitter.split(bundle.features, bundle.target)):
            folds.append(
                {
                    "fold": fold_index,
                    "train_row_ids": [bundle.row_ids[index] for index in train],
                    "valid_row_ids": [bundle.row_ids[index] for index in valid],
                }
            )
        manifests.append({"seed": seed, "folds": folds})
    value = {"dataset_hash": bundle.dataset_hash, "cv_folds": cv_folds, "splits": manifests}
    return value, stable_hash(value)
