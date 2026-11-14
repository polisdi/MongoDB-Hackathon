import os
from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING
from pymongo.errors import CollectionInvalid
from pymongo.operations import SearchIndexModel

load_dotenv()
db = MongoClient(os.environ["MONGODB_URI"])[os.environ["DB_NAME"]]
DIM = int(os.environ["EMBED_DIM"])

MEMORY_SCHEMA = {"$jsonSchema": {
    "bsonType": "object",
    "required": ["client_id", "kind", "status", "source", "created_at", "expires_at"],
    "properties": {
        "client_id": {"bsonType": "string", "minLength": 1},
        "kind": {"enum": ["rule", "fact", "preference"]},
        "status": {"enum": ["active", "superseded", "forgotten"]},
        "source": {"bsonType": "object", "required": ["type"],
                   "properties": {"type": {"enum": ["user_stated", "system_record", "agent_inferred"]}}},
        "text": {"bsonType": "string"},
        "embedding": {"bsonType": "array"},
        "created_at": {"bsonType": "date"},
        "expires_at": {"bsonType": "date"},
        "purge_at": {"bsonType": "date"},
        "version": {"bsonType": "int"},
    },
}}

DECISION_SCHEMA = {"$jsonSchema": {
    "bsonType": "object",
    "required": ["run_id", "client_id", "invoice_id", "mode", "action",
                 "retrieved_memory_ids", "used_memory_ids", "at"],
    "properties": {
        "client_id": {"bsonType": "string", "minLength": 1},
        "mode": {"enum": ["normal", "ablated"]},
        "action": {"enum": ["approve", "escalate", "hold"]},
        "retrieved_memory_ids": {"bsonType": "array"},
        "used_memory_ids": {"bsonType": "array"},
        "at": {"bsonType": "date"},
    },
}}

def ensure(name, schema=None):
    try:
        kwargs = {"validator": schema, "validationAction": "error"} if schema else {}
        db.create_collection(name, **kwargs)
    except CollectionInvalid:
        if schema:
            db.command("collMod", name, validator=schema, validationAction="error")

ensure("memories", MEMORY_SCHEMA)
ensure("decisions", DECISION_SCHEMA)
for name in ["memory_events", "ablation_runs", "invoices", "ledger", "approvals"]:
    ensure(name)

db.memories.create_index([("purge_at", ASCENDING)], expireAfterSeconds=0)
db.memories.create_index([("client_id", ASCENDING), ("status", ASCENDING)])
db.decisions.create_index([("invoice_id", ASCENDING), ("mode", ASCENDING)])
db.memory_events.create_index([("memory_id", ASCENDING), ("at", ASCENDING)])

existing = [i["name"] for i in db.memories.list_search_indexes()]
if "memory_vector" not in existing:
    db.memories.create_search_index(SearchIndexModel(
        name="memory_vector",
        type="vectorSearch",
        definition={"fields": [
            {"type": "vector", "path": "embedding", "numDimensions": DIM, "similarity": "cosine"},
            {"type": "filter", "path": "client_id"},
            {"type": "filter", "path": "status"},
            {"type": "filter", "path": "expires_at"},
            {"type": "filter", "path": "_id"},
        ]},
    ))
print("setup done; vector index building:", list(db.memories.list_search_indexes()))

