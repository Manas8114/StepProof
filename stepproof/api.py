from __future__ import annotations
import shutil, uuid
from pathlib import Path
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import config as cfg, store
from .compiler import compile_procedure
from .pipeline import run_inspection
from .providers import get_providers
from .schemas import ProcedureSpec

app = FastAPI(title="StepProof")
store.init()
seg, vis = get_providers()
STATIC = Path(__file__).parent / "static"


class CompileIn(BaseModel):
    text: str


class ReviewIn(BaseModel):
    step_id: str
    verdict: str  # pass | fail
    note: str = ""


@app.get("/api/health")
def health():
    return {"mode": cfg.PROVIDER_MODE, "cache": cfg.USE_CACHE, "segmentation": seg.name, "reasoning": vis.name}


@app.post("/api/procedures/compile")
def compile_(body: CompileIn):
    try:
        spec, warnings = compile_procedure(body.text, vis)
    except Exception as e:
        raise HTTPException(502, f"Could not compile procedure: {type(e).__name__}: {e}")
    return {"spec": spec, "warnings": warnings}


@app.post("/api/procedures")
def save_procedure(spec: ProcedureSpec):
    return {"id": store.save_procedure(spec)}


@app.get("/api/procedures")
def list_procedures():
    return store.list_procedures()


def _run(iid: str, dest: Path, spec: ProcedureSpec) -> None:
    try:
        store.set_status(iid, "running", "Starting")
        report = run_inspection(dest, spec, seg, vis, iid, on_progress=lambda m: store.set_status(iid, "running", m))
        store.save_report(iid, report)
    except Exception as e:  # surface the real reason to the UI
        store.set_status(iid, "error", f"{type(e).__name__}: {e}")


@app.post("/api/inspections")
def create_inspection(background: BackgroundTasks, procedure_id: str = Form(...), file: UploadFile = File(...)):
    spec = store.get_procedure(procedure_id)
    if spec is None:
        raise HTTPException(404, "Unknown procedure")
    iid = uuid.uuid4().hex[:10]
    dest = cfg.UPLOADS / f"{iid}{Path(file.filename or 'clip.mp4').suffix.lower() or '.mp4'}"
    with open(dest, "wb") as out:
        shutil.copyfileobj(file.file, out)
    store.create_inspection(iid, procedure_id, dest.name)
    background.add_task(_run, iid, dest, spec)
    return {"id": iid}


@app.get("/api/inspections/{iid}")
def get_inspection(iid: str):
    ins = store.get_inspection(iid)
    if ins is None:
        raise HTTPException(404, "Unknown inspection")
    return ins


@app.post("/api/inspections/{iid}/review")
def review(iid: str, body: ReviewIn):
    if body.verdict not in ("pass", "fail"):
        raise HTTPException(422, "verdict must be pass or fail")
    if not store.add_review(iid, body.model_dump()):
        raise HTTPException(404, "No finished report for this inspection")
    return {"ok": True}


app.mount("/media", StaticFiles(directory=cfg.UPLOADS), name="media")
app.mount("/evidence", StaticFiles(directory=cfg.EVIDENCE), name="evidence")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
