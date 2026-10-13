#!/usr/bin/env python3
"""Fetch the UCI Yelp sentence subset with provenance, never fake purchase links."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
URL = "https://archive.ics.uci.edu/static/public/331/sentiment+labelled+sentences.zip"
SOURCE = "https://archive.ics.uci.edu/dataset/331/sentiment+labelled+sentences"
MEMBER = "sentiment labelled sentences/yelp_labelled.txt"


def fetch(destination):
    destination.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(URL, timeout=45) as response:
        archive = response.read()
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        raw = zipped.read(MEMBER)
        readme = zipped.read("sentiment labelled sentences/readme.txt")
    rows = []
    for index, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        text, label = line.rsplit("\t", 1)
        if label not in ("0", "1") or not text.strip():
            raise RuntimeError(f"Invalid Yelp source sentence at line {index}")
        rows.append({"source_record_id": index, "text": text, "sentiment": int(label), "source": "uci_yelp"})
    counts = Counter(row["sentiment"] for row in rows)
    if len(rows) != 1000 or counts != {0: 500, 1: 500}:
        raise RuntimeError("Unexpected UCI subset size or class balance")
    files = {"uci_sentiment_source.zip": archive, "uci_yelp_labelled.txt": raw,
             "uci_sentiment_readme.txt": readme,
             "external_review_examples.json": (json.dumps(rows, ensure_ascii=False, indent=2) + "\n").encode("utf-8")}
    for filename, content in files.items():
        (destination / filename).write_bytes(content)
    metadata = {"title": "Sentiment Labelled Sentences — Yelp subset", "publisher": "UCI Machine Learning Repository",
                "creator": "Dimitrios Kotzias", "publication_year": 2015, "doi": "10.24432/C57604",
                "source_url": SOURCE, "download_url": URL, "licence": "CC BY 4.0",
                "licence_url": "https://creativecommons.org/licenses/by/4.0/",
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                "selected_archive_member": MEMBER, "records": len(rows),
                "sentiment_counts": {"negative": counts[0], "positive": counts[1]},
                "files": {name: {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
                          for name, content in files.items()},
                "transformations": ["Extract Yelp member only", "Split final tab into sentence and integer sentiment",
                                    "Assign reproducible source row number", "Preserve sentence text; no inferred ratings/tags/locations"],
                "limitations": ["Balanced research sample, not a representative complaint rate", "No neutral sentences",
                                "No dates, locations, customer IDs or purchase links", "Never joined to fictional local branches"],
                "citation": "Kotzias, D. (2015). Sentiment Labelled Sentences [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C57604",
                "paper_citation": "Kotzias, D., Denil, M., de Freitas, N., & Smyth, P. (2015). From Group to Individual Labels Using Deep Features. KDD."}
    (destination / "review_source_manifest.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"external_review_sentences": len(rows), "counts": dict(counts),
                      "archive_bytes": len(archive), "archive_sha256": hashlib.sha256(archive).hexdigest()}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=ROOT / "data")
    fetch(parser.parse_args().destination)
