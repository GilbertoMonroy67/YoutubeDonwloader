"""Lógica de descarga: envuelve yt-dlp y ffmpeg y lleva la cola de trabajos."""

import re
import shutil
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from yt_dlp.postprocessor import MetadataParserPP
from yt_dlp.utils import download_range_func

DOWNLOAD_DIR = (Path(__file__).resolve().parent.parent / "descargas").resolve()
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Dominio base -> plataforma. También se aceptan sus subdominios
# (www., m., web., es-la.facebook.com, etc.).
PLATFORM_DOMAINS = {
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "facebook.com": "facebook",
    "fb.com": "facebook",
    "fb.watch": "facebook",
    "instagram.com": "instagram",
}

BASE_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "windowsfilenames": True,
}

# Cookies opcionales (formato Netscape, exportadas del navegador) para videos con
# restricción de edad o que piden iniciar sesión. Si el archivo no existe, se
# descarga sin sesión.
COOKIES_FILE = DOWNLOAD_DIR.parent / "cookies.txt"


@contextmanager
def _ydl(opts: dict):
    """YoutubeDL con cookies.txt si existe (se revisa en cada uso, así que no hay
    que reiniciar el servidor al añadirlo).

    yt-dlp reescribe el archivo de cookies al cerrar; con dos trabajos a la vez
    podrían pisarse y corromperlo. Por eso cada uso trabaja sobre una copia
    temporal y el original nunca se modifica.
    """
    if not COOKIES_FILE.is_file():
        with yt_dlp.YoutubeDL(opts) as ydl:
            yield ydl
        return
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "cookies.txt"
        shutil.copyfile(COOKIES_FILE, copy)
        with yt_dlp.YoutubeDL({**opts, "cookiefile": str(copy)}) as ydl:
            yield ydl


# Facebook titula los reels como "9.9K views · 340 reactions | texto | autor".
FB_TITLE_RE = r"^[^|]*·[^|]*\| (?P<title>.+) \| [^|]+$"


@dataclass
class Job:
    id: str
    status: str = "en_cola"  # en_cola | descargando | procesando | listo | error
    progress: float | None = None
    message: str = "En cola"
    filename: str | None = None
    error: str | None = None


JOBS: dict[str, Job] = {}


def create_job() -> Job:
    job = Job(id=uuid.uuid4().hex)
    JOBS[job.id] = job
    return job


