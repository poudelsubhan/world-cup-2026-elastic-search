#!/usr/bin/env python3
"""
Build the Semantic Match Explorer index.

Fetches 2026 World Cup results from openfootball, writes a natural-language
narrative for each PLAYED match, and indexes them into `wc2026_narratives`
with a `semantic_text` field. On Serverless, semantic_text auto-embeds via
EIS (AWS Bedrock) at index time — no model to deploy, no keys.

Then you can semantically search matches, e.g. "dramatic late comebacks" or
"tight low-scoring knockout games", via an Agent Builder Index Search tool.

Incremental by default: each match gets a deterministic _id and is only
(re-)embedded when its narrative text is new or has changed — so a match
flipping upcoming->played costs exactly one EIS embedding call, not 81.

Usage:
    set -a && . ./.env && set +a
    python build_narratives.py                 # incremental one-shot
    python build_narratives.py --watch         # poll + embed changes every 300s
    python build_narratives.py --watch --interval 120
    python build_narratives.py --rebuild       # wipe + re-embed everything
"""
import argparse
import hashlib
import os
import sys
import time

import requests
from elasticsearch import Elasticsearch, helpers

DATA_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"
INDEX = "wc2026_narratives"

MAPPING = {
    "mappings": {
        "properties": {
            # The semantic field — auto-embedded by EIS at index time.
            "narrative": {"type": "semantic_text"},
            # Structured fields for display / filtering alongside semantic hits.
            "date": {"type": "date"},
            "round": {"type": "keyword"},
            "stage": {"type": "keyword"},
            "group": {"type": "keyword"},
            "team1": {"type": "keyword"},
            "team2": {"type": "keyword"},
            "score": {"type": "keyword"},
            "winner": {"type": "keyword"},
            "total_goals": {"type": "integer"},
            "margin": {"type": "integer"},
            "was_comeback": {"type": "boolean"},
            "stadium": {"type": "keyword"},
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


def match_id(m):
    """Stable id so re-runs update a match in place instead of duplicating."""
    key = f"{m['date']}|{m['team1']}|{m['team2']}|{m['round']}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]


def margin_phrase(m):
    if m == 0:
        return "level"
    if m == 1:
        return "by the narrowest margin"
    if m in (2, 3):
        return "comfortably"
    return "in a thrashing"


def scorers_clause(m):
    parts = []
    for side, team in (("goals1", m["team1"]), ("goals2", m["team2"])):
        for g in m.get(side, []):
            tag = " (pen)" if g.get("penalty") else (" (o.g.)" if g.get("owngoal") else "")
            minute = f"{g['minute']}'" if g.get("minute") else ""
            parts.append(f"{g['name']}{tag} {minute} for {team}".strip())
    if not parts:
        return ""
    return " Goals: " + "; ".join(parts) + "."


def build_narrative(m):
    ft1, ft2 = m["score"]["ft"]
    ht = m["score"].get("ht", [None, None])
    t1, t2 = m["team1"], m["team2"]
    stage_name = m["round"]
    venue = m.get("ground", "")
    total = ft1 + ft2
    margin = abs(ft1 - ft2)

    if ft1 > ft2:
        winner, loser, ws, ls = t1, t2, ft1, ft2
        headline = f"{winner} beat {loser} {ws}-{ls} {margin_phrase(margin)}"
    elif ft2 > ft1:
        winner, loser, ws, ls = t2, t1, ft2, ft1
        headline = f"{winner} beat {loser} {ws}-{ls} {margin_phrase(margin)}"
    else:
        winner = "draw"
        headline = f"{t1} and {t2} drew {ft1}-{ft2}"

    # Comeback detection: team behind at half-time avoided defeat / won.
    was_comeback = False
    comeback_clause = ""
    if ht[0] is not None and ht[1] is not None:
        ht1, ht2 = ht
        # Who was ahead at the break vs the final result winner.
        if ht1 != ht2:
            ht_leader = t1 if ht1 > ht2 else t2
            if winner == "draw" and ht_leader in (t1, t2):
                was_comeback = True
                trailer = t2 if ht_leader == t1 else t1
                comeback_clause = f" {trailer} fought back from {ht1}-{ht2} at half-time to snatch a draw."
            elif winner != "draw" and winner != ht_leader:
                was_comeback = True
                comeback_clause = (
                    f" {winner} completed a comeback, trailing {ht1}-{ht2} at half-time before turning it around."
                )

    goals_clause = scorers_clause(m)
    venue_clause = f" at {venue}" if venue else ""
    group = m.get("group", "Knockout")
    context = f"the {stage_name}" if group == "Knockout" else f"{group}, {stage_name}"

    narrative = (
        f"In {context} of the 2026 World Cup, {headline}{venue_clause}. "
        f"It was a {total}-goal game."
        f"{comeback_clause}{goals_clause}"
    ).strip()

    return {
        "narrative": narrative,
        "date": m["date"],
        "round": stage_name,
        "stage": ROUND_TO_STAGE.get(stage_name, "group"),
        "group": group,
        "team1": t1,
        "team2": t2,
        "score": f"{ft1}-{ft2}",
        "winner": winner,
        "total_goals": total,
        "margin": margin,
        "was_comeback": was_comeback,
        "stadium": venue,
    }


def ensure_index(es):
    if not es.indices.exists(index=INDEX):
        es.indices.create(index=INDEX, body=MAPPING)
        print(f"✅ Created index: {INDEX} (semantic_text auto-embeds via EIS)")


def existing_narratives(es, ids):
    """Return {id: narrative_text} for docs already indexed, to skip unchanged ones."""
    if not ids:
        return {}
    resp = es.mget(index=INDEX, ids=ids, source=["narrative"])
    out = {}
    for d in resp["docs"]:
        if d.get("found"):
            out[d["_id"]] = d["_source"].get("narrative")
    return out


def refresh_once(es):
    matches = requests.get(DATA_URL, timeout=15).json()["matches"]
    played = [m for m in matches if "score" in m]

    docs = {match_id(m): build_narrative(m) for m in played}
    current = existing_narratives(es, list(docs))

    # Only (re-)embed matches whose narrative is new or has changed.
    changed = {i: d for i, d in docs.items() if current.get(i) != d["narrative"]}

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    if not changed:
        print(f"[{ts}] {len(played)} played — no new/changed narratives, nothing to embed")
        return 0

    actions = [{"_index": INDEX, "_id": i, "_source": d} for i, d in changed.items()]
    success, errors = helpers.bulk(es, actions, chunk_size=25)
    es.indices.refresh(index=INDEX)
    print(f"[{ts}] {len(played)} played — embedded {success} new/changed narratives ({len(errors)} errors)")
    return success


def main():
    parser = argparse.ArgumentParser(description="Build/refresh the Semantic Match Explorer index")
    parser.add_argument("--watch", action="store_true", help="poll and embed changes on an interval")
    parser.add_argument("--interval", type=int, default=300, help="seconds between refreshes in --watch (default 300)")
    parser.add_argument("--rebuild", action="store_true", help="wipe the index and re-embed everything")
    args = parser.parse_args()

    endpoint = os.environ.get("ELASTIC_ENDPOINT")
    api_key = os.environ.get("ELASTIC_API_KEY")
    if not endpoint or not api_key:
        sys.exit("Set ELASTIC_ENDPOINT and ELASTIC_API_KEY environment variables first.")

    es = Elasticsearch(endpoint, api_key=api_key, request_timeout=120)
    print(f"✅ Connected to Elasticsearch {es.info()['version']['number']}")

    if args.rebuild and es.indices.exists(index=INDEX):
        es.indices.delete(index=INDEX)
        print(f"🗑️  Deleted existing index: {INDEX}")
    ensure_index(es)

    if not args.watch:
        refresh_once(es)
        return

    print(f"⏱  Watching for match updates every {args.interval}s. Ctrl+C to stop.")
    try:
        while True:
            try:
                refresh_once(es)
            except Exception as e:
                print(f"⚠️  refresh failed: {e}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n👋 Stopped.")


if __name__ == "__main__":
    main()
