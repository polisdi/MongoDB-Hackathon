import datetime as dt
from common import db, set_now, DEFAULT_NOW
from governor import MemoryGovernor
from agent import run_invoice

g = MemoryGovernor()
set_now(DEFAULT_NOW)

print("before:", run_invoice("client_a", "inv_a_001", mode="ablated")["action"])

new_id = g.correct("mem_a_rule_5k",
                   "Never auto-approve invoices over $10,000. Escalate them to the office manager for approval.",
                   by="owner")
old = db.memories.find_one({"_id": "mem_a_rule_5k"})
print("old status:", old["status"], "-> superseded_by", old["superseded_by"])
print("after correction:", run_invoice("client_a", "inv_a_001", mode="ablated")["action"])

set_now(DEFAULT_NOW + dt.timedelta(days=200))
print("after 200 days:", run_invoice("client_a", "inv_a_001", mode="ablated")["action"])
set_now(DEFAULT_NOW)

print("history:", [(e["event"], e["actor"]) for e in g.history("mem_a_rule_5k")])

