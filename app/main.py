from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "frontend"
TEMP_ROOT = Path(os.getenv("YTDLP_TEMP_DIR", "/tmp/ytdlp-web"))
TEMP_ROOT.mkdir(parents=True, exist_ok=True)
JOBS: dict[str, dict[str, Any]] = {}
ALLOWED_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com", "instagram.com", "instagr.am", "tiktok.com", "twitter.com", "x.com", "t.co")
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"

app = FastAPI(title="ytdlp-web", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class InspectRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if parsed.scheme not in {"http", "https"} or not host or not any(host == item or host.endswith("." + item) for item in ALLOWED_HOSTS):
            raise ValueError("Desteklenmeyen veya geçersiz URL")
        return value


class DownloadRequest(InspectRequest):
    kind: str = Field(pattern="^(audio|video|subtitle)$")
    format: str = Field(default="best", pattern="^(best|mp3|opus|flac|wav|mp4-1080|mp4-720|mp4-480|srt|vtt)$")
    start: str | None = Field(default=None, max_length=12)
    end: str | None = Field(default=None, max_length=12)
    subtitle_langs: str = Field(default="tr,en", max_length=30)

    @field_validator("start", "end")
    @classmethod
    def valid_time(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not re.fullmatch(r"(?:\d{1,2}:)?\d{1,2}:\d{2}", value):
            raise ValueError("Zaman biçimi SS, MM:SS veya HH:MM:SS olmalı")
        return value


def run_ytdlp(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["yt-dlp", *args], cwd=cwd, capture_output=True, text=True, timeout=1800, check=False)


def stream_ytdlp(args: list[str], cwd: Path, on_line: Any) -> tuple[int, str]:
    process = subprocess.Popen(["yt-dlp", *args], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    output: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        output.append(line)
        on_line(line)
    return process.wait(), "".join(output)


def seconds(value: str | None) -> float | None:
    if not value:
        return None
    parts = [float(p) for p in value.split(":")]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def progress_from_output(line: str) -> int | None:
    match = re.search(r"(\d+(?:\.\d+)?)%", line)
    return min(99, int(float(match.group(1)))) if match else None


def extractor_args(url: str) -> list[str]:
    host = (urlparse(url).hostname or "").lower()
    args = ["--user-agent", USER_AGENT, "--socket-timeout", "30", "--retries", "2", "--extractor-retries", "2"]
    if host.endswith(("twitter.com", "x.com")):
        args += ["--extractor-args", "twitter:api=syndication"]
    return args


def explain_extraction_error(output: str) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", output or "")
    lower = text.lower()
    if "unsupported url" in lower or "no suitable extractor" in lower:
        return "Bu URL biçimi desteklenmiyor. Gönderinin/video sayfasının tam bağlantısını deneyin."
    if "private" in lower or "login required" in lower or "sign in to confirm" in lower:
        return "Bu içerik herkese açık değil veya platform giriş istiyor. Yalnızca herkese açık içerikler desteklenir."
    if "captcha" in lower or "robot" in lower or "bot" in lower or "confirm you're not a bot" in lower:
        return "Kaynak platform geçici bot doğrulaması istiyor. Birkaç dakika sonra tekrar deneyin."
    if "http error 403" in lower or "forbidden" in lower or "blocked" in lower:
        return "Kaynak platform bu sunucunun isteğini geçici olarak reddetti. Daha sonra tekrar deneyin."
    if "country" in lower or "geo" in lower or "not available" in lower:
        return "Bu içerik sunucunun bulunduğu bölgede kullanılamıyor."
    meaningful = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("[debug]")]
    if meaningful:
        detail = meaningful[-1].replace("ERROR:", "").strip()
        if len(detail) > 180:
            detail = detail[:177] + "..."
        return f"Platform yanıtı: {detail}"
    return "Link çözümlenemedi. URL'nin herkese açık ve doğrudan medya sayfası olduğundan emin olun."


async def download_job(job_id: str, request: DownloadRequest) -> None:
    job = JOBS[job_id]
    folder = Path(job["folder"])
    try:
        args = ["--no-playlist", "--newline", "--no-warnings", "--restrict-filenames", *extractor_args(request.url)]
        start, end = seconds(request.start), seconds(request.end)
        if start is not None and end is not None and end > start:
            args += ["--download-sections", f"*{request.start}-{request.end}", "--force-keyframes-at-cuts"]
        if request.kind == "audio":
            if request.format == "best":
                args += ["-f", "bestaudio/best", "-o", "%(title)s.%(ext)s"]
            else:
                args += ["-x", "--audio-format", request.format, "--audio-quality", "0", "-o", "%(title)s.%(ext)s"]
        elif request.kind == "video":
            selector = {"best": "bestvideo*+bestaudio/best", "mp4-1080": "bestvideo[height<=1080]+bestaudio/best[height<=1080]", "mp4-720": "bestvideo[height<=720]+bestaudio/best[height<=720]", "mp4-480": "bestvideo[height<=480]+bestaudio/best[height<=480]"}[request.format]
            args += ["-f", selector, "--merge-output-format", "mp4", "-o", "%(title)s.%(ext)s"]
        else:
            args += ["--write-subs", "--sub-langs", request.subtitle_langs, "--sub-format", request.format, "--skip-download", "-o", "%(title)s.%(ext)s"]
        args.append(request.url)
        job["status"] = "downloading"
        def update_progress(line: str) -> None:
            value = progress_from_output(line)
            if value is not None:
                job["progress"] = value
                job["updated_at"] = time.time()

        returncode, output = await asyncio.to_thread(stream_ytdlp, args, folder, update_progress)
        if returncode != 0:
            raise RuntimeError(output[-500:] or "yt-dlp işlemi başarısız")
        files = [p for p in folder.iterdir() if p.is_file()]
        if not files:
            raise RuntimeError("İndirilebilir medya veya altyazı bulunamadı")
        job["file"] = str(files[0])
        job["filename"] = files[0].name
        job["mime"] = mimetypes.guess_type(files[0].name)[0] or "application/octet-stream"
        job["progress"] = 100
        job["status"] = "complete"
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)
    finally:
        job["updated_at"] = time.time()


def cleanup(job_id: str) -> None:
    job = JOBS.pop(job_id, None)
    if job:
        shutil.rmtree(job["folder"], ignore_errors=True)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/inspect")
async def inspect(request: InspectRequest) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as folder:
        result = await asyncio.to_thread(run_ytdlp, ["--dump-single-json", "--no-download", "--no-playlist", "--no-warnings", *extractor_args(request.url), request.url], Path(folder))
    if result.returncode != 0:
        raise HTTPException(422, explain_extraction_error(result.stderr or result.stdout))
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(502, "Kaynak platform geçerli metadata döndürmedi.") from exc
    return {"id": data.get("id"), "title": data.get("title") or "Bilinmeyen başlık", "thumbnail": data.get("thumbnail"), "duration": data.get("duration"), "duration_string": data.get("duration_string"), "uploader": data.get("uploader"), "webpage_url": data.get("webpage_url", request.url), "subtitles": sorted((data.get("subtitles") or {}).keys()), "automatic_captions": sorted((data.get("automatic_captions") or {}).keys())}


@app.post("/api/download")
async def download(request: DownloadRequest) -> dict[str, str]:
    job_id = uuid.uuid4().hex
    folder = Path(tempfile.mkdtemp(prefix=f"{job_id}-", dir=TEMP_ROOT))
    JOBS[job_id] = {"status": "queued", "progress": 0, "folder": str(folder), "created_at": time.time()}
    asyncio.create_task(download_job(job_id, request))
    return {"job_id": job_id}


@app.get("/api/download/{job_id}")
async def download_status(job_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "İş bulunamadı veya süresi doldu")
    response = {"status": job["status"], "progress": job["progress"], "error": job.get("error")}
    if job["status"] == "complete":
        response["download_url"] = f"/api/download/{job_id}/file"
        response["filename"] = job["filename"]
    if job["status"] == "error":
        background_tasks.add_task(cleanup, job_id)
    return response


@app.get("/api/download/{job_id}/file")
async def download_file(job_id: str, background_tasks: BackgroundTasks) -> FileResponse:
    job = JOBS.get(job_id)
    if not job or job.get("status") != "complete" or not Path(job.get("file", "")).is_file():
        raise HTTPException(404, "Dosya hazır değil veya süresi doldu")
    background_tasks.add_task(cleanup, job_id)
    return FileResponse(job["file"], media_type=job["mime"], filename=job["filename"])


app.mount("/", StaticFiles(directory=STATIC, html=True), name="frontend")
