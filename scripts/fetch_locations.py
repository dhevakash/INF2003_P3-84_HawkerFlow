#!/usr/bin/env python3
"""Download an attributed, hash-verified NEA historical location snapshot.

The bundled snapshot makes setup independent of a live government API. This
script refreshes only data files: it never changes application database rows.
"""
import argparse
import csv
import hashlib
import io
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET_ID = "d_68a42f09f350881996d83f9cd73ab02f"
SOURCE = f"https://data.gov.sg/datasets/{DATASET_ID}/view"
API = f"https://data.gov.sg/api/action/datastore_search?resource_id={DATASET_ID}&limit=1000"
LICENCE = "https://data.gov.sg/open-data-licence"
SELECTED = ["Adam Road Food Centre", "Amoy Street Food Centre", "Bedok Food Centre",
            "Berseh Food Centre", "Chomp Chomp Food Centre"]


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def fetch(destination):
    destination.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(API, headers={"User-Agent": "HawkerFlow academic dataset importer"})
    with urllib.request.urlopen(request, timeout=45) as response:
        raw = response.read()
    payload = json.loads(raw)
    if not payload.get("success"):
        raise RuntimeError("Government API did not return a successful dataset response")
    result = payload["result"]
    records = result["records"]
    if result.get("total") != len(records):
        raise RuntimeError("Incomplete snapshot; API pagination must be implemented before use")
    fields = [field["id"] for field in result["fields"]]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(records)
    csv_bytes = output.getvalue().encode("utf-8")
    branches = []
    for index, name in enumerate(SELECTED, 1):
        matches = [record for record in records if record["name_of_centre"] == name]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one centre named {name}")
        record = matches[0]
        match = re.search(r"S\((\d{6})\)", record["location_of_centre"])
        if not match:
            raise RuntimeError(f"Missing six-digit postal code for {name}")
        branches.append({"id": index, "name": f"HawkerFlow Demo — {name}",
                         "address": record["location_of_centre"], "postal_code": match.group(1),
                         "source_centre_name": name, "source_record_id": record["_id"],
                         "scenario": "Fictional teaching branch using a historical public location; no affiliation"})
    files = {"nea_hawker_centres_raw.json": raw, "nea_hawker_centres.csv": csv_bytes,
             "demo_branches.json": (json.dumps(branches, ensure_ascii=False, indent=2) + "\n").encode()}
    for name, content in files.items():
        (destination / name).write_bytes(content)
    metadata = {"dataset_id": DATASET_ID, "title": "List of Government Markets Hawker Centres",
                "publisher": "National Environment Agency", "source_url": SOURCE, "api_url": API,
                "licence_url": LICENCE, "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                "source_data_period": "January–September 2016", "source_page_last_updated": "2024-06-06",
                "record_count": len(records), "column_count_excluding_api_id": len(fields) - 1,
                "files": {name: {"sha256": sha256(content), "bytes": len(content)} for name, content in files.items()},
                "limitations": ["Historical locations, not a current directory", "Centres are not branches of HawkerFlow",
                                "No menu, stock, sales, customer or review data is provided by this source"],
                "attribution": "Contains information from List of Government Markets Hawker Centres, accessed on "
                               + datetime.now(timezone.utc).date().isoformat()
                               + " from data.gov.sg, made available under Singapore Open Data Licence v1.0: " + LICENCE}
    (destination / "source_manifest.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"downloaded_records": len(records), "selected_demo_branches": len(branches),
                      "raw_bytes": len(raw), "raw_sha256": sha256(raw)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=ROOT / "data")
    fetch(parser.parse_args().destination)
