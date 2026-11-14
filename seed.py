import datetime as dt
from common import db, embed, set_now, log_event, DEFAULT_NOW

D = lambda y, m, d: dt.datetime(y, m, d, tzinfo=dt.timezone.utc)
DAYS = lambda n: dt.timedelta(days=n)
LIFETIME = {"rule": 180, "fact": 30, "preference": 90}

for c in ["memories", "decisions", "memory_events", "ablation_runs",
          "invoices", "ledger", "approvals", "clients", "clock"]:
    db[c].delete_many({})   # keep collections, validators, indexes
set_now(DEFAULT_NOW)

db.clients.insert_many([
    {"_id": "client_a", "name": "Lakeview Dental Clinic",
     "people": {"owner": "Dr. Ana Moreau", "office_manager": "Priya Shah"}},
    {"_id": "client_b", "name": "Maple Street Bakery",
     "people": {"owner": "Tom Becker", "manager": "Lena Ortiz"}},
])

MEMS = [
    # id, client, kind, text, source_type, created
    ("mem_a_rule_5k", "client_a", "rule",
     "Never auto-approve invoices over $5,000. Escalate them to the office manager for approval.",
     "user_stated", D(2026, 10, 1)),
    ("mem_a_fact_pearl_dup", "client_a", "fact",
     "Vendor Pearl Dental Lab billed the same invoice twice in October. Hold Pearl Dental Lab invoices and check for duplicates.",
     "system_record", D(2026, 10, 25)),
    ("mem_a_pref_pay_due", "client_a", "preference",
     "Client prefers bills paid on the due date, not early.",
     "user_stated", D(2026, 9, 20)),
    ("mem_b_rule_known", "client_b", "rule",
     "Invoices from known suppliers Golden Mill Flour and Daily Dairy can be auto-approved.",
     "user_stated", D(2026, 9, 15)),
    ("mem_b_rule_flour", "client_b", "rule",
     "Flour supplier invoices over $2,000 go to the owner for approval, not the manager.",
     "user_stated", D(2026, 10, 10)),
    ("mem_b_rule_5k", "client_b", "rule",
     "Invoices over $5,000 need the owner's approval.",
     "user_stated", D(2026, 10, 12)),
]

for mid, client, kind, text, src, created in MEMS:
    expires = created + DAYS(LIFETIME[kind])
    db.memories.insert_one({
        "_id": mid, "client_id": client, "kind": kind, "text": text,
        "embedding": embed(text, "document"),
        "source": {"type": src, "by": "seed"},
        "status": "active", "created_at": created, "expires_at": expires,
        "purge_at": expires + DAYS(30),
        "supersedes": None, "superseded_by": None, "version": 1,
    })
    log_event(mid, client, "created", "seed")

db.invoices.insert_many([
    {"_id": "inv_a_001", "client_id": "client_a", "vendor": "Bright Smile Supplies",
     "amount": 7200.00, "due": D(2026, 11, 30), "status": "new"},   # hero: 5k rule -> escalate
    {"_id": "inv_a_002", "client_id": "client_a", "vendor": "Pearl Dental Lab",
     "amount": 1150.00, "due": D(2026, 11, 28), "status": "new"},   # duplicate fact -> hold
    {"_id": "inv_a_003", "client_id": "client_a", "vendor": "Bright Smile Supplies",
     "amount": 800.00, "due": D(2026, 12, 5), "status": "new"},     # plain approve
    {"_id": "inv_b_001", "client_id": "client_b", "vendor": "Golden Mill Flour",
     "amount": 2400.00, "due": D(2026, 11, 25), "status": "new"},   # flour rule -> escalate owner
    {"_id": "inv_b_002", "client_id": "client_b", "vendor": "Daily Dairy",
     "amount": 600.00, "due": D(2026, 11, 22), "status": "new"},    # known supplier -> approve
    {"_id": "inv_b_003", "client_id": "client_b", "vendor": "Northern Packaging Co",
     "amount": 3100.00, "due": D(2026, 12, 1), "status": "new"},    # unknown vendor -> hold
])

print("seeded:", db.memories.count_documents({}), "memories,",
      db.invoices.count_documents({}), "invoices")
print("vector index:", [(i["name"], i["status"]) for i in db.memories.list_search_indexes()])

