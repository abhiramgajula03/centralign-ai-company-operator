"""CentrAlign AI: bounded invoice follow-up operator, using only Python's stdlib."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("CENTRALIGN_DB", ROOT / "centrAlign.sqlite3"))
TODAY = date.today()
FAIL_NEXT_SAVE = False
FAIL_LOCK = threading.Lock()

SEED = [
    ("INV-1042", "Northstar Office Supply", 1840.00, -19, "unpaid", "ap@northstar.example"),
    ("INV-1043", "Aster Cloud Services", 9200.00, -7, "unpaid", "billing@aster.example"),
    ("INV-1044", "Juniper Freight", 3675.50, -34, "unpaid", "finance@juniper.example"),
    ("INV-1045", "Mosaic Design Studio", 1260.00, 9, "unpaid", "accounts@mosaic.example"),
    ("INV-1046", "Pinecone Security", 5150.00, -12, "paid", "ar@pinecone.example"),
    ("INV-1047", "Redwood Catering", 780.00, -3, "unpaid", "payables@redwood.example"),
    ("INV-1048", "Bluebird Analytics", 6420.00, -26, "unpaid", "finance@bluebird.example"),
]

@contextmanager
def connect():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def init_db() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS invoices(id TEXT PRIMARY KEY, vendor TEXT NOT NULL, amount REAL NOT NULL,
          due_date TEXT NOT NULL, status TEXT NOT NULL, email TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, request TEXT NOT NULL, status TEXT NOT NULL,
          mode TEXT NOT NULL, created_at TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
          invoice_id TEXT NOT NULL REFERENCES invoices(id), recipient TEXT NOT NULL, subject TEXT NOT NULL,
          body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', UNIQUE(task_id, invoice_id));
        CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, draft_id TEXT NOT NULL UNIQUE REFERENCES drafts(id),
          recipient TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
          at TEXT NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS task_invoices(task_id TEXT NOT NULL REFERENCES tasks(id), invoice_id TEXT NOT NULL,
          overdue_days INTEGER NOT NULL, priority TEXT NOT NULL, PRIMARY KEY(task_id, invoice_id));
        """)
        if db.execute("SELECT count(*) FROM invoices").fetchone()[0] == 0:
            for iid, vendor, amount, due_delta, status, email in SEED:
                db.execute("INSERT INTO invoices VALUES(?,?,?,?,?,?)", (iid, vendor, amount,
                    (TODAY.replace(day=1) if False else date.fromordinal(TODAY.toordinal()+due_delta)).isoformat(), status, email))

def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def event(db: sqlite3.Connection, task_id: str, kind: str, message: str, data: Any = None) -> None:
    db.execute("INSERT INTO events(task_id,at,kind,message,data) VALUES(?,?,?,?,?)",
               (task_id, now(), kind, message, json.dumps(data or {})))

def invoice_analysis() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("SELECT * FROM invoices ORDER BY id").fetchall()
    result = []
    for r in rows:
        days = (TODAY - date.fromisoformat(r["due_date"])).days
        result.append({**dict(r), "overdue_days": max(0, days), "outstanding": round(r["amount"], 2) if r["status"] != "paid" else 0.0})
    return result

def tool_list_invoices() -> list[dict[str, Any]]:
    return invoice_analysis()

def tool_save_draft(task_id: str, invoice: dict[str, Any]) -> dict[str, Any]:
    global FAIL_NEXT_SAVE
    with FAIL_LOCK:
        if FAIL_NEXT_SAVE:
            FAIL_NEXT_SAVE = False
            raise RuntimeError("Injected transient database write failure")
    draft_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{task_id}:{invoice['id']}"))
    body = (f"Hello {invoice['vendor']} team,\n\nOur records show invoice {invoice['id']} for "
            f"${invoice['amount']:,.2f} is {invoice['overdue_days']} days overdue. Could you share an "
            "expected payment date or let us know if you need anything from us?\n\nThank you,\nAccounts Payable")
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO drafts(id,task_id,invoice_id,recipient,subject,body) VALUES(?,?,?,?,?,?)",
          (draft_id, task_id, invoice["id"], invoice["email"], f"Payment follow-up: {invoice['id']}", body))
        row = db.execute("SELECT * FROM drafts WHERE task_id=? AND invoice_id=?", (task_id, invoice["id"])).fetchone()
    return dict(row)

