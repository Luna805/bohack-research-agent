"""Build the demo upload CSV for the chat research page (role C).

Source: UCI Machine Learning Repository, "Student Performance" (Cortez and Silva, 2008),
CC BY 4.0, file ``student-por.csv`` (Portuguese language course, 649 students).

The CSV keeps every original column, including the period grades G1, G2 and the final grade G3,
because a real school export would contain them. The target ``final_result`` is "fail" when
G3 < 10 (Portuguese 0-20 scale) and "pass" otherwise. Deciding which columns are unusable at
prediction time is left to the protocol step - that is the point of the demo.

Usage (from the repository root):
    python examples/student_risk/build_demo_csv.py            # downloads from UCI
    python examples/student_risk/build_demo_csv.py --zip path/to/student+performance.zip
"""

from __future__ import annotations

import argparse
import hashlib
import io
import ssl
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

URL = "https://archive.ics.uci.edu/static/public/320/student+performance.zip"
SOURCE_SHA256 = "a7594a11d7771c0efe1a740824e0e833da9c4cad07c39a9766a874575563fb3f"
HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "student_risk.csv"


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def read_source(zip_path: Path | None) -> bytes:
    if zip_path is not None:
        outer = zipfile.ZipFile(zip_path)
    else:
        with urllib.request.urlopen(URL, timeout=60, context=_ssl_context()) as response:  # noqa: S310
            outer = zipfile.ZipFile(io.BytesIO(response.read()))
    inner = zipfile.ZipFile(io.BytesIO(outer.read("student.zip")))
    raw = inner.read("student-por.csv")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SOURCE_SHA256:
        raise ValueError(f"unexpected student-por.csv hash: {digest}")
    return raw


def build(raw: bytes) -> pd.DataFrame:
    frame = pd.read_csv(io.BytesIO(raw), sep=";")
    frame["final_result"] = (frame["G3"] >= 10).map({True: "pass", False: "fail"})
    return frame


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, help="local copy of the UCI zip instead of downloading")
    args = parser.parse_args()
    frame = build(read_source(args.zip))
    frame.to_csv(OUTPUT, index=False, lineterminator="\n")
    counts = frame["final_result"].value_counts().to_dict()
    print(f"wrote {OUTPUT} ({len(frame)} rows, {frame.shape[1]} columns, {counts})")
    print(f"sha256 {hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
