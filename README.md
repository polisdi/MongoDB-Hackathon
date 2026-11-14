# Scoped Memory Agent

An invoice-handling agent whose memory is **scoped per client, expires, can be corrected or forgotten, and is proven to change what the agent does**, not just what it says.

Built at the MongoDB Agents in Context Toronto Hackathon, Nov 14, 2026. Track: **Memory You Can Govern**. All code in this repo was written during the event; see the commit history.

## The three track questions

| Question | How we answer it |
|---|---|
| How do you keep one client's memory from leaking into another's? | `client_id` comes from the session, never the model. Atlas Vector Search pre-filters on it, code re-checks every result, and `$jsonSchema` validation rejects any memory without a `client_id`. |
| How does the agent fix or drop a wrong or expired memory? | Corrections create a new version in a transaction and mark the old one `superseded`. Forgetting removes text and embedding but keeps an audit stub. Every read filters on `expires_at`, using a simulated clock. |
| How do you prove memory changed behaviour? | An ablation runner replays the same decision with one memory hidden: **escalate 100% with the memory, 0% without (n=5)**. A control memory shows **+0% effect**. |

## Architecture

```
invoice ─▶ LangGraph: load → recall → decide → validate → act → log
                         │                         │
                MemoryGovernor               decisions (audit)
                (the only code that
                 touches memories)
                         │
        MongoDB Atlas: memories (+ vector index, TTL, schema validation),
                       memory_events, decisions, ablation_runs
```

- **The model never governs memory; code does.** The LLM only reads the memories it's handed and returns a structured decision `{action, target_person, reason, memory_ids_used}`.
- **The model's "used" claim isn't trusted.** It's filtered against what was actually retrieved, and the ablation is the real proof.
- **Ablation runs never touch the mock systems** (`mode: "ablated"`).

## Stack

MongoDB Atlas (Sandbox) · Atlas Vector Search with filters on `client_id`, `status`, `expires_at` · LangGraph · Pydantic structured output · FastAPI + plain HTML · hosted LLM for decisions · local embeddings (nomic-embed-text v1.5 via LM Studio).

## Run it

```bash
uv sync
cp .env.example .env        # fill in MONGODB_URI, LLM_*, EMBED_*
python3 setup_db.py         # collections, validation, indexes
python3 seed.py             # 2 clients, 6 memories, 6 invoices
python3 -m uvicorn app:app --port 8000
curl -X POST "localhost:8000/ablate?n=5"   # precompute the proof
```

Open http://localhost:8000 and follow beats 1–5.

## Demo beats

1. **Agent works:** a $7,200 invoice escalates because of a client rule.
2. **Proof:** hiding that memory flips the action, 100% → 0%; the control has no effect.
3. **Isolation:** client B can't retrieve client A's memories; an unscoped write is rejected by Atlas.
4. **Correct and expire:** the owner raises the limit, the rule is superseded with history, and the next run approves. A +200 day jump expires the rule.
5. **Forget:** the duplicate-check memory is forgotten; the invoice goes from hold to approve, and only an audit stub remains.

## Known limits

- Two clients and fictional data; mock accounting systems are Atlas collections.
- Ablation is per decision and per memory, not yet automated across all memories.
- Duplicate detection on write uses a similarity threshold that needs tuning per embedding model.

