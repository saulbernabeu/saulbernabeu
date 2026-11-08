"""Monta el reel final a partir de los tramos renderizados.

Uso:
    python3 video/cadera/montar.py [--borrador]

Necesita: tramos/*.mp4 (render_tramos.sh), audio/locucion.mp3 y audio/palabras.json.
Genera: reel_cadera.mp4 (1080x1920, 24 fps, ~60 s).
Con --borrador rellena en negro los tramos que falten.
"""
import argparse
import glob
import json
import math
import os
import random
import subprocess
import wave

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
FPS = 24
DUR = 60.0
W, H = 1080, 1920
TEMPO = 1.06            # la locución se acelera un 6 % (palabras.json ya está en esa escala)
WORK = os.environ.get("WORK", "/tmp/montaje_cadera")
FONT_DIR = "/usr/share/fonts/opentype/inter"
TRES = (636, 700)       # fotogramas del rótulo «3 errores»
CUTS = [6.00, 8.20, 9.85, 11.65, 14.30, 22.80, 26.50, 29.20, 34.90, 37.20, 39.10, 42.90, 45.20, 53.30]


def run(cmd):
    subprocess.run(cmd, check=True)


# ------------------------------------------------------------------ vídeo base

def base_video(draft):
    tramos = sorted(glob.glob(os.path.join(HERE, "tramos", "tramo_*.mp4")))
    have = {}
    for p in tramos:
        a, b = map(int, os.path.basename(p)[6:-4].split("_"))
        have[a] = (b, p)
    parts, f = [], 0
    while f < 1440:
        if f == TRES[0]:
            parts.append(tres_card(have))
            f = TRES[1] + 1
            continue
        if f in have:
            b, p = have[f]
            parts.append(p)
            f = b + 1
            continue
        if not draft:
            raise SystemExit(f"Falta el tramo que empieza en el fotograma {f}")
        nxt = min([k for k in have if k > f] + [TRES[0] if f < TRES[0] else 1440])
        black = os.path.join(WORK, f"negro_{f:04d}.mp4")
        run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
             f"color=c=0x05070c:s=540x960:r={FPS}", "-frames:v", str(nxt - f),
             "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", black])
        parts.append(black)
        f = nxt
    lst = os.path.join(WORK, "lista.txt")
    with open(lst, "w") as fh:
        fh.writelines(f"file '{p}'\n" for p in parts)
    out = os.path.join(WORK, "base.mp4")
    run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
         "-c", "copy", out])
    return out


def tres_card(have):
    """Fondo del rótulo «3 errores»: la cadera comprimida, desenfocada y oscura."""
    out = os.path.join(WORK, "tres.mp4")
    src = next((p for a, (b, p) in have.items() if a <= 520 <= b), None)
    n = TRES[1] - TRES[0] + 1
    if src:
        a = int(os.path.basename(src)[6:10])
        t = (520 - a) / FPS
        vf = (f"trim=start={t:.3f}:duration={1 / FPS:.4f},setpts=PTS-STARTPTS,loop={n}:1:0,"
              f"scale=600:-2,crop=540:960,gblur=sigma=18,eq=brightness=-0.12:saturation=1.3,"
              f"zoompan=z='1+0.0018*on':d=1:s=540x960:fps={FPS}")
        run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-vf", vf, "-frames:v", str(n),
             "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", "-r", str(FPS), out])
    else:
        run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
             f"color=c=0x1a0606:s=540x960:r={FPS}", "-frames:v", str(n),
             "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", out])
    return out


# ------------------------------------------------------------------ iconos

def icons():
    def canvas():
        return Image.new("RGBA", (440, 440), (0, 0, 0, 0))

    def disc(d, col):
        d.ellipse((20, 20, 420, 420), fill=col)
        d.ellipse((20, 20, 420, 420), outline=(255, 255, 255, 255), width=18)

    paths = {}
    im = canvas(); d = ImageDraw.Draw(im); disc(d, (226, 35, 40, 255))
    d.line((140, 140, 300, 300), fill="white", width=46); d.line((300, 140, 140, 300), fill="white", width=46)
    paths["no"] = im
    im = canvas(); d = ImageDraw.Draw(im); disc(d, (22, 178, 120, 255))
    d.line((120, 225, 195, 305), fill="white", width=46); d.line((190, 305, 325, 145), fill="white", width=46)
    paths["si"] = im
    im = canvas(); d = ImageDraw.Draw(im); disc(d, (255, 196, 0, 255))
    d.polygon([(150, 110), (290, 110), (290, 330), (220, 270), (150, 330)], fill="white")
    paths["guardar"] = im
    out = {}
    for k, im in paths.items():
        p = os.path.join(WORK, f"icono_{k}.png")
        im.resize((180, 180), Image.LANCZOS).save(p)
        out[k] = p
    return out


