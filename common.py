import os, datetime as dt
from dotenv import load_dotenv
from pymongo import MongoClient
from openai import OpenAI

load_dotenv()
db = MongoClient(os.environ["MONGODB_URI"])[os.environ["DB_NAME"]]
llm = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ.get("LLM_API_KEY", "lm-studio"))
embedder = OpenAI(base_url=os.environ["EMBED_BASE_URL"], api_key="lm-studio")
UTC = dt.timezone.utc
DEFAULT_NOW = dt.datetime(2026, 11, 14, 12, 0, tzinfo=UTC)

def now() -> dt.datetime:
    """Simulated clock, shared by agent, API and demo via the db."""
    doc = db.clock.find_one({"_id": "sim"})
    t = doc["now"] if doc else DEFAULT_NOW
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t

def set_now(t: dt.datetime):
    db.clock.update_one({"_id": "sim"}, {"$set": {"now": t}}, upsert=True)

def embed(text: str, kind: str = "document") -> list[float]:
    # nomic-embed expects these prefixes; harmless for most other models
    prefix = "search_document: " if kind == "document" else "search_query: "
    r = embedder.embeddings.create(model=os.environ["EMBED_MODEL"], input=[prefix + text])
    return r.data[0].embedding

def log_event(memory_id, client_id, event, actor, run_id=None):
    db.memory_events.insert_one({"memory_id": memory_id, "client_id": client_id, "event": event,
                                 "actor": actor, "run_id": run_id, "at": now()})

