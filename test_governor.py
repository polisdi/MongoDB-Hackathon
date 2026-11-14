import datetime as dt
from common import now, set_now, DEFAULT_NOW
from governor import MemoryGovernor

g = MemoryGovernor()
q = "approval rule for an invoice over $5,000"

set_now(DEFAULT_NOW)
a = g.recall("client_a", q, log=False)
b = g.recall("client_b", q, log=False)
print("A:", [(m["_id"], round(m["score"], 3)) for m in a])
print("B:", [(m["_id"], round(m["score"], 3)) for m in b])
assert all(m["client_id"] == "client_a" for m in a), "LEAK into A"
assert all(m["client_id"] == "client_b" for m in b), "LEAK into B"
assert a and a[0]["_id"] == "mem_a_rule_5k", "A's 5k rule should rank first"
assert "mem_b_rule_5k" not in [m["_id"] for m in a]
print("OK isolation")

no5k = g.recall("client_a", q, exclude_ids=["mem_a_rule_5k"], log=False)
assert "mem_a_rule_5k" not in [m["_id"] for m in no5k]
print("OK exclusion")

set_now(DEFAULT_NOW + dt.timedelta(days=200))
later = g.recall("client_a", q, log=False)
print("A after 200 days:", [m["_id"] for m in later])
assert "mem_a_rule_5k" not in [m["_id"] for m in later]
print("OK expiry")
set_now(DEFAULT_NOW)