# Iconos: (icono, inicio, fin, y del centro)
ICONS = [
    ("no", 29.35, 31.60, 520), ("si", 32.70, 34.90, 520),
    ("no", 35.05, 39.10, 520), ("no", 39.25, 45.20, 520),
    ("si", 45.35, 53.30, 520), ("guardar", 53.40, 56.90, 520),
]


# ------------------------------------------------------------------ subtítulos y rótulos (ASS)

def ass_time(t):
    t = max(0.0, t)
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,Inter Black,84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,0,0,0,0,100,100,0,0,1,7,3,5,60,60,0,1
Style: Titulo,Inter Black,92,&H00FFFFFF,&H00FFFFFF,&H00101010,&H96000000,0,0,0,0,100,100,1,0,1,6,4,5,60,60,0,1
Style: Pill,Inter ExtraBold,54,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,3,18,0,5,60,60,0,1
Style: Etiqueta,Inter ExtraBold,46,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,0,0,0,0,100,100,0,0,1,4,2,5,0,0,0,1
Style: Grande,Inter Black,300,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,0,0,0,0,100,100,0,0,1,10,6,5,0,0,0,1
Style: Credito,Inter Medium,26,&H00D0D0D0,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,40,40,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

YELLOW = "&H0000D4FF&"
RED = "&H002A2AFF&"
GREEN = "&H0078C016&"
TEAL = "&H00BFD81A&"


def ev(lines, a, b, style, text, layer=0):
    lines.append(f"Dialogue: {layer},{ass_time(a)},{ass_time(b)},{style},,0,0,0,,{text}")


def subtitles(lines):
    words = json.load(open(os.path.join(HERE, "audio", "palabras.json")))
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        txt = w[0]
        if len(cur) >= 3 or txt[-1] in ".,?:;" or len(" ".join(x[0] for x in cur)) > 16:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    for ci, ch in enumerate(chunks):
        end_chunk = chunks[ci + 1][0][1] if ci + 1 < len(chunks) else DUR
        end_chunk = min(end_chunk, ch[-1][2] + 0.6)
        clean = [w[0].upper().strip("¿?.,:;").replace("«", "").replace("»", "") for w in ch]
        for wi, w in enumerate(ch):
            a = w[1]
            b = ch[wi + 1][1] if wi + 1 < len(ch) else end_chunk
            parts = []
            for k, c in enumerate(clean):
                parts.append("{\\c" + YELLOW + "}" + c + "{\\c&HFFFFFF&}" if k == wi else c)
            pop = "{\\fscx78\\fscy78\\t(0,110,\\fscx100\\fscy100)}" if wi == 0 else ""
            ev(lines, a, b, "Sub", "{\\pos(540,1420)}" + pop + " ".join(parts))


