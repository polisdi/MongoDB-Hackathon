# uv run python -c "..." or a small test_schema.py
import os, datetime as dt
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import WriteError

load_dotenv()
db = MongoClient(os.environ["MONGODB_URI"])[os.environ["DB_NAME"]]
try:
    db.memories.insert_one({"kind": "rule", "status": "active", "source": {"type": "user_stated"},
                            "created_at": dt.datetime.now(dt.timezone.utc),
                            "expires_at": dt.datetime.now(dt.timezone.utc)})
    print("FAIL: insert without client_id was accepted")
except WriteError as e:
    print("OK: rejected ->", e.details.get("errmsg"))

