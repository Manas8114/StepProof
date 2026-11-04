from __future__ import annotations
import json, sqlite3, uuid
from . import config as cfg
from .schemas import ProcedureSpec, Report


def _c() -> sqlite3.Connection:
    c = sqlite3.connect(cfg.DATA_DIR / "stepproof.db")
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _c() as c:
        c.execute("CREATE TABLE IF NOT EXISTS procedures(id TEXT PRIMARY KEY, name TEXT, spec TEXT, created REAL DEFAULT (strftime('%s','now')))")
        c.execute("CREATE TABLE IF NOT EXISTS inspections(id TEXT PRIMARY KEY, procedure_id TEXT, video TEXT, status TEXT, detail TEXT, report TEXT, created REAL DEFAULT (strftime('%s','now')))")
        c.execute("CREATE TABLE IF NOT EXISTS audit_chain(seq INTEGER PRIMARY KEY, run_id TEXT, prev_hash TEXT, entry_hash TEXT, data TEXT, created REAL DEFAULT (strftime('%s','now')))")


def append_audit_entry(entry: dict) -> int:
    with _c() as c:
        row = c.execute("SELECT MAX(seq) as max_seq FROM audit_chain").fetchone()
        max_seq = row["max_seq"] if row and row["max_seq"] is not None else -1
        seq = max(entry.get("seq", 0), max_seq + 1)
        entry["seq"] = seq
        c.execute("INSERT INTO audit_chain(seq, run_id, prev_hash, entry_hash, data) VALUES(?,?,?,?,?)",
                  (seq, entry["run_id"], entry["prev_hash"], entry["entry_hash"], json.dumps(entry)))
        return seq


def get_audit_entries(run_id: str | None = None) -> list[dict]:
    with _c() as c:
        if run_id:
            rows = c.execute("SELECT data FROM audit_chain WHERE run_id=? ORDER BY seq ASC", (run_id,)).fetchall()
        else:
            rows = c.execute("SELECT data FROM audit_chain ORDER BY seq ASC").fetchall()
    return [json.loads(r["data"]) for r in rows]


def get_last_audit_entry() -> dict | None:
    with _c() as c:
        row = c.execute("SELECT data FROM audit_chain ORDER BY seq DESC LIMIT 1").fetchone()
    return json.loads(row["data"]) if row else None


def save_procedure(spec: ProcedureSpec) -> str:
    pid = uuid.uuid4().hex[:8]
    with _c() as c:
        c.execute("INSERT INTO procedures(id,name,spec) VALUES(?,?,?)", (pid, spec.name, spec.model_dump_json()))
    return pid


def get_procedure(pid: str) -> ProcedureSpec | None:
    with _c() as c:
        row = c.execute("SELECT spec FROM procedures WHERE id=?", (pid,)).fetchone()
    return ProcedureSpec.model_validate_json(row["spec"]) if row else None


def list_procedures() -> list[dict]:
    with _c() as c:
        return [dict(r) for r in c.execute("SELECT id,name FROM procedures ORDER BY created DESC")]


def create_inspection(iid: str, pid: str, video: str) -> None:
    with _c() as c:
        c.execute("INSERT INTO inspections(id,procedure_id,video,status,detail) VALUES(?,?,?,?,?)", (iid, pid, video, "queued", ""))


def set_status(iid: str, status: str, detail: str = "") -> None:
    with _c() as c:
        c.execute("UPDATE inspections SET status=?, detail=? WHERE id=?", (status, detail, iid))


def save_report(iid: str, report: Report) -> None:
    with _c() as c:
        c.execute("UPDATE inspections SET status='done', detail='', report=? WHERE id=?", (report.model_dump_json(), iid))


def get_inspection(iid: str) -> dict | None:
    with _c() as c:
        row = c.execute("SELECT id,procedure_id,video,status,detail,report FROM inspections WHERE id=?", (iid,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["report"] = json.loads(d["report"]) if d["report"] else None
    return d


def add_review(iid: str, review: dict) -> bool:
    ins = get_inspection(iid)
    if not ins or not ins["report"]:
        return False
    rep = ins["report"]
    rep["reviews"] = [r for r in rep.get("reviews", []) if r["step_id"] != review["step_id"]] + [review]
    with _c() as c:
        c.execute("UPDATE inspections SET report=? WHERE id=?", (json.dumps(rep), iid))
    return True