def titles(lines):
    T = []
    # etiquetas de situaciones
    for a, b, txt in ((7.15, 8.20, "SUBIR ESCALERAS"), (8.30, 9.85, "CRUZAR LAS PIERNAS"),
                      (9.95, 11.65, "APOYO EN UNA PIERNA")):
        T.append((a, b, "Pill", "{\\pos(540,330)\\3c&H2A2AE2&\\fad(120,120)}" + txt))
    T.append((12.70, 14.30, "Titulo", "{\\pos(540,320)\\fscx70\\fscy70\\t(0,150,\\fscx100\\fscy100)\\fad(0,150)}"
              "TENDINOPATÍA\\N{\\c" + RED + "}GLÚTEA"))
    T.append((19.85, 22.80, "Titulo", "{\\pos(540,300)\\fad(150,150)}COMPRESIÓN\\N{\\c" + RED + "}= DOLOR"))
    T.append((22.85, 26.50, "Titulo", "{\\pos(540,300)\\fad(150,150)}{\\c" + YELLOW + "}DE NOCHE\\N{\\c&HFFFFFF&}HORAS DE PRESIÓN"))
    T.append((26.50, 29.20, "Grande", "{\\pos(540,820)\\fscx40\\fscy40\\t(0,180,\\fscx100\\fscy100)\\c" + RED + "}3"))
    T.append((26.65, 29.20, "Titulo", "{\\pos(540,1130)\\fad(150,100)}ERRORES QUE\\NDEBES DEJAR YA"))
    for a, b, n, txt in ((29.30, 31.60, "1", "DORMIR SOBRE\\NEL LADO QUE DUELE"),
                         (35.05, 37.20, "2", "CRUZAR\\NLAS PIERNAS"),
                         (37.20, 39.10, "2", "COLGARTE\\NDE UNA CADERA"),
                         (39.25, 45.20, "3", "ESTIRAR\\NEL GLÚTEO")):
        T.append((a, b, "Titulo", "{\\pos(540,310)\\fad(100,100)}{\\c" + RED + "}" + n + ". {\\c&HFFFFFF&}" + txt))
    T.append((32.70, 34.90, "Titulo", "{\\pos(540,310)\\fad(100,100)}{\\c" + GREEN + "}MEJOR: {\\c&HFFFFFF&}COJÍN\\NENTRE LAS RODILLAS"))
    T.append((42.95, 45.20, "Pill", "{\\pos(540,700)\\3c&H2A2AE2&\\fad(100,100)}+ COMPRESIÓN DEL TENDÓN"))
    T.append((45.35, 53.30, "Titulo", "{\\pos(540,310)\\fad(120,120)}{\\c" + GREEN + "}LO QUE FUNCIONA:\\N{\\c&HFFFFFF&}CARGA PROGRESIVA"))
    T.append((48.90, 50.85, "Pill", "{\\pos(540,700)\\3c&H78A016&\\fad(100,100)}ISOMÉTRICOS"))
    T.append((50.95, 53.30, "Pill", "{\\pos(540,700)\\3c&H78A016&\\fad(100,100)}+ CARGA, POCO A POCO"))
    T.append((53.40, 56.95, "Titulo", "{\\pos(540,310)\\fad(120,120)}GUÁRDALO\\N{\\c" + YELLOW + "}Y COMPÁRTELO"))
    T.append((57.00, 60.00, "Titulo", "{\\pos(540,330)\\fad(120,0)}COMENTA"))
    T.append((58.40, 60.00, "Grande", "{\\pos(540,560)\\fs150\\c" + YELLOW + "\\fscx60\\fscy60\\t(0,160,\\fscx100\\fscy100)"
              "\\t(300,700,\\fscx106\\fscy106)\\t(700,1100,\\fscx100\\fscy100)}«CADERA»"))
    for a, b, st, txt in T:
        ev(lines, a, b, st, txt, layer=2)
    # reloj de la noche
    for i in range(int((26.5 - 22.85) * 8)):
        t0 = 22.85 + i / 8
        hrs = 23 + 8 * (t0 - 22.85) / (26.5 - 22.85)
        hh = int(hrs) % 24
        mm = int((hrs - int(hrs)) * 60) // 5 * 5
        ev(lines, t0, t0 + 1 / 8, "Grande", f"{{\\pos(540,620)\\fs120\\c&HFFE0B0&}}{hh:02d}:{mm:02d}", layer=2)
    ev(lines, 56.6, 60.0, "Credito", "{\\fad(300,0)}Anatomía: CT Anatomy GLB / TotalSegmentator (CC BY 4.0) · Voz: ElevenLabs",
       layer=3)


