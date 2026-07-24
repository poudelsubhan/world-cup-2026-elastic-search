# World Cup 2026 — Elastic Semantic Search & Prediction Agents

**A live 2026 FIFA World Cup match predictor and semantic "vibe search" match explorer, built on Elasticsearch Serverless, Elastic Agent Builder, and AWS Bedrock via the Elastic Inference Service (EIS) — zero LLM API keys required.**

Two AI agents run on top of one continuously-updating Elasticsearch dataset:

- **Predictor agent** — ask *"Predict Paraguay vs France"* or *"Compare Brazil and Morocco based on their 2026 results"* and get a grounded prediction, backed by custom **ES|QL** tools that aggregate real match data (form, standings, head-to-head) — no hallucinated stats.
- **Match Explorer agent** — ask *"Show me the most dramatic comebacks of the tournament"* and get results from **semantic vector search** over AI-generated natural-language narratives of every played match, auto-embedded by EIS on AWS Bedrock at index time.

Both indices are kept fresh by lightweight Python pollers that re-fetch tournament results and upsert/re-embed only what changed — so the agents are always talking about tonight's real scores, not a static snapshot.

## How it works

```
openfootball/worldcup.json (public JSON API)
              │
   ┌──────────┴──────────┐
   ▼                      ▼
poll_live.py        build_narratives.py
(upsert every       (generate + embed narrative
 N seconds)           per played match, incremental)
   │                      │
   ▼                      ▼
wc2026_matches        wc2026_narratives
(structured index,    (semantic_text field,
 ES|QL analytics)      auto-embedded via EIS/Bedrock)
   │                      │
   ▼                      ▼
Predictor Agent       Match Explorer Agent
(ES|QL custom tools:  (Index Search / semantic
 form, stats,          query — "dramatic comebacks",
 fixtures, standings)  "tight knockout games", ...)
```

- **`world_cup_predictor.ipynb`** — the initial data-ingest notebook: fetches the full 2026 tournament schedule/results, builds the `wc2026_matches` mapping (nested goals, stage, winner, etc.), and bulk-indexes everything into Elasticsearch Serverless.
- **`poll_live.py`** — a live-ish poller that re-fetches results on an interval and **upserts** into `wc2026_matches` with deterministic per-match IDs, so an "upcoming" fixture flips to "played" in place instead of duplicating documents.
- **`build_narratives.py`** — generates a natural-language story for every played match (margin, comeback detection, scorer clauses) and indexes it into `wc2026_narratives` as a `semantic_text` field. EIS auto-embeds it on AWS Bedrock at index time — no model deployment, no separate API keys. Incremental by design: a match is only (re-)embedded when its narrative text is new or changed.
- **`DEMO.md`** — a 90-second demo script covering both agents, sample prompts, and a Dev Tools query that proves the semantic search is real vector similarity, not keyword matching.

## Tech stack

`Elasticsearch` `Elastic Serverless` `Elastic Agent Builder` `Elastic Inference Service (EIS)` `AWS Bedrock` `semantic_text` `vector search` `kNN` `ES|QL` `RAG` `retrieval-augmented generation` `Python` `openfootball` `sports analytics` `FIFA World Cup 2026`

## Setup

Requirements: Python 3.9+, an [Elastic Cloud Serverless](https://www.elastic.co/cloud/cloud-trial-overview) project, and its endpoint + API key.

```bash
pip install elasticsearch requests
cp .env .env.local   # or just export directly
export ELASTIC_ENDPOINT="https://your-project.es.region.aws.elastic.cloud:443"
export ELASTIC_API_KEY="your-elastic-api-key"
```

1. Run `world_cup_predictor.ipynb` once to create and populate `wc2026_matches`.
2. Build the semantic index:
   ```bash
   python build_narratives.py            # incremental one-shot
   python build_narratives.py --watch --interval 120
   ```
3. Keep raw results current:
   ```bash
   python poll_live.py --interval 120
   ```
4. In Kibana, wire up **Agent Builder** agents on top of the two indices — see `agent_builder_guide.md` and `starter_project.md` for the ES|QL tool definitions and agent configs used here, and `eis_guide.md` for using EIS as the agent LLM and embedding model with zero keys.

## Proof it's real semantic search

```
GET wc2026_narratives/_search
{
  "query": { "semantic": { "field": "narrative", "query": "tense low-scoring knockout games" } }
}
```

The word "comeback" or "knockout" is never stored as a filter — matches are ranked by embedding similarity over the generated narrative text.

## Repository layout

| path | what it is |
|---|---|
| `world_cup_predictor.ipynb` | one-time ingest notebook: fetch, enrich, bulk-index `wc2026_matches` |
| `build_narratives.py` | generates + incrementally embeds match narratives into `wc2026_narratives` |
| `poll_live.py` | live upsert poller for `wc2026_matches` |
| `DEMO.md` | 90-second demo script and judge cheat sheet |
| `agent_builder_guide.md` | reference for building Elastic Agent Builder tools/agents |
| `eis_guide.md` | reference for using Elastic Inference Service (Bedrock-hosted LLM/embeddings, no keys) |
| `starter_project.md`, `open_challenge.md` | original event background/prompts this project grew out of |

## Credential handling

`.env` is gitignored and never committed. The notebook ships with placeholder `ELASTIC_ENDPOINT`/`ELASTIC_API_KEY` values — fill in your own Elastic Cloud Serverless credentials locally; never commit real ones.

## Background

Built during Elastic's **AWS Hack Night (World Cup Edition)**. The starter notebook and event docs (`README` content below the fold, `agent_builder_guide.md`, `eis_guide.md`, `open_challenge.md`, `starter_project.md`) were provided by the organizers; the live-updating pollers, the semantic Match Explorer agent, and the incremental embedding pipeline were built at the event.

---

*Topics: Elasticsearch · Elastic Serverless · Elastic Agent Builder · Elastic Inference Service (EIS) · AWS Bedrock · semantic search · semantic_text · vector search · kNN · ES|QL · retrieval-augmented generation (RAG) · AI agents · sports analytics · FIFA World Cup 2026 · Python*
