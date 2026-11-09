#!/usr/bin/env bash
# Crea el entorno, actualiza dependencias (yt-dlp debe estar al día) y arranca la app.
set -euo pipefail
cd "$(dirname "$0")"

export PATH="$HOME/.deno/bin:$PATH"  # yt-dlp usa Deno para los desafíos JS de YouTube

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -U -r requirements.txt || echo "Aviso: no se pudieron actualizar las dependencias (¿sin internet?). Se usa la versión instalada."

echo "Abre http://127.0.0.1:8000 en tu navegador"
exec uvicorn app.main:app --host 127.0.0.1 --port 8000
