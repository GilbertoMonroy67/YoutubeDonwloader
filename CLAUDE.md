# YouTube Downloader — contexto del proyecto

Aplicación web **local** para descargar videos de YouTube (completos o fragmentos)
sin perder calidad. La usa un creador de contenido que saca clips de YouTube para
editar sus propios videos. Toda la comunicación, la interfaz y los comentarios del
código van **en español**.

También descarga **videos y reels públicos de Facebook e Instagram** con las mismas
opciones (completo, fragmento, corte exacto, solo audio).

## Objetivos

1. **Cero pérdida de calidad**: obtener exactamente los streams que sirve YouTube
   (mejor video + mejor audio) y unirlos con ffmpeg **sin recodificar** (remux).
2. **Sin malware**: solo herramientas open source instaladas desde fuentes oficiales
   (pip, apt, deno.land). Nada de webs de descarga de terceros.
3. **Descargar completo o solo un fragmento** (inicio/fin), sin tener que ver ni
   bajar el video entero. La interfaz incluye un reproductor embebido para buscar
   el momento y marcar inicio/fin con un clic.
4. **Archivos listos para editar**: por defecto MP4 con H.264 + AAC cuando existe a
   la resolución elegida, porque es lo que mejor importan Premiere, DaVinci, CapCut, etc.

## Stack

- **Backend**: Python 3.12 + FastAPI + Uvicorn, usando `yt-dlp` como librería.
- **ffmpeg** (apt): unión de streams, recortes y extracción de audio.
- **Deno** (`~/.deno/bin`): yt-dlp lo necesita como runtime JS para resolver los
  desafíos de YouTube. `run.sh` lo añade al PATH.
- **Frontend**: HTML + CSS + JS sin framework ni build, servido por FastAPI como
  estáticos. Usa la YouTube IFrame API para la vista previa.
- Entorno: WSL Ubuntu. La app escucha solo en `127.0.0.1:8000` y se abre desde el
  navegador de Windows.

## Estructura

```
app/
  main.py         # API FastAPI: /api/info, /api/download, /api/jobs/{id}[/file]
  downloader.py   # Lógica con yt-dlp/ffmpeg, cola de trabajos en memoria
  static/         # index.html, app.js, styles.css
descargas/        # Archivos descargados (ignorado por git)
run.sh            # Crea el venv, actualiza dependencias y arranca el servidor
requirements.txt
```

## Comandos

```bash
./run.sh          # instala/actualiza dependencias (incluye yt-dlp) y arranca en http://127.0.0.1:8000
```

`run.sh` ejecuta `pip install -U` en cada arranque **a propósito**: YouTube cambia
seguido y una versión vieja de yt-dlp deja de funcionar. Si no hay internet, sigue
con la versión instalada.

### Lanzador para Windows (sin terminal)
- `iniciar.vbs`: si el servidor no responde, lo arranca oculto en WSL
  (`bash run.sh > servidor.log`), espera hasta 90 s y abre el navegador. Saca la
  distro y la ruta Linux de su propia ubicación (`\\wsl.localhost\<distro>\...`).
- `detener.vbs`: hace `pkill -f "uvicorn app.main:app"`.
- Hay accesos directos en el escritorio (OneDrive\Escritorio) que apuntan a
  `wscript.exe` con estos scripts.
- Se llama `bash run.sh` y no `./run.sh` porque editar el archivo desde Windows
  (ruta UNC) le quita el permiso de ejecución.
- Se descartó empaquetar un `.exe` (PyInstaller): congelaría yt-dlp y dejaría de
  funcionar cuando YouTube cambie algo.

## Decisiones técnicas clave

### Selección de formato
- Se usa `format = "bv*+ba/b"` y se controla la preferencia con `format_sort`:
  - **MP4**: `res[:altura]`, `vcodec:h264`, `acodec:aac`. Prioriza la resolución y,
    dentro de la misma resolución, H.264/AAC. YouTube solo ofrece H.264 hasta
    1080p; en 1440p/4K el video viene en VP9/AV1 (también dentro del MP4).
  - **MKV**: orden por defecto de yt-dlp (mejor códec: AV1/VP9 + Opus). Es la máxima
    calidad, pero algunos editores no lo importan bien.
- **Solo audio**: `ba` + `FFmpegExtractAudio` con `preferredcodec: "best"`, que
  conserva el códec original (Opus/AAC) sin recodificar. Nunca convertir a MP3:
  sería otra compresión con pérdida.

### Fragmentos: dos modos
- **Rápido sin pérdida** (por defecto): `download_ranges` de yt-dlp con copia de
  streams. Solo baja ese tramo. El corte cae en el keyframe anterior, así que el
  clip puede empezar unos segundos antes de lo pedido. Calidad intacta. Verificado:
  el audio y el video quedan sincronizados (en MP4 los frames previos se ocultan con
  una edit list; en MKV el clip simplemente dura un poco más).