TOOLS: dict[str, Callable[..., Any]] = {"invoice.list": tool_list_invoices, "reminder.save_draft": tool_save_draft}

def make_plan(request: str) -> list[dict[str, str]]:
    # Narrow deterministic intent parser; never converts user text into executable actions.
    if not any(w in request.lower() for w in ("invoice", "overdue", "follow-up", "reminder", "payment")):
        raise ValueError("This prototype supports invoice follow-up requests. Try mentioning overdue invoices or reminders.")
    return [
      {"step":"understand", "description":"Interpret the goal as preparing follow-up reminders for overdue, unpaid invoices."},
      {"step":"read_invoices", "tool":"invoice.list", "description":"Read invoice records and calculate overdue days and outstanding amounts."},
      {"step":"prioritize", "description":"Exclude paid and not-yet-due records; rank by overdue age, then amount."},
      {"step":"draft_reminders", "tool":"reminder.save_draft", "description":"Create personalized, persisted drafts. Sending is approval-gated."},
      {"step":"approval", "description":"Wait for a human to approve or reject each simulated send."},
      {"step":"verify", "description":"Re-read persisted drafts, decisions, and outbox rows independently."},
    ]

def run_task(request: str) -> dict[str, Any]:
    task_id = str(uuid.uuid4())
    plan = make_plan(request)
    with connect() as db:
        db.execute("INSERT INTO tasks(id,request,status,mode,created_at) VALUES(?,?,?,?,?)", (task_id, request, "running", "deterministic", now()))
        event(db, task_id, "goal", "Goal understood: prepare reminders for eligible overdue invoices.")
        event(db, task_id, "plan", "Created a bounded invoice follow-up plan.", plan)
    invoices = TOOLS["invoice.list"]()
    with connect() as db:
        event(db, task_id, "tool", f"invoice.list returned {len(invoices)} invoice records.", {"tool":"invoice.list", "count":len(invoices)})
    eligible = [i for i in invoices if i["status"] != "paid" and i["overdue_days"] > 0]
    eligible.sort(key=lambda i: (-i["overdue_days"], -i["outstanding"]))
    for idx, inv in enumerate(eligible):
        inv["priority"] = "high" if inv["overdue_days"] >= 21 or inv["outstanding"] >= 6000 else "normal"
        with connect() as db:
            db.execute("INSERT OR IGNORE INTO task_invoices VALUES(?,?,?,?)", (task_id, inv["id"], inv["overdue_days"], inv["priority"]))
            event(db, task_id, "analysis", f"Prioritized {inv['id']} ({inv['overdue_days']} days overdue, ${inv['outstanding']:,.2f}, {inv['priority']}).")
        for attempt in range(1, 3):
            try:
                draft = TOOLS["reminder.save_draft"](task_id, inv)
                with connect() as db:
                    event(db, task_id, "tool", f"reminder.save_draft persisted {inv['id']}.", {"tool":"reminder.save_draft", "invoice_id":inv["id"], "attempt":attempt, "draft_id":draft["id"]})
                break
            except Exception as e:
                with connect() as db:
                    event(db, task_id, "retry", f"Draft save attempt {attempt} failed for {inv['id']}: {e}", {"attempt":attempt, "invoice_id":inv["id"]})
                if attempt == 2:
                    with connect() as db:
                        event(db, task_id, "failed", f"Draft save exhausted retries for {inv['id']}.", {"attempt":attempt, "invoice_id":inv["id"]})
    with connect() as db:
        failed = db.execute("SELECT count(*) FROM events WHERE task_id=? AND kind='failed'", (task_id,)).fetchone()[0]
        status = "failed" if failed else "awaiting_approval"
        db.execute("UPDATE tasks SET status=?,summary=? WHERE id=?", (status, "Reminder drafts prepared; review each before simulated sending.", task_id))
        event(db, task_id, "approval_required", "No messages are sent until individually approved.")
    return get_task(task_id)