def platform_of(url: str) -> str | None:
    """Devuelve 'youtube', 'facebook' o 'instagram' según el dominio, o None."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    for domain, platform in PLATFORM_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return platform
    return None


def validate_url(url: str) -> str:
    url = url.strip()
    if not platform_of(url):
        raise ValueError("Solo se aceptan enlaces de YouTube, Facebook o Instagram.")
    return url


def clean_error(exc: Exception) -> str:
    msg = str(exc).removeprefix("ERROR: ").strip()
    low = msg.lower()
    if "matches no streams" in low or "unable to obtain file audio codec" in low:
        return "Este video no tiene pista de audio."
    has_cookies = COOKIES_FILE.is_file()
    if "confirm your age" in low or "age-restricted" in low:
        if has_cookies:
            return ("Video con restricción de edad y las cookies de cookies.txt no sirvieron: "
                    "puede que hayan caducado o que la cuenta no tenga la edad verificada. "
                    "Vuelve a exportarlas.")
        return ("Video con restricción de edad: YouTube exige una cuenta con sesión iniciada. "
                "Exporta las cookies de YouTube a un archivo cookies.txt en la carpeta del "
                "proyecto (abajo en la página están los pasos) y vuelve a intentarlo.")
    if "not a bot" in low:
        return ("YouTube bloqueó la consulta (\"confirma que no eres un bot\"). Espera unos "
                "minutos; si sigue, " + ("vuelve a exportar cookies.txt." if has_cookies
                                         else "pon un archivo cookies.txt en la carpeta del proyecto."))
    if "instagram" in low and ("login" in low or "rate-limit" in low or "cookies" in low):
        return ("Instagram pide iniciar sesión para este contenido (o limitó las consultas). "
                "Prueba de nuevo en unos minutos o añade cookies de Instagram a cookies.txt.")
    if "facebook" in low and ("login" in low or "cookies" in low):
        return ("Facebook pide iniciar sesión para este video. Si es público, añade cookies "
                "de Facebook a cookies.txt.")
    return msg


def _preview(info: dict) -> tuple[str | None, bool]:
    """Enlace directo para la vista previa en un <video> del navegador
    (Facebook/Instagram no tienen reproductor embebible). Devuelve (url, tiene_audio).

    Prefiere el mejor formato con video y audio juntos; si no hay, el video más
    ligero sin audio, que sirve igual para buscar el momento y marcar tiempos.
    yt-dlp ordena los formatos de peor a mejor; un códec None significa desconocido.
    """
    formats = [
        f for f in info.get("formats", [])
        if f.get("protocol") in ("http", "https") and f.get("vcodec") != "none"
    ]
    for f in reversed(formats):
        if f.get("acodec") != "none":
            return f["url"], True
    return (formats[0]["url"], False) if formats else (None, False)


def _clean_title(title: str | None, platform: str | None) -> str | None:
    """Facebook pone en el título '9.9K views · 340 reactions | texto | autor'."""
    if title and platform == "facebook" and (m := re.match(FB_TITLE_RE, title)):
        return m["title"]
    return title


def get_info(url: str) -> dict:
    platform = platform_of(url)
    with _ydl(BASE_OPTS) as ydl:
        info = ydl.extract_info(url, download=False)
    heights = sorted(
        {
            f["height"]
            for f in info.get("formats", [])
            if f.get("height") and f.get("vcodec") not in (None, "none")
        },
        reverse=True,
    )
    preview_url, preview_audio = (None, False) if platform == "youtube" else _preview(info)
    return {
        "id": info["id"],
        "platform": platform,
        "title": _clean_title(info.get("title"), platform),
        "uploader": info.get("uploader") or info.get("channel"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "heights": heights,
        "preview_url": preview_url,
        "preview_audio": preview_audio,
    }


def _fmt_time(seconds: float) -> str:
    """83.5 -> '1m23s' (para nombres de archivo, sin ':' que Windows no admite)."""
    s = int(seconds)
    h, rest = divmod(s, 3600)
    m, s = divmod(rest, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


def _format_opts(req, container: str) -> dict:
    if req.mode == "audio":
        return {
            "format": "ba/b",
            # "best" conserva el códec original (Opus/AAC) sin recodificar.
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "best"}],
        }
    res = f"res:{req.height}" if req.height else "res"
    if container == "mp4":
        # Primero la resolución; a igual resolución, H.264 + AAC (mejor para editores).
        sort = [res, "vcodec:h264", "acodec:aac"]
    else:
        sort = [res]
    return {"format": "bv*+ba/b", "format_sort": sort, "merge_output_format": container}


def _opts(req, container: str) -> dict:
    """Opciones de yt-dlp comunes a la descarga directa y a resolver streams."""
    opts = {**BASE_OPTS, **_format_opts(req, container), "outtmpl": _outtmpl(req)}
    if platform_of(req.url) == "facebook":
        # Limpia el título antes de armar el nombre del archivo.
        clean = {"key": "MetadataParser", "when": "pre_process",
                 "actions": [(MetadataParserPP.Actions.INTERPRET, "title", FB_TITLE_RE)]}
        opts["postprocessors"] = [clean, *opts.get("postprocessors", [])]
    return opts


def _outtmpl(req) -> str:
    suffix = ""
    if req.is_fragment:
        exact = " exacto" if req.exact and req.mode == "video" else ""
        suffix = f" [{_fmt_time(req.start)}-{_fmt_time(req.end)}{exact}]"
    return str(DOWNLOAD_DIR / f"%(title).150B [%(id)s]{suffix}.%(ext)s")


def run_job(job: Job, req) -> None:
    try:
        if req.is_fragment and req.mode == "audio":
            _audio_cut(job, req)
        elif req.is_fragment and req.exact:
            _exact_cut(job, req)
        else:
            _ytdlp_download(job, req)
        job.status = "listo"
        job.progress = 100.0
        job.message = "Listo"
    except Exception as exc:  # noqa: BLE001 — cualquier fallo se muestra al usuario
        job.status = "error"
        job.error = clean_error(exc)
        job.message = "Error"


def _ytdlp_download(job: Job, req) -> None:
    def on_progress(d):
        job.status = "descargando"
        info = d.get("info_dict") or {}
        kind = "audio" if info.get("vcodec") == "none" else "video"
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes")
            job.progress = round(done * 100 / total, 1) if total and done else None
            job.message = f"Descargando {kind}"
        elif d["status"] == "finished":
            job.message = f"{kind.capitalize()} descargado"

    def on_postprocess(d):
        if d["status"] == "started":
            job.status = "procesando"
            job.progress = None
            job.message = "Procesando con ffmpeg (sin recodificar)"

    def on_finished(filepath):
        job.filename = Path(filepath).name

    opts = {
        **_opts(req, req.container),
        "progress_hooks": [on_progress],
        "postprocessor_hooks": [on_postprocess],
        "post_hooks": [on_finished],
    }
    if req.is_fragment:
        # Solo baja el tramo pedido, copiando streams (corta en el keyframe previo).
        opts["download_ranges"] = download_range_func(None, [(req.start, req.end)])

    job.status = "descargando"
    job.message = "Preparando descarga"
    with _ydl(opts) as ydl:
        ydl.download([req.url])


def _resolve_streams(job: Job, req, container: str) -> tuple[dict, list[dict], Path]:
    """Pide a yt-dlp las URLs directas de los streams elegidos, sin descargar nada."""
    job.status = "descargando"
    job.message = "Obteniendo enlaces del video"
    with _ydl(_opts(req, container)) as ydl:
        info = ydl.extract_info(req.url, download=False)
        path = Path(ydl.prepare_filename(info))
    return info, info.get("requested_formats") or [info], path


def _ffmpeg_inputs(streams: list[dict], seek: float) -> list[str]:
    args = []
    for f in streams:
        headers = "".join(f"{k}: {v}\r\n" for k, v in (f.get("http_headers") or {}).items())
        if headers:
            args += ["-headers", headers]
        args += ["-ss", f"{seek:.3f}", "-i", f["url"]]
    return args


def _run_ffmpeg(job: Job, args: list[str], duration: float, out: Path, message: str) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats", "-y", "-progress", "pipe:1",
           *args, str(out)]
    job.status = "procesando"
    job.message = message
    job.progress = 0.0
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in proc.stdout:
        key, _, value = line.strip().partition("=")
        if key == "out_time_us" and value.isdigit():
            job.progress = min(99.0, round(int(value) / 1e6 / duration * 100, 1))
    stderr = proc.stderr.read()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg falló: {stderr.strip()[-500:]}")
    job.filename = out.name


def _exact_cut(job: Job, req) -> None:
    """Corte exacto al frame: ffmpeg lee los streams de YouTube y recodifica en alta calidad."""
    _, streams, path = _resolve_streams(job, req, "mp4")
    duration = req.end - req.start
    args = _ffmpeg_inputs(streams, req.start)
    if len(streams) > 1:
        args += ["-map", "0:v:0", "-map", "1:a:0"]
    args += [
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "320k",
        "-movflags", "+faststart",
    ]
    _run_ffmpeg(job, args, duration, path.with_suffix(".mp4"),
                "Cortando y recodificando en alta calidad")


def _audio_cut(job: Job, req) -> None:
    """Fragmento de audio sin recodificar y preciso (~20 ms).

    Con copia directa, ffmpeg arranca en el punto de búsqueda previo del contenedor,
    que en WebM de solo audio puede estar 10 s antes. Por eso se busca en dos pasos:
    grueso en la entrada (rápido, por rango HTTP) y fino en la salida, que descarta
    los paquetes sobrantes uno a uno.
    """
    info, streams, path = _resolve_streams(job, req, "mp4")
    coarse = max(0.0, req.start - 30)
    duration = req.end - req.start
    ext = "opus" if info.get("acodec") == "opus" else info["ext"]
    if ext == "mp4":  # Facebook/Instagram sirven el audio en MP4: se guarda como .m4a
        ext = "m4a"
    args = _ffmpeg_inputs(streams[:1], coarse) + [
        "-ss", f"{req.start - coarse:.3f}",
        "-t", f"{duration:.3f}",
        "-map", "0:a:0",
        "-c:a", "copy",
    ]
    _run_ffmpeg(job, args, duration, path.with_suffix(f".{ext}"), "Recortando audio (sin recodificar)")
