#!/usr/bin/env bash
# Renderiza un tramo de fotogramas y lo guarda como clip en video/tramos/.
# Uso: bash video/render_tramo.sh INICIO FIN [MUESTRAS]
#      ESCENA=escena_mi_video.py bash video/render_tramo.sh 1 20     (otra escena)
set -euo pipefail
INI=$1; FIN=$2; SAMPLES=${3:-64}
ESCENA=${ESCENA:-escena_poleas.py}
EXTRA=()
# las escenas hechas con la plantilla aceptan --calidad
grep -q -- "--calidad" "$(git rev-parse --show-toplevel)/video/$ESCENA" && EXTRA=(--calidad final)
ROOT=$(git rev-parse --show-toplevel)
WORK=${WORK:-/tmp/render_$INI}
mkdir -p "$WORK"
if [ ! -x "$WORK/bl/bin/python" ]; then
  uv venv -q -p 3.13 "$WORK/bl"
  uv pip install -q -p "$WORK/bl/bin/python" bpy==5.2.3
fi
"$WORK/bl/bin/python" "$ROOT/video/$ESCENA" --out "$WORK/frames" \
  --samples "$SAMPLES" --frames "$INI-$FIN" "${EXTRA[@]}"
mkdir -p "$ROOT/video/tramos"
NAME=$(printf "tramo_%04d_%04d.mp4" "$INI" "$FIN")
ffmpeg -loglevel error -y -framerate 24 -start_number "$INI" -i "$WORK/frames/f_%04d.png" \
  -c:v libx264 -preset slow -crf 12 -pix_fmt yuv420p "$ROOT/video/tramos/$NAME"
echo "OK $ROOT/video/tramos/$NAME"
