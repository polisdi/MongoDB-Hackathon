import datetime as dt
from common import db, embed, now, log_event

LIFETIME_DAYS = {"rule": 180, "fact": 30, "preference": 90}
INFERRED_MAX_DAYS = 7
#DUP_SCORE = 0.93   # Atlas cosine score = (1 + cos) / 2; tune after printing real scores
DUP_SCORE = 0.96   # Atlas cosine score = (1 + cos) / 2; tune after printing real scores

class ScopeViolation(Exception):
    pass

class MemoryGovernor:
    """The only code allowed to touch db.memories."""

    def recall(self, client_id: str, query: str, k: int = 5,
               exclude_ids: list[str] | None = None, run_id: str | None = None,
               log: bool = True) -> list[dict]:
        if not client_id:
            raise ScopeViolation("client_id is required")
        exclude_ids = exclude_ids or []
        t = now()
        filt = {"client_id": {"$eq": client_id},
                "status": {"$eq": "active"},
                "expires_at": {"$gt": t}}
        if exclude_ids:
            filt["_id"] = {"$nin": exclude_ids}
        pipeline = [
            {"$vectorSearch": {"index": "memory_vector", "path": "embedding",
                               "queryVector": embed(query, "query"),
                               "numCandidates": 100, "limit": k, "filter": filt}},
            {"$project": {"embedding": 0, "score": {"$meta": "vectorSearchScore"}}},
        ]
        results = list(db.memories.aggregate(pipeline))
        for m in results:   # belt and braces: never trust a single layer
            if m["client_id"] != client_id or m["_id"] in exclude_ids:
                raise ScopeViolation(f"{m['_id']} leaked into {client_id}")
        if log and results:
            db.memory_events.insert_many([{"memory_id": m["_id"], "client_id": client_id,
                                           "event": "read", "actor": "agent", "run_id": run_id,
                                           "at": t} for m in results])
        return results

    def write(self, client_id: str, kind: str, text: str, source_type: str,
              by: str, lifetime_days: int | None = None) -> str:
        """Model output is a proposal; scope and lifetime are set here, not by the model."""
        if source_type not in ("user_stated", "system_record", "agent_inferred"):
            log_event(None, client_id, "rejected", by)
            raise ValueError("unknown source type")
        max_days = INFERRED_MAX_DAYS if source_type == "agent_inferred" else LIFETIME_DAYS[kind]
        days = min(lifetime_days or max_days, max_days)
        # near-duplicate in the SAME client -> supersede instead of insert
        dup = self.recall(client_id, text, k=1, log=False)
        if dup and dup[0]["score"] >= DUP_SCORE and dup[0]["kind"] == kind:
            return self.correct(dup[0]["_id"], text, by)
        t = now()
        mid = f"mem_{client_id}_{int(t.timestamp() * 1000)}"
        db.memories.insert_one({
            "_id": mid, "client_id": client_id, "kind": kind, "text": text,
            "embedding": embed(text, "document"),
            "source": {"type": source_type, "by": by}, "status": "active",
            "created_at": t, "expires_at": t + dt.timedelta(days=days),
            "purge_at": t + dt.timedelta(days=days + 30),
            "supersedes": None, "superseded_by": None, "version": 1,
        })
        log_event(mid, client_id, "created", by)
        return mid

    def correct(self, memory_id: str, new_text: str, by: str) -> str:
        old = db.memories.find_one({"_id": memory_id, "status": "active"})
        if not old:
            raise ValueError(f"{memory_id} not active")
        t = now()
        base = memory_id.split("__v")[0]
        new_id = f"{base}__v{old['version'] + 1}"
        days = LIFETIME_DAYS[old["kind"]]
        new_doc = {**{k: v for k, v in old.items() if k != "_id"},
                   "_id": new_id, "text": new_text, "embedding": embed(new_text, "document"),
                   "source": {"type": "user_stated", "by": by},
                   "created_at": t, "expires_at": t + dt.timedelta(days=days),
                   "purge_at": t + dt.timedelta(days=days + 30),
                   "supersedes": memory_id, "superseded_by": None,
                   "version": old["version"] + 1}
        with db.client.start_session() as s, s.start_transaction():
            db.memories.insert_one(new_doc, session=s)
            db.memories.update_one({"_id": memory_id},
                                   {"$set": {"status": "superseded", "superseded_by": new_id}},
                                   session=s)
        log_event(memory_id, old["client_id"], "superseded", by)
        log_event(new_id, old["client_id"], "created", by)
        return new_id

    def forget(self, memory_id: str, by: str, reason: str):
        m = db.memories.find_one({"_id": memory_id})
        if not m:
            raise ValueError(f"{memory_id} not found")
        db.memories.update_one({"_id": memory_id},
                               {"$set": {"status": "forgotten",
                                         "forgotten": {"by": by, "reason": reason, "at": now()}},
                                "$unset": {"text": "", "embedding": ""}})
        log_event(memory_id, m["client_id"], "forgotten", by)

    def history(self, memory_id: str) -> list[dict]:
        return list(db.memory_events.find({"memory_id": memory_id}, {"_id": 0}).sort("at", 1))

