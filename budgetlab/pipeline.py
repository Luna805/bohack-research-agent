from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.decomposition import TruncatedSVD
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .schemas import ExperimentSpec, Metric


class FeatureActionsTransformer(BaseEstimator, TransformerMixin):
    def __init__(self, actions: tuple[object, ...]):
        self.actions = actions

    def fit(self, features: pd.DataFrame, target: object = None) -> FeatureActionsTransformer:
        apply_feature_actions(features, self.actions)
        return self

    def transform(self, features: pd.DataFrame) -> pd.DataFrame:
        return apply_feature_actions(features, self.actions)


def apply_feature_actions(features: pd.DataFrame, actions: tuple[object, ...]) -> pd.DataFrame:
    transformed = features.copy()
    for action in actions:
        missing = set(action.columns) - set(transformed.columns)
        if missing:
            raise ValueError(f"feature action references missing columns: {sorted(missing)}")
        if action.kind == "drop_columns":
            transformed = transformed.drop(columns=list(action.columns))
        elif action.kind == "log1p":
            for column in action.columns:
                if not pd.api.types.is_numeric_dtype(transformed[column]):
                    raise ValueError(f"log1p requires a numeric column: {column}")
                if (transformed[column].dropna() <= -1).any():
                    raise ValueError(f"log1p domain violation: {column}")
                transformed[column] = np.log1p(transformed[column])
        elif action.kind == "missing_indicator":
            for column in action.columns:
                transformed[f"{column}__missing"] = transformed[column].isna().astype(float)
        elif action.kind == "sentinel_to_missing":
            for column in action.columns:
                if not pd.api.types.is_numeric_dtype(transformed[column]):
                    raise ValueError(f"sentinel_to_missing requires a numeric column: {column}")
                values = transformed[column].astype(float)
                transformed[column] = values.where(values != action.value)
        else:
            raise ValueError(f"unsupported feature action: {action.kind}")
    return transformed


def _to_text(values: object) -> np.ndarray:
    if hasattr(values, "iloc"):
        series = values.iloc[:, 0]
    else:
        array = np.asarray(values)
        series = pd.Series(array.reshape(-1))
    return series.fillna("").astype(str).to_numpy()


class Text1DTransformer(BaseEstimator, TransformerMixin):
    def fit(self, values: object, target: object = None) -> Text1DTransformer:
        return self

    def transform(self, values: object) -> np.ndarray:
        return _to_text(values)


def build_pipeline(spec: ExperimentSpec, features: pd.DataFrame, training_seed: int) -> Pipeline:
    preview = apply_feature_actions(features, spec.feature_actions)
    text_columns = set(spec.preprocessing.text.columns if spec.preprocessing.text else ())
    numeric_columns = [
        column
        for column in preview.select_dtypes(include="number").columns
        if column not in text_columns
    ]
    categorical_columns = [
        column
        for column in preview.columns
        if column not in numeric_columns and column not in text_columns
    ]
    transformers: list[tuple[str, object, object]] = []
    if numeric_columns:
        numeric_steps: list[tuple[str, object]] = [
            ("imputer", SimpleImputer(strategy=spec.preprocessing.numeric_imputer))
        ]
        if spec.preprocessing.numeric_scaler == "standard":
            numeric_steps.append(("scaler", StandardScaler()))
        transformers.append(("numeric", Pipeline(numeric_steps), numeric_columns))
    if categorical_columns:
        fill_value = "__missing__" if spec.preprocessing.categorical_imputer == "constant" else None
        categorical = Pipeline(
            [
                (
                    "imputer",
                    SimpleImputer(
                        strategy=spec.preprocessing.categorical_imputer, fill_value=fill_value
                    ),
                ),
                ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
            ]
        )
        transformers.append(("categorical", categorical, categorical_columns))
    if spec.preprocessing.text is not None:
        text_spec = spec.preprocessing.text
        for index, column in enumerate(text_spec.columns):
            text_steps: list[tuple[str, object]] = [
                ("to_text", Text1DTransformer()),
                (
                    "tfidf",
                    TfidfVectorizer(
                        max_features=text_spec.max_features,
                        ngram_range=(1, text_spec.ngram_max),
                    ),
                ),
            ]
            if text_spec.svd_components is not None:
                text_steps.append(
                    (
                        "svd",
                        TruncatedSVD(
                            n_components=text_spec.svd_components, random_state=training_seed
                        ),
                    )
                )
            transformers.append((f"text_{index}", Pipeline(text_steps), [column]))
    if not transformers:
        raise ValueError("experiment has no usable feature columns")
    preprocessor = ColumnTransformer(transformers, remainder="drop")
    model = spec.model
    if model.family == "logistic_regression":
        estimator = LogisticRegression(
            C=model.c,
            class_weight=model.class_weight,
            max_iter=model.max_iter,
            random_state=training_seed,
            solver="lbfgs",
        )
    elif model.family == "random_forest":
        estimator = RandomForestClassifier(
            n_estimators=model.n_estimators,
            max_depth=model.max_depth,
            min_samples_leaf=model.min_samples_leaf,
            class_weight=model.class_weight,
            random_state=training_seed,
            n_jobs=1,
        )
    elif model.family == "hist_gradient_boosting":
        estimator = HistGradientBoostingClassifier(
            learning_rate=model.learning_rate,
            max_iter=model.max_iter,
            max_leaf_nodes=model.max_leaf_nodes,
            min_samples_leaf=model.min_samples_leaf,
            class_weight=model.class_weight,
            random_state=training_seed,
        )
    elif model.family == "ridge":
        estimator = Ridge(alpha=model.alpha, random_state=training_seed)
    elif model.family == "random_forest_regressor":
        estimator = RandomForestRegressor(
            n_estimators=model.n_estimators,
            max_depth=model.max_depth,
            min_samples_leaf=model.min_samples_leaf,
            random_state=training_seed,
            n_jobs=1,
        )
    elif model.family == "hist_gradient_boosting_regressor":
        estimator = HistGradientBoostingRegressor(
            learning_rate=model.learning_rate,
            max_iter=model.max_iter,
            max_leaf_nodes=model.max_leaf_nodes,
            min_samples_leaf=model.min_samples_leaf,
            random_state=training_seed,
        )
    else:
        raise ValueError(f"unsupported model family: {model.family}")
    return Pipeline(
        [
            ("feature_actions", FeatureActionsTransformer(spec.feature_actions)),
            ("preprocessing", preprocessor),
            ("model", estimator),
        ]
    )


def score_predictions(
    metric: Metric, target: pd.Series, pipeline: Pipeline, features: pd.DataFrame
) -> float:
    predictions = pipeline.predict(features)
    if metric == "f1_macro":
        return float(f1_score(target, predictions, average="macro", zero_division=0))
    if metric == "accuracy":
        return float(accuracy_score(target, predictions))
    if metric == "roc_auc":
        if not hasattr(pipeline, "predict_proba"):
            raise ValueError("roc_auc requires continuous class scores")
        probabilities = pipeline.predict_proba(features)
        if probabilities.shape[1] == 2:
            return float(roc_auc_score(target, probabilities[:, 1]))
        return float(roc_auc_score(target, probabilities, multi_class="ovr", average="macro"))
    if metric == "r2":
        return float(r2_score(target, predictions))
    if metric == "rmse":
        return float(np.sqrt(mean_squared_error(target, predictions)))
    if metric == "mae":
        return float(mean_absolute_error(target, predictions))
    raise ValueError(f"unsupported metric: {metric}")
