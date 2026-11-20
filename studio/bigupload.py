"""Large video upload (2 hours, many GB): streamed straight to disk in chunks, never held in RAM.

Streamlit's own file_uploader keeps the whole file in memory (a 4 GB video = 4+ GB of RAM). Here the browser
sends the file in 16 MB chunks and each chunk is written to disk immediately. If the connection drops, the
upload resumes where it stopped. These routes are mounted in server.py (st.App).

  GET  /api/bigupload/{token}/status          -> {"offset": bytes received so far}
  PUT  /api/bigupload/{token}?offset=N        -> one chunk (body); wrong offset returns 409 + the right offset
  POST /api/bigupload/{token}/done            -> {"name", "size"}: file complete, move it into INPUT_DIR

The token is a random per-browser-session id (created by app.py), so nobody can reach another user's file."""
import hashlib
import json
import os
import re
import time
from pathlib import Path

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from studio.config import INPUT_DIR

UPLOAD_DIR = INPUT_DIR / "_uploads"
MAX_BYTES = 20 * 1024 ** 3                 # 20 GB: comfortably fits a 2-hour 1080p video
ALLOWED = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".3gp"}
TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
STALE_HOURS = 24                           # unfinished uploads are cleaned up after this many hours


def _part(token: str) -> Path:
    return UPLOAD_DIR / f"{token}.part"


def _done(token: str) -> Path:
    return UPLOAD_DIR / f"{token}.json"


def result(token: str) -> dict | None:
    """If the upload is complete: {'file': name in INPUT_DIR, 'name': original name, 'size': bytes}."""
    try:
        return json.loads(_done(token).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def forget(token: str) -> None:
    for p in (_part(token), _done(token)):
        p.unlink(missing_ok=True)


def _bad(msg: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=code)


def _token(request: Request) -> str | None:
    token = request.path_params.get("token", "")
    return token if TOKEN.match(token) else None


def _clean_stale() -> None:
    cutoff = time.time() - STALE_HOURS * 3600
    for p in UPLOAD_DIR.glob("*.part"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


def _fingerprint(path: Path) -> str:
    """Fast fingerprint: size + first and last 8 MB. Re-uploading the same video reuses its transcript."""
    h = hashlib.sha1(str(path.stat().st_size).encode())
    with open(path, "rb") as f:
        h.update(f.read(8 * 1_048_576))
        f.seek(max(0, path.stat().st_size - 8 * 1_048_576))
        h.update(f.read())
    return h.hexdigest()[:16]


async def _status(request: Request) -> JSONResponse:
    token = _token(request)
    if not token:
        return _bad("bad token")
    part = _part(token)
    return JSONResponse({"offset": part.stat().st_size if part.exists() else 0, "done": result(token) is not None})


async def _put(request: Request) -> JSONResponse:
    token = _token(request)
    if not token:
        return _bad("bad token")
    try:
        offset = int(request.query_params.get("offset", "-1"))
    except ValueError:
        return _bad("bad offset")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    part = _part(token)
    current = part.stat().st_size if part.exists() else 0
    if offset != current:                     # resume: tell the browser where to continue from
        return JSONResponse({"offset": current}, status_code=409)
    if current == 0:
        await run_in_threadpool(_clean_stale)
    written = 0
    f = await run_in_threadpool(open, part, "ab")
    try:
        async for chunk in request.stream():
            written += len(chunk)
            if current + written > MAX_BYTES:
                return _bad(f"file is larger than {MAX_BYTES // 1024 ** 3} GB", 413)
            await run_in_threadpool(f.write, chunk)
    finally:
        await run_in_threadpool(f.close)
    return JSONResponse({"offset": current + written})


async def _finish(request: Request) -> JSONResponse:
    token = _token(request)
    if not token:
        return _bad("bad token")
    try:
        info = await request.json()
        name, size = str(info["name"])[:200], int(info["size"])
    except (ValueError, KeyError, TypeError):
        return _bad("bad request")
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED:
        return _bad(f"unsupported file type {ext or '(none)'}")
    part = _part(token)
    if not part.exists() or part.stat().st_size != size:
        return _bad("upload incomplete", 409)

    def place() -> str:
        target = INPUT_DIR / f"up_{_fingerprint(part)}{ext}"
        if target.exists() and target.stat().st_size == size:
            part.unlink()                     # same video uploaded before: reuse it (and its transcript)
        else:
            os.replace(part, target)
        return target.name

    file = await run_in_threadpool(place)
    _done(token).write_text(json.dumps({"file": file, "name": name, "size": size}), encoding="utf-8")
    return JSONResponse({"ok": True})


def routes() -> list[Route]:
    return [
        Route("/api/bigupload/{token}/status", _status, methods=["GET"]),
        Route("/api/bigupload/{token}/done", _finish, methods=["POST"]),
        Route("/api/bigupload/{token}", _put, methods=["PUT"]),
    ]
