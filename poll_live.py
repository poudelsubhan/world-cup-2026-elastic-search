#!/usr/bin/env python3
"""
Live-ish poller for the 2026 World Cup index.

Re-fetches openfootball and UPSERTS matches into wc2026_matches on an interval,
so newly-finished results and score corrections land within minutes without
dropping the index (unlike the notebook, which deletes+recreates each run).

Uses a deterministic _id per match so an "upcoming" fixture is updated in place
when it becomes "played".

Usage:
    export ELASTIC_ENDPOINT="https://your-project.es.region.aws.elastic.cloud:443"
    export ELASTIC_API_KEY="your-api-key"
    python poll_live.py                 # poll every 300s (default)
    python poll_live.py --interval 120  # poll every 2 minutes
    python poll_live.py --once          # single pass, then exit
"""
import argparse
import hashlib
import os
import sys
import time

import requests
from elasticsearch import Elasticsearch, helpers

DATA_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"
INDEX = "wc2026_matches"

MAPPING = {
    "mappings": {
        "properties": {
            "date": {"type": "date"},
            "round": {"type": "keyword"},
            "group": {"type": "keyword"},
            "stadium": {"type": "keyword"},
            "stage": {"type": "keyword"},
            "status": {"type": "keyword"},
            "team1": {"type": "keyword"},
            "team2": {"type": "keyword"},
            "score_ft1": {"type": "integer"},
            "score_ft2": {"type": "integer"},
            "score_ht1": {"type": "integer"},
            "score_ht2": {"type": "integer"},
            "total_goals": {"type": "integer"},
            "winner": {"type": "keyword"},
            "team1_win": {"type": "boolean"},
            "team2_win": {"type": "boolean"},
            "goals": {
                "type": "nested",
                "properties": {
                    "scorer": {"type": "keyword"},
                    "minute": {"type": "keyword"},
                    "team": {"type": "keyword"},
                    "type": {"type": "keyword"},
                },
            },
        }
    }
}

ROUND_TO_STAGE = {
    "Round of 32": "round_of_32",
    "Round of 16": "round_of_16",
    "Quarter-finals": "quarter",
    "Semi-finals": "semi",
    "Match for third place": "third_place",
    "Final": "final",
}


def round_to_stage(round_name):
    return ROUND_TO_STAGE.get(round_name, "group")


def match_id(m):
    """Stable id so re-ingesting the same fixture updates it in place."""
    key = f"{m['date']}|{m['team1']}|{m['team2']}|{m['round']}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]


def enrich(m):
    doc = {
        "date": m["date"],
        "round": m["round"],
        "group": m.get("group", "Knockout"),
        "stadium": m.get("ground", ""),
        "stage": round_to_stage(m["round"]),
        "team1": m["team1"],
        "team2": m["team2"],
    }

    if "score" in m:
        ft1, ft2 = m["score"]["ft"]
        ht = m["score"].get("ht", [None, None])
        if ft1 > ft2:
            winner = m["team1"]
        elif ft2 > ft1:
            winner = m["team2"]
        else:
            winner = "draw"
        doc.update({
            "status": "played",
            "score_ft1": ft1,
            "score_ft2": ft2,
            "score_ht1": ht[0],
            "score_ht2": ht[1],
            "total_goals": ft1 + ft2,
            "winner": winner,
            "team1_win": winner == m["team1"],
            "team2_win": winner == m["team2"],
        })
        goals = []
        for g in m.get("goals1", []):
            goals.append({
                "scorer": g["name"],
                "minute": g.get("minute", ""),
                "team": m["team1"],
                "type": "own_goal" if g.get("owngoal") else ("penalty" if g.get("penalty") else "goal"),
            })
        for g in m.get("goals2", []):
            goals.append({
                "scorer": g["name"],
                "minute": g.get("minute", ""),
                "team": m["team2"],
                "type": "own_goal" if g.get("owngoal") else ("penalty" if g.get("penalty") else "goal"),
            })
        doc["goals"] = goals
    else:
        doc["status"] = "upcoming"

    return doc


def ensure_index(es):
    if not es.indices.exists(index=INDEX):
        es.indices.create(index=INDEX, body=MAPPING)
        print(f"✅ Created index: {INDEX}")


def poll_once(es):
    resp = requests.get(DATA_URL, timeout=15)
    resp.raise_for_status()
    matches = resp.json()["matches"]

    actions = [
        {"_op_type": "index", "_index": INDEX, "_id": match_id(m), "_source": enrich(m)}
        for m in matches
    ]
    success, errors = helpers.bulk(es, actions)
    es.indices.refresh(index=INDEX)

    played = sum(1 for m in matches if "score" in m)
    upcoming = len(matches) - played
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] upserted {success} docs ({len(errors)} errors) — {played} played, {upcoming} upcoming")


def main():
    parser = argparse.ArgumentParser(description="Live-ish World Cup poller")
    parser.add_argument("--interval", type=int, default=300, help="seconds between polls (default 300)")
    parser.add_argument("--once", action="store_true", help="run a single pass and exit")
    parser.add_argument("--rebuild", action="store_true",
                        help="delete + recreate the index first (removes any docs with mismatched IDs), then poll")
    args = parser.parse_args()

    endpoint = os.environ.get("ELASTIC_ENDPOINT")
    api_key = os.environ.get("ELASTIC_API_KEY")
    if not endpoint or not api_key:
        sys.exit("Set ELASTIC_ENDPOINT and ELASTIC_API_KEY environment variables first.")

    es = Elasticsearch(endpoint, api_key=api_key)
    print(f"✅ Connected to Elasticsearch {es.info()['version']['number']}")

    if args.rebuild and es.indices.exists(index=INDEX):
        es.indices.delete(index=INDEX)
        print(f"🗑️  Deleted existing index: {INDEX}")
    ensure_index(es)

    if args.once:
        poll_once(es)
        return

    print(f"⏱  Polling every {args.interval}s. Ctrl+C to stop.")
    try:
        while True:
            try:
                poll_once(es)
            except Exception as e:  # keep the loop alive on transient errors
                print(f"⚠️  poll failed: {e}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n👋 Stopped.")


if __name__ == "__main__":
    main()