def get_task(task_id: str) -> dict[str, Any]:
    with connect() as db:
        t = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not t: raise KeyError(task_id)
        drafts = [dict(r) for r in db.execute("SELECT d.*,i.vendor,i.amount,ti.overdue_days,ti.priority FROM drafts d JOIN invoices i ON i.id=d.invoice_id JOIN task_invoices ti ON ti.task_id=d.task_id AND ti.invoice_id=d.invoice_id WHERE d.task_id=? ORDER BY ti.overdue_days DESC, d.invoice_id", (task_id,))]
        events = [dict(r) for r in db.execute("SELECT * FROM events WHERE task_id=? ORDER BY id", (task_id,))]
        outbox = [dict(r) for r in db.execute("SELECT o.*,d.invoice_id FROM outbox o JOIN drafts d ON d.id=o.draft_id WHERE d.task_id=?", (task_id,))]
    for e in events: e["data"] = json.loads(e["data"])
    with connect() as db:
        source = [dict(r) for r in db.execute("SELECT id,status,due_date FROM invoices")]
    expected = {i["id"] for i in source if i["status"] != "paid" and (TODAY-date.fromisoformat(i["due_date"])).days > 0}
    actual = {d["invoice_id"] for d in drafts}
    approved_ids = {d["id"] for d in drafts if d["status"] == "approved"}
    outbox_draft_ids = {o["draft_id"] for o in outbox}
    verified = {"draft_count":len(drafts), "expected_eligible_count":len(expected), "eligible_match":actual == expected,
      "pending":sum(d["status"]=="pending" for d in drafts), "approved":sum(d["status"]=="approved" for d in drafts),
      "rejected":sum(d["status"]=="rejected" for d in drafts), "outbox_count":len(outbox),
      "approved_outbox_match":approved_ids == outbox_draft_ids, "checked_at":now()}
    return {**dict(t), "plan":make_plan(t["request"]), "drafts":drafts, "events":events, "outbox":outbox, "verification":verified}

def decide(draft_id: str, action: str) -> dict[str, Any]:
    if action not in ("approve", "reject"): raise ValueError("Decision must be approve or reject")
    with connect() as db:
        draft = db.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
        if not draft: raise KeyError(draft_id)
        if draft["status"] != "pending": raise ValueError("This draft has already been decided")
        task_id = draft["task_id"]
        if action == "approve":
            db.execute("INSERT OR IGNORE INTO outbox(id,draft_id,recipient,subject,body,created_at) VALUES(?,?,?,?,?,?)", (str(uuid.uuid4()), draft_id, draft["recipient"], draft["subject"], draft["body"], now()))
            db.execute("UPDATE drafts SET status='approved' WHERE id=?", (draft_id,))
            event(db, task_id, "approved", f"Approved {draft['invoice_id']}; placed in simulated outbox.", {"draft_id":draft_id})
        else:
            db.execute("UPDATE drafts SET status='rejected' WHERE id=?", (draft_id,))
            event(db, task_id, "rejected", f"Rejected {draft['invoice_id']}; protected send operation not executed.", {"draft_id":draft_id})
        pending = db.execute("SELECT count(*) FROM drafts WHERE task_id=? AND status='pending'", (task_id,)).fetchone()[0]
        failed = db.execute("SELECT count(*) FROM events WHERE task_id=? AND kind='failed'", (task_id,)).fetchone()[0]
        status = "failed" if failed else ("awaiting_approval" if pending else "completed")
        db.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
    return get_task(task_id)

