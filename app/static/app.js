const $ = (sel) => document.querySelector(sel);

let current = null; // info del video cargado
let player = null;
let playerReady = false;
let pendingVideoId = null;

// --- Utilidades -------------------------------------------------------------

/** "1:02:30" | "1:23" | "83" -> segundos (NaN si no es válido) */
function parseTime(text) {
  const parts = text.trim().split(":");
  if (!parts.length || parts.length > 3 || parts.some((p) => p === "" || isNaN(p))) return NaN;
  return parts.reduce((acc, p) => acc * 60 + Number(p), 0);
}

/** segundos -> "1:02:30" o "1:23" */
function formatTime(total) {
  total = Math.floor(total);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

async function api(path, body) {
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((d) => d.msg.replace(/^Value error, /, "")).join(" ")
      : data.detail;
    throw new Error(detail || `Error ${res.status}`);
  }
  return data;
}

function showError(el, msg) {
  el.textContent = msg || "";
  el.hidden = !msg;
}

// --- Reproductor (YouTube IFrame API) --------------------------------------

window.onYouTubeIframeAPIReady = () => {
  playerReady = true;
  if (pendingVideoId) loadPlayer(pendingVideoId);
};

function loadPlayer(videoId) {
  if (!playerReady) {
    pendingVideoId = videoId;
    return;
  }
  if (player) {
    player.cueVideoById(videoId);
    return;
  }
  player = new YT.Player("player", {
    videoId,
    playerVars: { rel: 0, modestbranding: 1 },
  });
}

// --- Vista previa según la plataforma -----------------------------------------

/** YouTube usa su reproductor embebido; Facebook/Instagram, un <video> con el
 *  enlace directo que devuelve el servidor (o la miniatura si no hay enlace). */
function showPreview(info) {
  const native = $("#native-player");
  const thumb = $("#thumb");
  const isYouTube = info.platform === "youtube";

  $("#yt-wrap").hidden = !isYouTube;
  native.hidden = true;
  thumb.hidden = true;
  native.onerror = null;
  native.pause();
  native.removeAttribute("src");
  native.load();

  if (isYouTube) {
    loadPlayer(info.id);
    return;
  }
  if (player && typeof player.pauseVideo === "function") player.pauseVideo();

  const showThumb = () => {
    native.hidden = true;
    if (info.thumbnail) {
      thumb.src = info.thumbnail;
      thumb.hidden = false;
    }
  };
  if (info.preview_url) {
    native.poster = info.thumbnail || "";
    native.onerror = showThumb;
    native.src = info.preview_url;
    native.hidden = false;
  } else {
    showThumb();
  }
}

/** Segundo actual del reproductor visible, o null si no hay reproductor. */
function currentTime() {
  if (current?.platform === "youtube") {
    return player && typeof player.getCurrentTime === "function" ? player.getCurrentTime() : null;
  }
  const native = $("#native-player");
  return native.hidden ? null : native.currentTime;
}

// --- Buscar video ------------------------------------------------------------

$("#search-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("#search-btn");
  btn.disabled = true;
  btn.textContent = "Buscando…";
  showError($("#search-error"), "");
  try {
    current = await api("/api/info", { url: $("#url").value });
    current.url = $("#url").value.trim();
    renderVideo(current);
  } catch (err) {
    showError($("#search-error"), err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Buscar";
  }
});

function renderVideo(info) {
  $("#title").textContent = info.title;
  const PLATFORMS = { youtube: "YouTube", facebook: "Facebook", instagram: "Instagram" };
  const mutedPreview = info.preview_url && !info.preview_audio
    ? "vista previa sin sonido (la descarga sí lleva audio)"
    : null;
  $("#meta").textContent = [
    PLATFORMS[info.platform],
    info.uploader,
    info.duration ? formatTime(info.duration) : null,
    mutedPreview,
  ]
    .filter(Boolean)
    .join(" · ");

  const select = $("#height");
  select.innerHTML = "";
  select.add(new Option(`Mejor disponible${info.heights[0] ? ` (${info.heights[0]}p)` : ""}`, ""));
  for (const h of info.heights) select.add(new Option(`${h}p`, h));

  $("#start").value = "";
  $("#end").value = "";
  showError($("#download-error"), "");
  $("#video").hidden = false;
  showPreview(info);
}

