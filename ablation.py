import sys
from collections import Counter
from common import db, now
from agent import run_invoice

def ablate(client_id, invoice_id, memory_id, n=5, temperature=0.5, label=""):
    """Same invoice, n runs with all memories vs n runs with one memory hidden.
    Ablation runs use mode='ablated' so they never touch the mock systems."""
    with_mem, without_mem = Counter(), Counter()
    for i in range(n):
        d = run_invoice(client_id, invoice_id, mode="ablated",
                        temperature=temperature, seed=100 + i)
        with_mem[d["action"]] += 1
        d = run_invoice(client_id, invoice_id, mode="ablated", exclude_ids=[memory_id],
                        temperature=temperature, seed=100 + i)
        without_mem[d["action"]] += 1
    top_with = with_mem.most_common(1)[0][0]
    top_without = without_mem.most_common(1)[0][0]

    target = top_with                                   # the action the memory drives
    rate_with = with_mem[target] / n
    rate_without = without_mem[target] / n

    result = {
        "client_id": client_id, "invoice_id": invoice_id, "memory_id": memory_id,
        "label": label, "n": n, "temperature": temperature,
        "actions_with": dict(with_mem), "actions_without": dict(without_mem),
        "consistent": with_mem[top_with] == n and without_mem[top_without] == n,
        "changed": top_with != top_without, "at": now(),
        "target_action": target,
        "rate_with": rate_with, "rate_without": rate_without,
        "effect": round(rate_with - rate_without, 2),
    }
    db.ablation_runs.insert_one(dict(result))
    return result

def show(r):
    t = r["target_action"]
    print(f"{r['label']}: '{t}' {r['rate_with']:.0%} with memory vs "
          f"{r['rate_without']:.0%} without  (effect {r['effect']:+.0%})  "
          f"with={r['actions_with']} without={r['actions_without']}")

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    # experiment: the memory that should matter
    show(ablate("client_a", "inv_a_001", "mem_a_rule_5k", n=n, label="5K rule on $7,200 invoice"))
    # control: a memory that should NOT matter for this decision
    show(ablate("client_a", "inv_a_001", "mem_a_pref_pay_due", n=n, label="CONTROL: pay-on-due pref"))

