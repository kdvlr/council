from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .attachments import extract_attachment_text
from .db import (
    create_preset,
    create_session_and_run,
    delete_preset,
    delete_session,
    get_run_detail,
    get_session_detail,
    init_db,
    list_presets,
    list_sessions,
    rename_session,
)
from .job_manager import job_manager
from .litellm_client import litellm_client
from .mode1_engine import execute_mode1_run
from .mode2_engine import execute_mode2_run
from .models import CreateRunRequest, PresetCreateRequest, RenameSessionRequest


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Council API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/models")
async def get_models():
    try:
        models = await litellm_client.fetch_models()
        return {"models": [m.model_dump() for m in models]}
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to query LiteLLM models: {exc}"
        ) from exc


@app.post("/api/attachments/extract")
async def upload_attachment(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        parsed = extract_attachment_text(
            filename=file.filename or "attachment.txt",
            mime_type=file.content_type or "text/plain",
            raw_bytes=raw,
        )
        return parsed.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/presets")
async def api_list_presets():
    return {"presets": await list_presets()}


@app.post("/api/presets")
async def api_create_preset(req: PresetCreateRequest):
    deduped = list(dict.fromkeys(m.strip() for m in req.models if m.strip()))
    max_allowed = 5 if req.mode == "council" else 3
    if len(deduped) < 2 or len(deduped) > max_allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Mode '{req.mode}' requires between 2 and {max_allowed} distinct models.",
        )
    preset = await create_preset(
        name=req.name,
        mode=req.mode,
        models=deduped,
        chairman_model=req.chairman_model,
        shared_constraints=req.shared_constraints,
    )
    return preset


@app.delete("/api/presets/{preset_id}")
async def api_delete_preset(preset_id: str):
    ok = await delete_preset(preset_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Preset not found")
    return {"deleted": True}


@app.get("/api/sessions")
async def api_list_sessions(search: Optional[str] = Query(default=None)):
    return {"sessions": await list_sessions(search=search)}


@app.get("/api/sessions/{session_id}")
async def api_get_session(session_id: str):
    detail = await get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Session not found")
    return detail


@app.patch("/api/sessions/{session_id}")
async def api_rename_session(session_id: str, req: RenameSessionRequest):
    ok = await rename_session(session_id, req.title)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"updated": True}


@app.delete("/api/sessions/{session_id}")
async def api_delete_session(session_id: str):
    ok = await delete_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": True}


@app.post("/api/runs")
async def api_create_run(req: CreateRunRequest):
    deduped_models = list(dict.fromkeys(m.strip() for m in req.models if m.strip()))
    max_models = 5 if req.mode == "council" else 3
    if len(deduped_models) < 2 or len(deduped_models) > max_models:
        raise HTTPException(
            status_code=400,
            detail=f"Mode '{req.mode}' requires 2 to {max_models} distinct models.",
        )

    attachments_dicts = [a.model_dump() for a in req.attachments]

    try:
        session_id, run_id, run_index = await create_session_and_run(
            session_id=req.session_id,
            mode=req.mode,
            prompt=req.prompt.strip(),
            models=deduped_models,
            chairman_spec=req.chairman_model if req.mode == "council" else None,
            shared_constraints=req.shared_constraints,
            attachments=attachments_dicts,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if req.mode == "council":
        job_manager.start_job(
            run_id,
            lambda stream: execute_mode1_run(
                stream=stream,
                session_id=session_id,
                run_id=run_id,
                run_index=run_index,
                prompt=req.prompt.strip(),
                models=deduped_models,
                chairman_spec=req.chairman_model,
                shared_constraints=req.shared_constraints,
                attachments=attachments_dicts,
            ),
        )
    else:
        job_manager.start_job(
            run_id,
            lambda stream: execute_mode2_run(
                stream=stream,
                session_id=session_id,
                run_id=run_id,
                run_index=run_index,
                prompt=req.prompt.strip(),
                models=deduped_models,
                shared_constraints=req.shared_constraints,
                attachments=attachments_dicts,
            ),
        )

    return {
        "session_id": session_id,
        "run_id": run_id,
        "run_index": run_index,
    }


@app.get("/api/runs/{run_id}")
async def api_get_run(run_id: str):
    detail = await get_run_detail(run_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Run not found")
    return detail


@app.get("/api/runs/{run_id}/stream")
async def api_stream_run(run_id: str):
    return StreamingResponse(
        job_manager.subscribe_sse(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/runs/{run_id}/cancel")
async def api_cancel_run(run_id: str):
    cancelled = job_manager.cancel_job(run_id)
    return {"cancelled": cancelled}


# Serve built React SPA if present
_static_dir = Path(__file__).resolve().parent.parent / "static"
if not _static_dir.exists():
    _static_dir = Path(__file__).resolve().parent / "static"

if _static_dir.exists() and (_static_dir / "index.html").exists():
    assets_dir = _static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        candidate = (_static_dir / full_path).resolve()
        if (
            full_path
            and str(candidate).startswith(str(_static_dir.resolve()))
            and candidate.is_file()
        ):
            return FileResponse(str(candidate))
        return FileResponse(str(_static_dir / "index.html"))
