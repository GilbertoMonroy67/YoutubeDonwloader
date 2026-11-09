"""API web de la app. Arrancar con ./run.sh"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, model_validator

from . import downloader

app = FastAPI(title="Video Downloader (YouTube, Facebook, Instagram)")
executor = ThreadPoolExecutor(max_workers=2)
STATIC_DIR = Path(__file__).parent / "static"


class InfoRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    url: str
    mode: Literal["video", "audio"] = "video"
    container: Literal["mp4", "mkv"] = "mp4"
    height: int | None = None
    start: float | None = None
    end: float | None = None
    exact: bool = False

    @model_validator(mode="after")
    def check_range(self):
        if (self.start is None) != (self.end is None):
            raise ValueError("Indica el inicio y el fin del fragmento.")
        if self.start is not None and not 0 <= self.start < self.end:
            raise ValueError("El inicio debe ser menor que el fin.")
        return self

    @property
    def is_fragment(self) -> bool:
        return self.start is not None


def _validated_url(url: str) -> str:
    try:
        return downloader.validate_url(url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/status")
def status():
    return {"cookies": downloader.COOKIES_FILE.is_file()}


@app.post("/api/info")
def info(body: InfoRequest):
    url = _validated_url(body.url)
    try:
        return downloader.get_info(url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, downloader.clean_error(exc)) from exc


@app.post("/api/download")
def download(body: DownloadRequest):
    req = body.model_copy(update={"url": _validated_url(body.url)})
    job = downloader.create_job()
    executor.submit(downloader.run_job, job, req)
    return asdict(job)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = downloader.JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Trabajo no encontrado.")
    return asdict(job)


@app.get("/api/jobs/{job_id}/file")
def job_file(job_id: str):
    job = downloader.JOBS.get(job_id)
    if not job or job.status != "listo" or not job.filename:
        raise HTTPException(404, "Archivo no disponible.")
    path = (downloader.DOWNLOAD_DIR / job.filename).resolve()
    if path.parent != downloader.DOWNLOAD_DIR or not path.is_file():
        raise HTTPException(404, "Archivo no disponible.")
    return FileResponse(path, filename=job.filename)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