def labels(lines):
    """Rótulos anatómicos que siguen a la cámara (posiciones de anclas.json)."""
    anchors = {}
    for p in glob.glob(os.path.join(HERE, "tramos", "tramo_*.json")):
        anchors.update(json.load(open(p)))
    spec = {
        "medio": ("GLÚTEO MEDIO", 15.05, 19.35, (-1, -1)),
        "menor": ("GLÚTEO MENOR", 16.05, 19.35, (1, 1)),
        "trocanter": ("TROCÁNTER MAYOR", 17.95, 22.80, (-1, 1)),
    }
    for key, (txt, a, b, (sx, sy)) in spec.items():
        for f in range(int(a * FPS), int(b * FPS)):
            an = anchors.get(str(f), {}).get(key)
            if not an:
                continue
            x, y = an[0] * W, an[1] * H
            t0, t1 = f / FPS, (f + 1) / FPS
            fade = min(1.0, (t0 - a) / 0.25, (b - t0) / 0.25)
            alpha = f"&H{int(255 * (1 - max(0.0, fade))):02X}&"
            lx, ly = x + sx * 150, y + sy * 140
            lx = min(max(lx, 230), W - 230)
            # punto, línea y texto
            ev(lines, t0, t1, "Etiqueta",
               f"{{\\an7\\pos(0,0)\\bord0\\shad0\\1c&HFFFFFF&\\alpha{alpha}\\p1}}"
               f"m {x - 9:.0f} {y:.0f} b {x - 9:.0f} {y - 12:.0f} {x + 9:.0f} {y - 12:.0f} {x + 9:.0f} {y:.0f} "
               f"b {x + 9:.0f} {y + 12:.0f} {x - 9:.0f} {y + 12:.0f} {x - 9:.0f} {y:.0f}{{\\p0}}", layer=4)
            dx, dy = lx - x, ly - y
            n = math.hypot(dx, dy) or 1
            px, py = -dy / n * 2.5, dx / n * 2.5
            ev(lines, t0, t1, "Etiqueta",
               f"{{\\an7\\pos(0,0)\\bord0\\shad0\\1c&HFFFFFF&\\alpha{alpha}\\p1}}"
               f"m {x + px:.0f} {y + py:.0f} l {lx + px:.0f} {ly + py:.0f} l {lx - px:.0f} {ly - py:.0f} "
               f"l {x - px:.0f} {y - py:.0f}{{\\p0}}", layer=4)
            ev(lines, t0, t1, "Etiqueta",
               f"{{\\pos({lx:.0f},{ly + (-36 if sy < 0 else 36):.0f})\\alpha{alpha}}}{txt}", layer=5)


def write_ass():
    lines = []
    subtitles(lines)
    titles(lines)
    labels(lines)
    p = os.path.join(WORK, "rotulos.ass")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(HEADER + "\n".join(lines) + "\n")
    return p


# ------------------------------------------------------------------ sonido

SR = 48000


