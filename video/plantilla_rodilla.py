"""Plantilla de escena: rodilla del corredor (síndrome de la cintilla iliotibial).

La pierna derecha corre en el sitio a cámara lenta. Vista lateral: la piel se
vuelve translúcida, la cintilla iliotibial se resalta y, en cada apoyo, cuando
la rodilla pasa por 20–30° de flexión, la cintilla comprime la zona del
epicóndilo femoral lateral, que se enciende.

Uso:
    python plantilla_rodilla.py --still 1 90 170 --out pruebas/      # borrador
    python plantilla_rodilla.py --frames 1-300 --calidad final --out frames/
    python plantilla_rodilla.py --save escena.blend

Requiere Blender como módulo de Python:  pip install bpy==5.2.3
"""
import argparse
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit import anatomia, animacion, escena, materiales  # noqa: E402

FPS = 24

# ------------------------------------------------------------------ PLANO
F_PIEL = (30, 80)          # la piel se vuelve translúcida
F_CINTILLA = (70, 100)     # la cintilla iliotibial se ilumina de arriba abajo
F_CARRERA = 100            # empieza a correr
CICLOS = 4                 # zancadas
FRAMES_POR_CICLO = 48      # 16 = tiempo real (180 pasos/min); 48 = ralentí x3
FRAMES = F_CARRERA + CICLOS * FRAMES_POR_CICLO + 24


def construir():
    sc = escena.nueva_escena(FPS, FRAMES)

    # --- Anatomía
    pierna = anatomia.cargar_pierna()
    rig = anatomia.crear_rig_pierna(pierna)
    # los vastos y el bíceps femoral también se aclaran para que se vea la cintilla
    mats = materiales.aplicar_auto(pierna, translucidos=("Vastus lateralis", "biceps femoris"))
    # fascias que envuelven todo, bursas lejanas: fuera de este plano
    pierna.ocultar("Fascia lata", "Crural fascia", "Sciatic bursa", "Trochanteric bursa")

    # La cintilla, con material propio para poder resaltarla
    cintilla_mat, cintilla_bsdf = materiales.ligamento("Cintilla iliotibial", resalte=(1.0, 0.45, 0.15))
    pierna["Iliotibial tract"].data.materials[0] = cintilla_mat

    # Zona de roce sobre el epicóndilo lateral (sigue al fémur)
    epi = pierna.epicondilo_lateral()
    zona_mat, zona_bsdf = materiales.resalte("Zona de roce")
    anatomia.zona("Zona_roce", epi + Vector((-0.004, 0, 0)), (0.007, 0.016, 0.02),
                  "muslo", rig, zona_mat)

    # --- Postura de partida: de pie, rodilla casi recta
    rig.flexion("muslo", 5, frame=1)
    rig.flexion("pierna", 8, frame=1)
    rig.flexion("muslo", 5, frame=F_CARRERA - 12)
    rig.flexion("pierna", 8, frame=F_CARRERA - 12)
    rig.flexion("muslo", 32, frame=F_CARRERA)
    rig.flexion("pierna", 20, frame=F_CARRERA)

    # --- Carrera
    apoyos = animacion.ciclo_carrera(rig, F_CARRERA, CICLOS, FRAMES_POR_CICLO)
    # Pinzamiento: solo al principio del apoyo (0–25 % del ciclo), que es cuando
    # la cintilla está cargada
    tramos = [t for t in animacion.tramos_en_rango(rig, F_CARRERA, FRAMES, *animacion.PINZAMIENTO_ITB)
              if any(a <= t[0] <= a + 0.25 * FRAMES_POR_CICLO for a in apoyos)]
    animacion.pulsos(zona_bsdf.inputs["Emission Strength"], tramos, base=0.0, pico=6.0)
    for f, a in ((1, 0.0), (F_CARRERA - 8, 0.0), (F_CARRERA, 0.25)):
        zona_bsdf.inputs["Alpha"].default_value = a
        zona_bsdf.inputs["Alpha"].keyframe_insert("default_value", frame=f)

    # --- Piel, músculos y cintilla
    for clave, final in (("piel_opacidad", 0.06), ("opacidad_Vastus lateralis", 0.35),
                         ("opacidad_biceps femoris", 0.35)):
        if clave not in mats:
            continue
        op = mats[clave].outputs[0]
        for f, v in ((1, 1.0), (F_PIEL[0], 1.0), (F_PIEL[1], final)):
            op.default_value = v
            op.keyframe_insert("default_value", frame=f)
    em = cintilla_bsdf.inputs["Emission Strength"]
    for f, v in ((1, 0.0), (F_CINTILLA[0], 0.0), (F_CINTILLA[1], 0.8), (FRAMES, 0.6)):
        em.default_value = v
        em.keyframe_insert("default_value", frame=f)

    # --- Luces y cámara (giro -90 = lado externo de la pierna derecha)
    rodilla = pierna.centro_rodilla()
    escena.mundo_estudio(sc)
    escena.luces_estudio(rodilla, distancia=1.0, intensidad=0.2)

    cam = escena.Camara(rodilla, distancia=1.2, lente=50, fstop=8.0)
    cam.clave(1, giro=-70, inclinacion=6, distancia=1.0, objetivo=rodilla + Vector((0, 0, 0.08)))
    cam.clave(F_PIEL[1], giro=-82, inclinacion=4, distancia=1.0)
    cam.clave(F_CARRERA, giro=-90, inclinacion=2, distancia=0.75,
              objetivo=rodilla + Vector((0, 0, 0.06)))
    cam.clave(F_CARRERA + 2 * FRAMES_POR_CICLO, giro=-96, inclinacion=0, distancia=0.45,
              objetivo=rodilla + Vector((0, 0, 0.02)))
    cam.clave(FRAMES, giro=-100, inclinacion=-2, distancia=0.40)
    cam.apertura(F_CARRERA, 8.0)
    cam.apertura(F_CARRERA + 2 * FRAMES_POR_CICLO, 5.6)
    cam.en_mano(intensidad=2.0)
    # acompaña a la rodilla (cabeza del hueso 'pierna') mientras corre
    cam.seguir(rig.arm, "pierna", influencia=0.7)

    animacion.suavizar()
    escena.configurar_render(sc, "borrador")
    escena.postproduccion(sc)
    return sc


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="frames")
    ap.add_argument("--calidad", default="borrador", choices=("borrador", "final"))
    ap.add_argument("--samples", type=int, default=None)
    ap.add_argument("--res", type=int, default=None, help="porcentaje de resolución")
    ap.add_argument("--frames", default=None, help="rango, p. ej. 1-300")
    ap.add_argument("--still", type=int, nargs="*", default=None)
    ap.add_argument("--save", default=None, help="guardar .blend")
    a = ap.parse_args(argv)

    sc = construir()
    escena.configurar_render(sc, a.calidad)
    if a.samples:
        sc.cycles.samples = a.samples
    if a.res:
        sc.render.resolution_percentage = a.res
    os.makedirs(a.out, exist_ok=True)
    if a.save:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(a.save))
    if a.still:
        for f in a.still:
            sc.frame_set(f)
            sc.render.filepath = os.path.join(os.path.abspath(a.out), f"still_{f:04d}.png")
            bpy.ops.render.render(write_still=True)
        return
    if a.frames:
        s, e = a.frames.split("-")
        sc.frame_start, sc.frame_end = int(s), int(e)
    sc.render.filepath = os.path.join(os.path.abspath(a.out), "f_")
    bpy.ops.render.render(animation=True)


if __name__ == "__main__":
    main()
