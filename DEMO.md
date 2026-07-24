# 🎤 Demo Script: World Cup 2026 on Elasticsearch (90 sec)

**One-liner (memorize this):**
> "I built two AI agents on live 2026 World Cup data in Elastic Agent Builder. One predicts matches with ES|QL analytics, and one lets you search matches by *vibe* using vector search. Both run on AWS Bedrock through Elastic's Inference Service, and the data updates itself as matches finish."

---

## The 3 beats

### Beat 1. Prediction (ES|QL tools) · ~25s
Open **Agents → World Cup 2026 Predictor**. Type:
```
Predict Paraguay vs France
```
**Say while it runs:** "Watch the thinking trace. It's calling three custom ES|QL tools I built: upcoming fixtures, team stats, and form, one per team. Every number is a real aggregation over my `wc2026_matches` index. No hallucination, it's grounded in the data."

### Beat 2. Semantic search (vector + EIS/Bedrock) · ~35s  ⭐ the wow
Open **Agents → World Cup 2026 Match Explorer**. Type:
```
Show me the most dramatic comebacks of the tournament
```
**Say while it runs:** "This one's different. I generated a natural-language *story* for every played match and indexed it into a `semantic_text` field. Elastic auto-embedded them on AWS Bedrock via the Inference Service: zero API keys, zero model deployment. So 'dramatic comebacks' isn't keyword matching; it's vector similarity. I never stored the word 'comeback' as a filter. It *understands* the query."

Follow up (shows the discovery → drill-down arc):
```
Now show me England's full run
```

### Beat 3. It's alive · ~20s
**Say (no need to run):** "And it's not a snapshot. A poller re-ingests results every couple minutes, and when a match ends it embeds *just that one* new narrative. Incremental, so it's cheap. The demo you're seeing is tonight's real results."

---

## Close (memorize)
> "So: two agents, ES|QL aggregations *and* semantic vector search, live-updating data, all on Bedrock via EIS with no keys. Thanks!"

---

## Cheat sheet, if a judge asks "show me the Elasticsearch"
- **Custom tools:** `get_team_form`, `get_team_stats_2026`, `get_upcoming_fixtures`, `get_group_standings` (ES|QL) + `search_match_narratives` (Index Search / semantic).
- **The semantic query** (paste in Dev Tools to prove it):
  ```
  GET wc2026_narratives/_search
  {
    "query": { "semantic": { "field": "narrative", "query": "tense low-scoring knockout games" } }
  }
  ```
- **Bedrock proof:** `GET _inference` → the `chat_completion` + embedding endpoints with `service: elastic` are Elastic Managed LLMs on AWS Bedrock.
- **Two indexes:** `wc2026_matches` (structured, for analytics) and `wc2026_narratives` (semantic_text, for vector search).

## Backup prompts (if one falls flat)
- Explorer: `Which games were tight low-scoring knockout battles?` · `Find the biggest thrashings`
- Predictor: `Compare Brazil and Morocco based on their 2026 results` · `Show me the Group A standings`

## Pre-demo checklist
- [ ] Both agents open in separate tabs
- [ ] `python poll_live.py --interval 120` running (raw results)
- [ ] `python build_narratives.py --watch --interval 120` running (narratives)
- [ ] Ran each prompt once beforehand so results are warm
