import json, hashlib, os, uuid
from typing import Literal, TypedDict
from pydantic import BaseModel, ValidationError
from langgraph.graph import StateGraph, END
from common import db, llm, now
from governor import MemoryGovernor

gov = MemoryGovernor()
MODEL = os.environ["LLM_MODEL"]

class Decision(BaseModel):
    action: Literal["approve", "escalate", "hold"]
    target_person: str          # role key like "office_manager", or "" if not escalating
    reason: str
    memory_ids_used: list[str]

class S(TypedDict, total=False):
    client_id: str; invoice_id: str; mode: str; exclude_ids: list[str]
    temperature: float; seed: int; run_id: str
    invoice: dict; client: dict; memories: list[dict]
    messages: list[dict]; raw: str; decision: dict; error: str; attempts: int

SYSTEM = """You process vendor invoices for a bookkeeping firm.
Pick exactly one action:
- approve: pay as normal
- escalate: send to a named person for approval (set target_person to their role key)
- hold: park it because something is wrong or a check is needed
Default: approve, unless one of the client's memories says otherwise.
Only cite memory ids that you actually relied on. Reply with JSON only."""

def load_invoice(s: S) -> S:
    inv = db.invoices.find_one({"_id": s["invoice_id"], "client_id": s["client_id"]})
    if not inv:
        raise ValueError("invoice not found in this client's scope")
    return {"invoice": inv, "client": db.clients.find_one({"_id": s["client_id"]}),
            "attempts": 0, "run_id": s.get("run_id") or f"run_{uuid.uuid4().hex[:8]}"}

def recall(s: S) -> S:
    inv = s["invoice"]
    q = f"invoice from {inv['vendor']} for ${inv['amount']:,.2f}: approval rules, vendor issues"
    mems = gov.recall(s["client_id"], q, k=5, exclude_ids=s.get("exclude_ids"),
                      run_id=s["run_id"], log=s.get("mode", "normal") == "normal")
    return {"memories": mems}

def decide(s: S) -> S:
    inv, client = s["invoice"], s["client"]
    mem_lines = "\n".join(f"- [{m['_id']}] ({m['kind']}) {m['text']}" for m in s["memories"]) or "- none"
    user = (f"Client: {client['name']}\nPeople (role key: name): {json.dumps(client['people'])}\n"
            f"Invoice: vendor={inv['vendor']}, amount=${inv['amount']:,.2f}, due={inv['due']:%Y-%m-%d}\n"
            f"Today: {now():%Y-%m-%d}\nClient memories:\n{mem_lines}")
    if s.get("error"):
        user += f"\n\nYour previous answer was invalid: {s['error']}. Fix it."
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    r = llm.chat.completions.create(
        model=MODEL, messages=messages,
        temperature=s.get("temperature", 0), seed=s.get("seed", 7),
        response_format={"type": "json_schema", "json_schema": {
            "name": "decision", "strict": True, "schema": Decision.model_json_schema()}})
    return {"messages": messages, "raw": r.choices[0].message.content,
            "attempts": s["attempts"] + 1}

def validate(s: S) -> S:
    try:
        d = Decision.model_validate_json(s["raw"])
    except ValidationError as e:
        return {"error": f"bad JSON: {e.errors()[0]['msg']}"}
    if d.action == "escalate" and d.target_person not in s["client"]["people"]:
        return {"error": f"target_person must be one of {list(s['client']['people'])}"}
    retrieved = {m["_id"] for m in s["memories"]}
    d.memory_ids_used = [m for m in d.memory_ids_used if m in retrieved]  # drop invented ids
    if d.action != "escalate":
        d.target_person = ""
    return {"decision": d.model_dump(), "error": ""}

def route(s: S) -> str:
    if not s.get("error"):
        return "act"
    return "decide" if s["attempts"] < 2 else "fallback"

def fallback(s: S) -> S:
    return {"decision": {"action": "hold", "target_person": "",
                         "reason": f"model output invalid twice: {s['error']}",
                         "memory_ids_used": []}}

def act(s: S) -> S:
    if s.get("mode", "normal") != "normal":
        return {}   # ablation runs never touch the mock systems
    d, inv = s["decision"], s["invoice"]
    if d["action"] == "approve":
        db.ledger.insert_one({"invoice_id": inv["_id"], "client_id": inv["client_id"],
                              "amount": inv["amount"], "at": now(), "run_id": s["run_id"]})
    elif d["action"] == "escalate":
        db.approvals.insert_one({"invoice_id": inv["_id"], "client_id": inv["client_id"],
                                 "to": d["target_person"], "reason": d["reason"],
                                 "at": now(), "run_id": s["run_id"]})
    db.invoices.update_one({"_id": inv["_id"]}, {"$set": {"status": d["action"]}})
    return {}

def log_decision(s: S) -> S:
    d = s["decision"]
    db.decisions.insert_one({
        "run_id": s["run_id"], "client_id": s["client_id"], "invoice_id": s["invoice_id"],
        "mode": s.get("mode", "normal"), "excluded_memory_ids": s.get("exclude_ids", []),
        "retrieved_memory_ids": [m["_id"] for m in s["memories"]],
        "used_memory_ids": d["memory_ids_used"], "action": d["action"],
        "target_person": d["target_person"], "reason": d["reason"],
        "model": MODEL, "temperature": s.get("temperature", 0), "seed": s.get("seed", 7),
        "prompt_hash": "sha256:" + hashlib.sha256(
            json.dumps(s.get("messages", []), sort_keys=True).encode()).hexdigest()[:16],
        "at": now()})
    return {}

g = StateGraph(S)
for name, fn in [("load_invoice", load_invoice), ("recall", recall), ("decide", decide),
                 ("validate", validate), ("fallback", fallback), ("act", act),
                 ("log_decision", log_decision)]:
    g.add_node(name, fn)
g.set_entry_point("load_invoice")
g.add_edge("load_invoice", "recall")
g.add_edge("recall", "decide")
g.add_edge("decide", "validate")
g.add_conditional_edges("validate", route, {"act": "act", "decide": "decide", "fallback": "fallback"})
g.add_edge("fallback", "act")
g.add_edge("act", "log_decision")
g.add_edge("log_decision", END)
graph = g.compile()

def run_invoice(client_id, invoice_id, mode="normal", exclude_ids=None, temperature=0.0, seed=7):
    out = graph.invoke({"client_id": client_id, "invoice_id": invoice_id, "mode": mode,
                        "exclude_ids": exclude_ids or [], "temperature": temperature, "seed": seed})
    return out["decision"]

if __name__ == "__main__":
    for cid, iid in [("client_a", "inv_a_001"), ("client_a", "inv_a_002"), ("client_a", "inv_a_003"),
                     ("client_b", "inv_b_001"), ("client_b", "inv_b_002"), ("client_b", "inv_b_003")]:
        d = run_invoice(cid, iid)
        print(f"{iid}: {d['action']:9} -> {d['target_person'] or '-':15} "
              f"used={d['memory_ids_used']}  | {d['reason'][:70]}")
