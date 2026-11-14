import subprocess, sys, datetime as dt
from fastapi import FastAPI
from fastapi.responses import FileResponse
from bson import ObjectId
from pymongo.errors import WriteError
from common import db, now, set_now, DEFAULT_NOW
from governor import MemoryGovernor
from agent import graph
from ablation import ablate

app = FastAPI(title="Scoped Memory Agent")
gov = MemoryGovernor()
HERO = ("client_a", "inv_a_001")

def clean(x):
    if isinstance(x, ObjectId): return str(x)
    if isinstance(x, dt.datetime): return x.isoformat()
    if isinstance(x, dict): return {k: clean(v) for k, v in x.items() if k != "embedding"}
    if isinstance(x, list): return [clean(v) for v in x]
    return x

def run(client_id, invoice_id):
    out = graph.invoke({"client_id": client_id, "invoice_id": invoice_id, "mode": "normal",
                        "exclude_ids": [], "temperature": 0.0, "seed": 7})
    inv = out["invoice"]
    d = dict(out["decision"])
    d["target_name"] = out["client"]["people"].get(d["target_person"], "")
    return {"run_id": out["run_id"],
            "invoice": {"id": inv["_id"], "client": out["client"]["name"],
                        "vendor": inv["vendor"], "amount": inv["amount"]},
            "decision":  d,
            "retrieved": [{"id": m["_id"], "text": m["text"], "score": round(m["score"], 3)}
                          for m in out["memories"]],
            "now": now()}

@app.get("/")
def index():
    return FileResponse("static/index.html")

@app.post("/reset")
def reset():
    subprocess.run([sys.executable, "seed.py"], check=True, capture_output=True)
    return clean({"ok": True, "now": now()})

@app.post("/run")
def run_one(client_id: str = HERO[0], invoice_id: str = HERO[1]):
    return clean(run(client_id, invoice_id))

@app.post("/ablate")
def ablate_live(n: int = 3):
    exp = ablate(*HERO, "mem_a_rule_5k", n=n, label="5K rule on $7,200 invoice")
    ctl = ablate(*HERO, "mem_a_pref_pay_due", n=n, label="CONTROL: pay-on-due preference")
    return clean({"experiment": exp, "control": ctl})

@app.get("/ablation/latest")
def ablation_latest():
    rows = list(db.ablation_runs.find({}, {"_id": 0}).sort("_id", -1).limit(2))
    return clean({"experiment": next((r for r in rows if not r["label"].startswith("CONTROL")), None),
                  "control": next((r for r in rows if r["label"].startswith("CONTROL")), None)})

@app.post("/isolation")
def isolation():
    q = "Lakeview Dental Clinic: approval rules for invoices over $5,000"
    seen_by_b = gov.recall("client_b", q, log=False)
    try:
        db.memories.insert_one({"kind": "rule", "status": "active", "text": "unscoped memory",
                                "source": {"type": "agent_inferred"},
                                "created_at": now(), "expires_at": now()})
        schema = "FAIL: unscoped memory was accepted"
    except WriteError as e:
        schema = f"Rejected by Atlas: {e.details.get('errmsg')}"
    return clean({"query_as_client_b": q,
                  "results": [{"id": m["_id"], "client_id": m["client_id"], "text": m["text"]}
                              for m in seen_by_b],
                  "schema_check": schema})

@app.post("/correct")
def correct(limit: int = 10000):
    set_now(DEFAULT_NOW)
    cur = db.memories.find_one({"_id": {"$regex": "^mem_a_rule_5k"}, "status": "active"})
    new_id = gov.correct(cur["_id"], f"Never auto-approve invoices over ${limit:,}. "
                         "Escalate them to the office manager for approval.", by="owner")
    versions = list(db.memories.find({"_id": {"$regex": "^mem_a_rule_5k"}},
                                     {"embedding": 0}).sort("version", 1))
    return clean({"new_id": new_id, "versions": versions, "rerun": run(*HERO)})

@app.post("/clock")
def clock(days: int = 200):
    set_now(DEFAULT_NOW)
    before = run(*HERO)
    set_now(DEFAULT_NOW + dt.timedelta(days=days))
    return clean({"now": now(), "before": before, "rerun": run(*HERO)})


@app.post("/forget")
def forget(memory_id: str = "mem_a_fact_pearl_dup"):
    set_now(DEFAULT_NOW)                                  # undo the +200 day jump from beat 4
    before = run("client_a", "inv_a_002")
    gov.forget(memory_id, by="owner", reason="client asked to remove vendor dispute note")
    return clean({"before": before,
                  "tombstone": db.memories.find_one({"_id": memory_id}),
                  "history": gov.history(memory_id),
                  "rerun": run("client_a", "inv_a_002")})


@app.get("/memories")
def memories(client_id: str):
    return clean(list(db.memories.find({"client_id": client_id}, {"embedding": 0})
                      .sort([("status", 1), ("_id", 1)])))

