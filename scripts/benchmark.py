"""Real MariaDB/MongoDB comparison on identical generated review documents.

This writes only benchmark_reviews/benchmark_review_tags SQL tables and the
benchmark_reviews Mongo collection. No live business tables are changed.
Run with --sql-url and --mongo-url, or SQL_URL/MONGO_URL environment variables.
"""
from __future__ import annotations

import argparse
import csv
import importlib.metadata
import json
import math
import os
import platform
import random
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

NEGATIVE_TAGS = ["cold", "slow service", "too spicy", "wrong order", "poor value"]
SQL_QUERY = """
SELECT t.tag, COUNT(*) AS count
FROM benchmark_reviews r
JOIN benchmark_review_tags t ON t.review_id = r.id
WHERE r.branch_id = :branch_id AND r.rating <= 2
  AND t.tag IN ('cold','slow service','too spicy','wrong order','poor value')
GROUP BY t.tag
ORDER BY count DESC, t.tag ASC
"""


def pipeline(branch_id: int) -> list[dict]:
    return [
        {"$match": {"branch_id": branch_id, "rating": {"$lte": 2}}},
        {"$unwind": "$tags"},
        {"$match": {"tags": {"$in": NEGATIVE_TAGS}}},
        {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
    ]


def records(count: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    tags = NEGATIVE_TAGS + ["friendly", "tasty", "fast service"]
    return [
        {"_id": index + 1, "branch_id": rng.randint(1, 8),
         "rating": rng.randint(1, 5),
         "tags": sorted(rng.sample(tags, rng.randint(0, 4)))}
        for index in range(count)
    ]


def summary(samples: list[float]) -> dict:
    ordered = sorted(samples)
    return {"median_ms": statistics.median(samples),
            "p95_ms": ordered[math.ceil(len(ordered) * .95) - 1],
            "min_ms": ordered[0], "max_ms": ordered[-1],
            "samples_ms": samples}


def measure(query, expected, repetitions: int, warmups: int) -> dict:
    for _ in range(warmups):
        assert query() == expected, "Warmup result differs from verified result"
    samples = []
    for _ in range(repetitions):
        started = time.perf_counter()
        result = query()  # Includes fetching and normalizing the complete result.
        elapsed = (time.perf_counter() - started) * 1000
        assert result == expected, "Timed result differs from verified result"
        samples.append(elapsed)
    return summary(samples)


def benchmark(args) -> dict:
    from pymongo import ASCENDING, MongoClient
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    sql_url = make_url(args.sql_url)
    if sql_url.get_backend_name() not in {"mysql", "mariadb"}:
        raise ValueError("Benchmark requires a real MariaDB/MySQL database; SQLite is rejected")
    engine = create_engine(sql_url, pool_pre_ping=True)
    mongo_client = MongoClient(args.mongo_url, serverSelectionTimeoutMS=5000)
    mongo_client.admin.command("ping")
    database = mongo_client[args.mongo_database]
    collection = database.benchmark_reviews
    try:
        with engine.begin() as conn:
            sql_version = conn.execute(text("SELECT VERSION()")).scalar_one()
            conn.execute(text("""CREATE TABLE IF NOT EXISTS benchmark_reviews (
                id INTEGER PRIMARY KEY, branch_id INTEGER NOT NULL,
                rating INTEGER NOT NULL,
                INDEX ix_benchmark_branch_rating (branch_id, rating)
            ) ENGINE=InnoDB"""))
            conn.execute(text("""CREATE TABLE IF NOT EXISTS benchmark_review_tags (
                review_id INTEGER NOT NULL, tag VARCHAR(50) NOT NULL,
                PRIMARY KEY (review_id, tag), INDEX ix_benchmark_tag (tag)
            ) ENGINE=InnoDB"""))
        mongo_version = mongo_client.server_info()["version"]
        collection.create_index([("branch_id", ASCENDING), ("rating", ASCENDING)],
                                name="ix_benchmark_branch_rating")
        output = {"generated_at": datetime.now(timezone.utc).isoformat(),
                  "workload": "Low-rating complaint tag counts for one branch",
                  "fixture_type": "synthetic, identical across databases",
                  "seed": args.seed, "warmups": args.warmups,
                  "repetitions": args.repetitions, "branch_id": args.branch_id,
                  "environment": {"python": platform.python_version(),
                    "platform": platform.platform(), "cpu_count": os.cpu_count(),
                    "sql_version": sql_version, "mongo_version": mongo_version,
                    "sql_host": sql_url.host, "sql_database": sql_url.database,
                    "mongo_database": args.mongo_database,
                    "connector_versions": {name: importlib.metadata.version(name)
                       for name in ("sqlalchemy", "pymongo")}},
                  "sql_query": SQL_QUERY, "mongo_pipeline": pipeline(args.branch_id),
                  "results": [],
                  "limitations": ["One workload; not a general SQL versus NoSQL ranking.",
                    "Warm-cache timings include connector/network and full result fetching.",
                    "Generated reviews do not imply real customer feedback.",
                    "Database caches, CPU quotas and background processes affect timings."]}
        for size in args.sizes:
            fixture = records(size, args.seed)
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM benchmark_review_tags"))
                conn.execute(text("DELETE FROM benchmark_reviews"))
                for start in range(0, size, 1000):
                    batch = fixture[start:start + 1000]
                    conn.execute(text("INSERT INTO benchmark_reviews(id,branch_id,rating) "
                                      "VALUES (:id,:branch_id,:rating)"),
                                 [{"id": row["_id"], "branch_id": row["branch_id"],
                                   "rating": row["rating"]} for row in batch])
                    tag_rows = [{"review_id": row["_id"], "tag": tag}
                                for row in batch for tag in row["tags"]]
                    if tag_rows:
                        conn.execute(text("INSERT INTO benchmark_review_tags(review_id,tag) "
                                          "VALUES (:review_id,:tag)"), tag_rows)
            collection.delete_many({})
            if fixture:
                for start in range(0, size, 1000):
                    collection.insert_many(fixture[start:start + 1000])
            with engine.connect() as conn:
                def sql_query():
                    return [{"tag": row.tag, "count": int(row.count)} for row in
                            conn.execute(text(SQL_QUERY), {"branch_id": args.branch_id})]
                def mongo_query():
                    return [{"tag": row["_id"], "count": row["count"]}
                            for row in collection.aggregate(pipeline(args.branch_id))]
                expected = sql_query()
                if mongo_query() != expected:
                    raise AssertionError("SQL/Mongo answers disagree; no benchmark claims emitted")
                sql_count = conn.execute(text("SELECT COUNT(*) FROM benchmark_reviews")).scalar_one()
                mongo_count = collection.count_documents({})
                assert sql_count == mongo_count == size, "Fixture counts disagree"
                sql_plan = [dict(row) for row in conn.execute(
                    text("EXPLAIN " + SQL_QUERY), {"branch_id": args.branch_id}).mappings()]
                mongo_plan = database.command("explain", {
                    "aggregate": collection.name, "pipeline": pipeline(args.branch_id),
                    "cursor": {}}, verbosity="executionStats")
                # Alternate which store runs first to reduce systematic run-order bias.
                query_order = [("sql", sql_query), ("mongo", mongo_query)]
                if len(output["results"]) % 2:
                    query_order.reverse()
                timings = {name: measure(query, expected, args.repetitions, args.warmups)
                           for name, query in query_order}
                result = {"size": size, "answers_verified_equal": True,
                          "review_count_sql": sql_count, "review_count_mongo": mongo_count,
                          "answer": expected, **timings,
                          "sql_plan": sql_plan, "mongo_plan": mongo_plan}
                output["results"].append(result)
                print(f"Verified {size} identical reviews: SQL median "
                      f"{timings['sql']['median_ms']:.3f} ms; Mongo median "
                      f"{timings['mongo']['median_ms']:.3f} ms", flush=True)
        return output
    finally:
        engine.dispose()
        mongo_client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sql-url", default=os.environ.get("SQL_URL"))
    parser.add_argument("--mongo-url", default=os.environ.get("MONGO_URL"))
    parser.add_argument("--mongo-database", default="hawkerflow_benchmark")
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000, 100000])
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--branch-id", type=int, default=1)
    parser.add_argument("--repetitions", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("evidence/benchmark.json"))
    args = parser.parse_args()
    if not args.sql_url or not args.mongo_url:
        parser.error("Set SQL_URL and MONGO_URL or supply both URLs explicitly")
    if min(args.sizes) < 1 or args.repetitions < 2 or args.warmups < 0:
        parser.error("Sizes must be positive, repetitions >=2 and warmups >=0")
    result = benchmark(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, default=str) + "\n")
    csv_path = args.output.with_suffix(".csv")
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["size", "database", "median_ms", "p95_ms"])
        writer.writeheader()
        for row in result["results"]:
            for name in ("sql", "mongo"):
                writer.writerow({"size": row["size"], "database": name,
                                 "median_ms": row[name]["median_ms"],
                                 "p95_ms": row[name]["p95_ms"]})
    print(f"Saved measured JSON to {args.output} and CSV to {csv_path}")


if __name__ == "__main__":
    main()
