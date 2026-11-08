#!/usr/bin/env bash
# Une los tramos renderizados y añade rótulos. Resultado: video/poleas_A2_rotura.mp4
set -euo pipefail
cd "$(dirname "$0")"
ls "$PWD"/tramos/tramo_*.mp4 | sort | sed "s/^/file '/; s/$/'/" > /tmp/lista_tramos.txt
N=$(wc -l < /tmp/lista_tramos.txt)
[ "$N" -eq 12 ] || { echo "Faltan tramos: hay $N de 12"; exit 1; }
B=/usr/share/fonts/opentype/inter/Inter-Bold.otf
R=/usr/share/fonts/opentype/inter/Inter-Regular.otf
txt() { # texto, fuente, tamaño, y, inicio, fin
  echo "drawtext=fontfile=$2:text='$1':fontsize=$3:fontcolor=white:x=(w-text_w)/2:y=$4:shadowcolor=black@0.6:shadowx=2:shadowy=2:alpha='if(lt(t,$5),0,if(lt(t,$5+0.4),(t-$5)/0.4,if(lt(t,$6-0.4),1,if(lt(t,$6),($6-t)/0.4,0))))'"
}
F="$(txt 'Las poleas de los dedos' $B 72 h*0.12 0.3 2.8)"
F="$F,$(txt 'Anillos fibrosos que mantienen el tendón pegado al hueso' $R 40 h*0.12+90 0.8 2.8)"
F="$F,$(txt 'Poleas A2 y A4 (en azul)' $B 54 h*0.82 3.2 5.0)"
F="$F,$(txt 'Agarre en arqueo: máxima carga sobre la A2' $B 54 h*0.82 5.0 5.8)"
F="$F,$(txt 'ROTURA DE LA POLEA A2' $B 80 h*0.12 5.85 7.6)"
F="$F,$(txt 'Efecto cuerda de arco' $B 64 h*0.80 7.4 10.0)"
F="$F,$(txt 'el tendón se separa del hueso' $R 44 h*0.80+80 7.6 10.0)"
F="$F,fade=t=in:st=0:d=0.5,fade=t=out:st=9.5:d=0.5"
ffmpeg -loglevel error -y -f concat -safe 0 -i /tmp/lista_tramos.txt -vf "$F" \
  -c:v libx264 -preset slow -crf 16 -pix_fmt yuv420p -movflags +faststart poleas_A2_rotura.mp4
echo "OK video/poleas_A2_rotura.mp4"
