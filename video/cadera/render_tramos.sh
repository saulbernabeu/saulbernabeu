#!/usr/bin/env bash
# Renderiza todos los planos en tramos de hasta 48 fotogramas (se puede reanudar).
# Uso: bash video/cadera/render_tramos.sh [MUESTRAS] [RES%]
set -euo pipefail
SAMPLES=${1:-12}; RES=${2:-50}
HERE=$(cd "$(dirname "$0")" && pwd)
PY=${BPY:-python}
WORK=${WORK:-/tmp/render_cadera}
mkdir -p "$HERE/tramos" "$WORK"
# tramos alineados con los planos (el plano «tres», 636-700, es un rótulo 2D)
"$PY" - "$HERE" > "$WORK/tramos.txt" <<'PYEOF'
import sys, math
sys.path.insert(0, sys.argv[1])
SHOTS = [("gancho",0.00,6.00),("escaleras",6.00,8.20),("cruzar",8.20,9.85),("unapierna",9.85,11.65),
 ("rayosx",11.65,14.30),("anatomia",14.30,22.80),("noche",22.80,26.50),("tres",26.50,29.20),
 ("error1",29.20,34.90),("error2",34.90,39.10),("error3",39.10,45.20),("solucion",45.20,53.30),("cierre",53.30,60.00)]
prev = 0
for i, (n, a, b) in enumerate(SHOTS):
    f0 = prev; f1 = 1440 if i == len(SHOTS) - 1 else round(b * 24); prev = f1
    if n == "tres": continue
    k = math.ceil((f1 - f0) / 48)
    for j in range(k):
        s = f0 + (f1 - f0) * j // k; e = f0 + (f1 - f0) * (j + 1) // k - 1
        print(s, e)
PYEOF
while read -r A B; do
  NAME=$(printf "tramo_%04d_%04d" "$A" "$B")
  [ -f "$HERE/tramos/$NAME.mp4" ] && continue
  rm -rf "$WORK/$NAME"
  "$PY" "$HERE/escena_cadera.py" --out "$WORK/$NAME" --frames "$A-$B" --samples "$SAMPLES" --res "$RES" < /dev/null \
    2>&1 | grep --line-buffered -E "^FRAME|Error|Traceback" || true
  N=$(ls "$WORK/$NAME"/f_*.png 2>/dev/null | wc -l)
  [ "$N" -eq $((B - A + 1)) ] || { echo "Tramo $NAME incompleto ($N)"; exit 1; }
  cp "$WORK/$NAME/anclas.json" "$HERE/tramos/$NAME.json"
  ffmpeg -nostdin -loglevel error -y -framerate 24 -start_number "$A" -i "$WORK/$NAME/f_%04d.png" \
    -c:v libx264 -preset slow -crf 12 -pix_fmt yuv420p "$HERE/tramos/$NAME.mp4.part.mp4"
  mv "$HERE/tramos/$NAME.mp4.part.mp4" "$HERE/tramos/$NAME.mp4"
  echo "OK $NAME"
done < "$WORK/tramos.txt"
echo "TODOS LOS TRAMOS LISTOS"