def synth_audio():
    n = int(DUR * SR)
    rng = np.random.default_rng(3)
    mix = np.zeros((n, 2))
    t = np.arange(n) / SR

    def add(sig, at, gain=1.0, pan=0.0):
        i = int(at * SR)
        j = min(n, i + len(sig))
        if i >= n:
            return
        s = sig[: j - i] * gain
        mix[i:j, 0] += s * (1 - pan) ** 0.5
        mix[i:j, 1] += s * (1 + pan) ** 0.5

    def lowpass(x, fc):
        a = math.exp(-2 * math.pi * fc / SR)
        y = np.empty_like(x)
        acc = 0.0
        for k in range(len(x)):
            acc = (1 - a) * x[k] + a * acc
            y[k] = acc
        return y

    def whoosh(d=0.45):
        m = int(d * SR)
        x = rng.standard_normal(m)
        env = np.sin(np.linspace(0, math.pi, m)) ** 2
        # barrido: pasabajos que se abre y se cierra
        y = np.zeros(m)
        acc = 0.0
        for k in range(m):
            fc = 300 + 5000 * env[k]
            a = math.exp(-2 * math.pi * fc / SR)
            acc = (1 - a) * x[k] + a * acc
            y[k] = acc
        return y * env * 0.5

    def boom(d=1.2):
        m = int(d * SR)
        tt = np.arange(m) / SR
        f = 90 * np.exp(-tt * 2.5) + 38
        ph = 2 * math.pi * np.cumsum(f) / SR
        return np.sin(ph) * np.exp(-tt * 3.2) * 0.9

    def ding(f0=1318.5):
        m = int(1.0 * SR)
        tt = np.arange(m) / SR
        return (np.sin(2 * math.pi * f0 * tt) + 0.5 * np.sin(2 * math.pi * f0 * 1.5 * tt)) * np.exp(-tt * 5) * 0.35

    def buzz():
        m = int(0.32 * SR)
        tt = np.arange(m) / SR
        sq = np.sign(np.sin(2 * math.pi * 110 * tt)) + np.sign(np.sin(2 * math.pi * 116 * tt))
        return lowpass(sq, 1200) * np.exp(-tt * 6) * 0.22

    def tick():
        m = int(0.03 * SR)
        return rng.standard_normal(m) * np.exp(-np.arange(m) / SR * 200) * 0.25

    # base musical: acordes suaves (La m - Fa - Do - Sol) con pulso lento
    chords = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (130.81, 196.0, 261.63), (196.0, 246.94, 293.66)]
    pad = np.zeros(n)
    bar = 3.75
    for i in range(int(DUR / bar) + 1):
        ch = chords[i % 4]
        a = int(i * bar * SR)
        b = min(n, int((i + 1) * bar * SR) + SR // 2)
        if a >= n:
            break
        tt = np.arange(b - a) / SR
        env = np.minimum(1, tt / 0.8) * np.minimum(1, np.maximum(0, (b - a) / SR - tt) / 0.6)
        seg = sum(np.sin(2 * math.pi * f * tt + k) + 0.5 * np.sin(2 * math.pi * f * 1.003 * tt)
                  for k, f in enumerate(ch))
        seg += 0.7 * np.sin(2 * math.pi * ch[0] / 2 * tt)
        pad[a:b] += seg * env
    pad = lowpass(pad, 900)
    beat = np.zeros(n)
    kick = boom(0.35) * 0.6
    for k in np.arange(6.0, 53.3, 60 / 96):
        i = int(k * SR)
        j = min(n, i + len(kick))
        beat[i:j] += kick[: j - i]
    music = pad / (np.abs(pad).max() + 1e-9) * 0.10 + beat * 0.22
    music *= np.clip((t - 0.2) / 1.5, 0, 1) * np.clip((DUR - t) / 1.0, 0, 1)
    mix[:, 0] += music
    mix[:, 1] += music

    add(boom(), 0.0, 0.8)
    for c in CUTS:
        add(whoosh(), c - 0.22, 0.55, pan=random.Random(int(c * 10)).uniform(-0.5, 0.5))
    add(boom(), 26.50, 0.9)
    for c in (29.35, 35.05, 39.25):
        add(buzz(), c, 1.0)
    for c in (32.70, 45.35):
        add(ding(), c, 1.0)
    add(ding(1567.98), 58.40, 1.0)
    for k in np.arange(22.85, 26.5, 0.5):
        add(tick(), k, 0.8)
    path = os.path.join(WORK, "efectos.wav")
    pcm = np.clip(mix, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((pcm * 32767).astype("<i2").tobytes())
    return path


# ------------------------------------------------------------------ montaje

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--borrador", action="store_true")
    ap.add_argument("--out", default=os.path.join(HERE, "reel_cadera.mp4"))
    args = ap.parse_args()
    os.makedirs(WORK, exist_ok=True)
    base = base_video(args.borrador)
    ass = write_ass()
    ic = icons()
    fx = synth_audio()
    voice = os.path.join(HERE, "audio", "locucion.mp3")
    flash = "+".join(f"0.22*exp(-((t-{c})*14)^2)*gte(t,{c - 0.03})" for c in CUTS)
    inputs = ["-i", base, "-i", voice, "-i", fx]
    for k in ("no", "si", "guardar"):
        inputs += ["-loop", "1", "-framerate", str(FPS), "-i", ic[k]]
    idx = {"no": 3, "si": 4, "guardar": 5}
    fc = [
        f"[0:v]scale={W}:{H}:flags=lanczos,unsharp=5:5:0.55,setsar=1,format=gbrp,split[a][b]",
        "[b]curves=all='0/0 0.62/0 1/1',gblur=sigma=28[g]",
        "[a][g]blend=all_mode=screen:all_opacity=0.55,format=yuv420p,"
        f"eq=brightness='{flash}':eval=frame,vignette=PI/5[v0]",
    ]
    last = "v0"
    for i, (k, a, b, y) in enumerate(ICONS):
        fc.append(f"[{idx[k]}:v]format=rgba,scale=180:180,"
                  f"fade=t=in:st={a}:d=0.15:alpha=1,fade=t=out:st={b - 0.15}:d=0.15:alpha=1[i{i}]")
        fc.append(f"[{last}][i{i}]overlay=x=(W-w)/2:y={y}-h/2:enable='between(t,{a},{b})'[v{i + 1}]")
        last = f"v{i + 1}"
    fc.append(f"[{last}]ass={ass}:fontsdir={FONT_DIR}[vout]")
    fc.append(f"[1:a]atempo={TEMPO},aresample=48000,highpass=f=70,"
              "acompressor=threshold=-18dB:ratio=3:attack=5:release=120,volume=1.6[voz]")
    fc.append("[2:a]volume=0.9[fx]")
    fc.append("[voz][fx]amix=inputs=2:duration=longest:normalize=0,"
              "alimiter=limit=0.95,loudnorm=I=-14:TP=-1.0:LRA=9[aout]")
    run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(fc),
         "-map", "[vout]", "-map", "[aout]", "-t", str(DUR), "-r", str(FPS),
         "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
         "-profile:v", "high", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-movflags", "+faststart", args.out])
    print("OK", args.out)


if __name__ == "__main__":
    main()