def state() -> dict[str, Any]:
    with connect() as db:
        invoices = [dict(r) for r in db.execute("SELECT * FROM invoices ORDER BY id")]
        tasks = [dict(r) for r in db.execute("SELECT * FROM tasks ORDER BY created_at DESC")]
        drafts = [dict(r) for r in db.execute("SELECT d.*,i.vendor,i.amount FROM drafts d JOIN invoices i ON i.id=d.invoice_id ORDER BY d.rowid DESC")]
        outbox = [dict(r) for r in db.execute("SELECT o.*,d.invoice_id FROM outbox o JOIN drafts d ON d.id=o.draft_id ORDER BY o.created_at DESC")]
    for i in invoices:
        i["overdue_days"] = max(0,(TODAY-date.fromisoformat(i["due_date"])).days)
        i["outstanding"] = i["amount"] if i["status"]!="paid" else 0
    return {"invoices":invoices,"tasks":tasks,"drafts":drafts,"outbox":outbox,"today":TODAY.isoformat(),"mode":"Deterministic local agent"}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None: print(f"[{self.log_date_time_string()}] {fmt % args}")
    def send_json(self, code: int, obj: Any) -> None:
        payload=json.dumps(obj,ensure_ascii=False).encode(); self.send_response(code); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(payload))); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers(); self.wfile.write(payload)
    def body(self) -> dict[str,Any]:
        n=int(self.headers.get("Content-Length","0")); return json.loads(self.rfile.read(n) or b"{}")
    def do_OPTIONS(self) -> None:
        self.send_response(204); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Access-Control-Allow-Headers","Content-Type"); self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS"); self.end_headers()
    def do_GET(self) -> None:
        path=urlparse(self.path).path
        try:
            if path=="/api/state": self.send_json(200,state())
            elif path.startswith("/api/tasks/"): self.send_json(200,get_task(path.rsplit("/",1)[1]))
            else:
                file="index.html" if path=="/" else path.lstrip("/")
                target=(ROOT/file).resolve()
                if ROOT not in target.parents and target!=ROOT: raise FileNotFoundError()
                if not target.is_file(): raise FileNotFoundError()
                raw=target.read_bytes()
                content_type={".html":"text/html; charset=utf-8", ".css":"text/css; charset=utf-8", ".js":"text/javascript; charset=utf-8"}.get(target.suffix.lower(), "application/octet-stream")
                self.send_response(200); self.send_header("Content-Type",content_type); self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw)
        except KeyError: self.send_json(404,{"error":"Not found"})
        except FileNotFoundError: self.send_json(404,{"error":"Not found"})
    def do_POST(self) -> None:
        global FAIL_NEXT_SAVE
        path=urlparse(self.path).path
        try:
            body=self.body()
            if path=="/api/tasks":
                req=str(body.get("request","")).strip()
                if not req: raise ValueError("Enter a task request")
                self.send_json(201,run_task(req))
            elif path=="/api/failure-injection":
                with FAIL_LOCK: FAIL_NEXT_SAVE=True
                self.send_json(200,{"armed":True,"message":"Next draft save will fail once; one automatic retry is allowed."})
            elif path.startswith("/api/drafts/") and path.endswith("/decision"):
                draft_id=path.split("/")[3]; result=decide(draft_id,body.get("decision","")); self.send_json(200,result)
            else: self.send_json(404,{"error":"Not found"})
        except KeyError: self.send_json(404,{"error":"Not found"})
        except (ValueError,json.JSONDecodeError) as e: self.send_json(400,{"error":str(e)})
        except Exception as e: self.send_json(500,{"error":str(e)})

if __name__ == "__main__":
    init_db()
    server=ThreadingHTTPServer(("127.0.0.1",8000),Handler)
    print(f"CentrAlign AI running at http://127.0.0.1:8000 (SQLite: {DB_PATH})")
    try: server.serve_forever()
    except KeyboardInterrupt: print("Stopping server")