// --- Opciones ----------------------------------------------------------------

function updateOptions() {
  const audio = document.querySelector("input[name=mode]:checked").value === "audio";
  document.querySelectorAll(".video-only").forEach((el) => (el.hidden = audio));
  const fragment = document.querySelector("input[name=range]:checked").value === "fragment";
  $("#fragment").hidden = !fragment;
}
document.querySelectorAll("input[name=mode], input[name=range]").forEach((el) =>
  el.addEventListener("change", updateOptions),
);

document.querySelectorAll("[data-mark]").forEach((btn) =>
  btn.addEventListener("click", () => {
    const t = currentTime();
    if (t == null) return;
    $(`#${btn.dataset.mark}`).value = formatTime(t);
  }),
);

// --- Descargar ---------------------------------------------------------------

$("#download-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = $("#download-error");
  showError(errorEl, "");

  const mode = document.querySelector("input[name=mode]:checked").value;
  const fragment = document.querySelector("input[name=range]:checked").value === "fragment";
  const body = {
    url: current.url,
    mode,
    container: $("#container").value,
    height: $("#height").value ? Number($("#height").value) : null,
    exact: fragment && mode === "video" && $("#exact").checked,
  };

  let label = mode === "audio" ? "Audio" : "Video";
  if (fragment) {
    const start = parseTime($("#start").value);
    const end = parseTime($("#end").value);
    if (isNaN(start) || isNaN(end)) return showError(errorEl, "Escribe el inicio y el fin (ej. 1:23).");
    if (start >= end) return showError(errorEl, "El inicio debe ser menor que el fin.");
    if (current.duration && end > current.duration) {
      return showError(errorEl, `El video dura ${formatTime(current.duration)}.`);
    }
    body.start = start;
    body.end = end;
    label += ` ${formatTime(start)}–${formatTime(end)}`;
  } else {
    label += " completo";
  }

  try {
    const job = await api("/api/download", body);
    addJob(job, `${current.title} · ${label}`);
  } catch (err) {
    showError(errorEl, err.message);
  }
});

function addJob(job, title) {
  $("#jobs-section").hidden = false;
  const li = document.createElement("li");
  li.className = "job";
  li.innerHTML = `
    <div class="job-title"></div>
    <div class="bar"><div class="fill"></div></div>
    <div class="job-status muted"></div>
    <a class="save" hidden>Guardar en mi PC</a>`;
  li.querySelector(".job-title").textContent = title;
  $("#jobs").prepend(li);
  pollJob(job.id, li);
}

async function pollJob(id, li) {
  let job;
  try {
    job = await api(`/api/jobs/${id}`);
  } catch (err) {
    li.querySelector(".job-status").textContent = err.message;
    return;
  }
  const bar = li.querySelector(".bar");
  const fill = li.querySelector(".fill");
  const status = li.querySelector(".job-status");

  bar.classList.toggle("indeterminate", job.progress == null && job.status !== "error");
  fill.style.width = job.progress != null ? `${job.progress}%` : "";
  status.textContent = job.progress != null && job.status !== "listo"
    ? `${job.message} · ${job.progress.toFixed(0)}%`
    : job.message;

  if (job.status === "listo") {
    li.classList.add("done");
    status.textContent = job.filename;
    const link = li.querySelector(".save");
    link.href = `/api/jobs/${id}/file`;
    link.hidden = false;
  } else if (job.status === "error") {
    li.classList.add("failed");
    status.textContent = job.error;
  } else {
    setTimeout(() => pollJob(id, li), 1000);
  }
}

// --- Estado de cookies.txt ---------------------------------------------------

async function refreshCookiesStatus() {
  const el = $("#cookies-status");
  try {
    const { cookies } = await api("/api/status");
    el.textContent = cookies ? "cookies.txt activo ✓" : "sin cookies.txt";
    el.classList.toggle("ok", cookies);
  } catch {
    el.textContent = "";
  }
}
refreshCookiesStatus();
$(".help").addEventListener("toggle", refreshCookiesStatus);