- **Corte exacto** (opcional, solo video): se obtienen las URLs de los streams con
  yt-dlp y se ejecuta ffmpeg directamente con `-ss` en la entrada y
  recodificación H.264 (`crf 16`, preset `medium`) + AAC 320k. Es exacto al frame,
  la pérdida es imperceptible y tarda más. La salida siempre es MP4.
  No se usa `force_keyframes_at_cuts` de yt-dlp porque falla al recodificar a
  H.264 dentro de contenedores WebM intermedios.
- **Fragmentos de solo audio** (`_audio_cut`): no usan `download_ranges`. El WebM de
  solo audio tiene puntos de búsqueda muy espaciados y la copia directa arrancaba
  hasta 10 s antes. Se usa ffmpeg con búsqueda gruesa en la entrada
  (`-ss inicio-30` antes de `-i`) y fina en la salida (`-ss 30` después de `-i`) con
  `-c:a copy`. Así queda preciso (~20 ms) y sin recodificar. El modo exacto no aplica
  al audio.

### Facebook e Instagram
- `PLATFORM_DOMAINS` mapea dominio → plataforma (`youtube`, `facebook`, `instagram`)
  y acepta subdominios (`web.facebook.com`, `fb.watch`, etc.). `/api/info` devuelve
  `platform`.
- No tienen reproductor embebible: la vista previa es un `<video>` con el enlace
  directo del CDN (`preview_url`). Se prefiere un formato con audio; si no hay, uno
  solo de video (`preview_audio: false`, la UI avisa). Si el CDN rechaza el enlace,
  se muestra la miniatura.
- Facebook titula los reels "9.9K views · 340 reactions | texto | autor":
  `FB_TITLE_RE` lo limpia en la UI y, con `MetadataParser` (pre_process), en el
  nombre del archivo.
- Facebook suele dar la mejor resolución en VP9 (H.264 solo en la versión SD); se
  aplica la misma regla que en YouTube: primero resolución, luego H.264.
- Instagram puede pedir sesión o limitar consultas; `clean_error` lo traduce.
  Instagram a veces no informa la duración.

### Cookies (videos con restricción de edad / que piden sesión)
- Si existe `cookies.txt` (formato Netscape) en la raíz del proyecto, se usa en todas
  las llamadas a yt-dlp vía el context manager `_ydl`. Se revisa en cada uso: no
  hace falta reiniciar. Está en `.gitignore`.
- yt-dlp reescribe el archivo de cookies al cerrar; con 2 workers podrían pisarse, así
  que cada uso trabaja sobre una **copia temporal** y el original no se toca.
- No se usa `cookiesfrombrowser`: Chrome/Edge en Windows cifran las cookies
  (app-bound encryption) y la app corre en WSL. El usuario exporta `cookies.txt` con
  la extensión "Get cookies.txt LOCALLY" desde una ventana de incógnito (pasos en
  la sección de ayuda de la UI). `/api/status` indica si el archivo está presente.
- Los cortes por ffmpeg (exacto/audio) no le pasan cookies a ffmpeg: las URLs de los
  streams ya vienen firmadas.

### Trabajos
- Cola en memoria (`JOBS` dict) + `ThreadPoolExecutor(max_workers=2)`. Se pierde al
  reiniciar el servidor, lo cual es aceptable para uso local.
- El frontend consulta `/api/jobs/{id}` cada segundo para mostrar el progreso.
- Los archivos quedan en `descargas/` y también se pueden guardar desde el
  navegador con `/api/jobs/{id}/file`.

## Seguridad
- Solo se aceptan URLs de YouTube, Facebook e Instagram (`validate_url`/`platform_of`).
- Nunca se pasa entrada del usuario a una shell: se usa la API de yt-dlp y
  `subprocess` con lista de argumentos.
- `noplaylist: True` para no bajar listas enteras por accidente.
- `windowsfilenames: True` para que los nombres sean válidos al abrirlos desde Windows.
- El endpoint de archivo verifica que la ruta esté dentro de `descargas/`.

## Problemas conocidos
- Ejecutar en servidores/VPS suele provocar bloqueos de YouTube ("Sign in to confirm
  you're not a bot"). Por eso la app es local. Si aparece en local, actualizar
  yt-dlp; como último recurso, poner un `cookies.txt`.
- Videos con inserción deshabilitada no se ven en la vista previa embebida, pero sí
  se pueden descargar.

## Contexto legal (para recordarle al usuario cuando aplique)
Descargar va contra los términos de YouTube, que es un tema contractual. Lo que
importa para el usuario es el **uso** de los clips en sus videos: es más defendible
si son fragmentos cortos con comentario o aporte propio (fair use/derecho de cita).
Dar crédito no equivale a tener permiso. La música es lo que más detecta Content ID.

## Ideas pendientes
- Historial de descargas persistente.
- Varios fragmentos del mismo video en una sola operación.
- Subir `cookies.txt` desde la UI (hoy se copia a mano a la carpeta).
- Botón para abrir la carpeta `descargas/` desde Windows.
