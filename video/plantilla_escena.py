"""Plantilla de escena: mano anatómica real agarrando una regleta.

Punto de partida para los próximos vídeos. Copia este archivo, cambia el
bloque PLANO y renderiza.

Uso:
    python plantilla_escena.py --still 1 90 128 140      # fotogramas sueltos (borrador)
    python plantilla_escena.py --frames 1-240 --calidad final --out frames/
    python plantilla_escena.py --save escena.blend        # abrir luego en Blender

Requiere Blender como módulo de Python:  pip install bpy
"""
import argparse
import math
import os
import sys

import bpy
from mathutils import Matrix

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit import anatomia, animacion, escena, materiales  # noqa: E402

FPS = 24
FRAMES = 240

# ------------------------------------------------------------------ PLANO
DEDO = "anular"          # dedo protagonista (el que más se lesiona en escalada)
AGARRE = "arqueo"        # 'arqueo', 'semiarqueo' o 'extendido' (ver animacion.AGARRES)
ROTURA = True            # mostrar la rotura de la A2

F_PIEL = (20, 70)        # la piel se vuelve translúcida
F_AGARRE = (40, 88)      # la mano pasa de abierta al agarre
F_CARGA = (92, 128)      # carga: temblor y la A2 se ilumina
F_ROTURA = 130           # rotura
RALENTI = (124, 152, 3)  # tramo a cámara lenta y factor (None para quitarlo)


def construir():
    sc = escena.nueva_escena(FPS, FRAMES)

    # --- Anatomía
    mano = anatomia.cargar_mano()
    rig = anatomia.crear_rig(mano)
    poleas = anatomia.crear_poleas(mano, rig, DEDO)
    mats = materiales.aplicar_mano(mano, poleas)
    a2 = poleas["A2"]
    for ob in a2:
        ob.data.materials[0] = mats["polea_resaltada"][0]

    # Ocultar lo que solo estorba en este plano
    for nombre in ("Dorsal fascia of hand", "Palmar aponeurosis", "Common flexor tendon sheath",
                   "Superficial transverse metacarpal ligament"):
        if nombre in mano.obj:
            mano[nombre].hide_render = True

    # --- Orientación de escalada: dedos hacia arriba, palma hacia la pared (+Y)
    muneca = rig.arm.data.bones["mano"].head_local.copy()
    giro = Matrix.Translation(muneca) @ Matrix.Rotation(math.pi, 4, "X") @ Matrix.Translation(-muneca)
    rig.arm.matrix_world = giro @ rig.arm.matrix_world
    bpy.context.view_layer.update()

    # --- Animación de la mano
    abierta = {d: animacion.AGARRES["abierta"] for d in ("indice", "corazon", "anular", "menique")}
    agarre = {d: animacion.AGARRES[AGARRE] for d in ("indice", "corazon", "anular", "menique")}
    pulgar = {"P1": 25, "P3": 30}
    animacion.pose_mano(rig, abierta, 1)
    animacion.pose_mano(rig, abierta, F_AGARRE[0])
    animacion.pose_dedo(rig, "pulgar", {"P1": 0, "P3": 0}, F_AGARRE[0])
    animacion.pose_mano(rig, agarre, F_AGARRE[1])
    animacion.pose_dedo(rig, "pulgar", pulgar, F_AGARRE[1])
    animacion.pose_mano(rig, agarre, F_ROTURA)
    huesos_dedos = [f"{d}.{f}" for d in ("indice", "corazon", "anular", "menique") for f in ("P1", "P2")]
    animacion.temblor(rig, huesos_dedos, F_CARGA[0], F_ROTURA, grados=0.35)

    # --- Regleta colocada bajo las yemas en la pose final
    sc.frame_set(F_AGARRE[1] + 8)
    regleta, pared = _regleta(rig)
    sc.frame_set(1)

    # --- Piel translúcida y resalte de la A2
    op = mats["piel_opacidad"]
    for f, v in ((1, 1.0), (F_PIEL[0], 1.0), (F_PIEL[1], 0.12)):
        op.outputs[0].default_value = v
        op.outputs[0].keyframe_insert("default_value", frame=f)
    em = mats["polea_resaltada"][1].inputs["Emission Strength"]
    for f, v in ((F_CARGA[0], 0.0), (F_ROTURA - 1, 1.2), (F_ROTURA + 1, 5.0), (F_ROTURA + 24, 0.8)):
        em.default_value = v
        em.keyframe_insert("default_value", frame=f)

    # --- Rotura
    if ROTURA:
        animacion.romper_polea(a2, F_ROTURA, apertura=65)
        # cuerda de arco: el tendón se separa de la falange hacia la palma
        animacion.desplazar(anatomia.objetos_flexores(mano), rig, f"{DEDO}.P1", (0, 0, -1),
                            F_ROTURA, 0.0035, desde=0.05, hasta=0.95, nombre="Cuerda")
        # y abomba la piel por encima
        animacion.desplazar([mano.piel], rig, f"{DEDO}.P1", (0, 0, -1), F_ROTURA + 1, 0.0022,
                            desde=0.1, hasta=0.9, radio=0.01, nombre="Bulto")
        # el dedo pierde el apoyo y se abre (el escalador suelta)
        semi = animacion.AGARRES["semiarqueo"]
        animacion.pose_dedo(rig, DEDO, animacion.AGARRES[AGARRE], F_ROTURA + 1, desfase=0)
        animacion.pose_dedo(rig, DEDO, semi, F_ROTURA + 7, desfase=1)

    # --- Luces y cámara
    # objetivo: centro de la falange proximal (la A2) con el agarre ya hecho
    sc.frame_set(F_AGARRE[1] + 8)
    centro = (rig.matriz_hueso(f"{DEDO}.P1").translation
              + rig.matriz_hueso(f"{DEDO}.P2").translation) / 2
    sc.frame_set(1)
    escena.mundo_estudio(sc)
    escena.luces_estudio(centro, distancia=0.5, intensidad=0.3)

    # giro: 0 = desde detrás de la mano (dorso), +90 = desde el lado del meñique
    # en macro la profundidad de campo es de milímetros: f/11-f/16 como en fotografía real
    cam = escena.Camara(centro, distancia=0.32, lente=85, fstop=16.0)
    cam.clave(1, giro=35, inclinacion=12, distancia=0.45, objetivo=centro)
    cam.clave(F_AGARRE[0], giro=48, inclinacion=14, distancia=0.38)
    # al cargar, la cámara gira hacia el lado del meñique y baja un poco para
    # ver la cara palmar, donde están las poleas
    cam.clave(F_AGARRE[1], giro=82, inclinacion=6, distancia=0.32)
    cam.clave(F_ROTURA - 6, giro=96, inclinacion=-4, distancia=0.25)
    cam.clave(FRAMES, giro=102, inclinacion=-7, distancia=0.23)
    cam.apertura(F_AGARRE[1], 16.0)
    cam.apertura(F_ROTURA - 6, 11.0)
    cam.en_mano(intensidad=1.0)
    if ROTURA:
        cam.sacudir(F_ROTURA, fuerza=0.6)

    animacion.suavizar()
    if RALENTI:
        animacion.ralenti(*RALENTI)

    escena.configurar_render(sc, "borrador")
    escena.postproduccion(sc)
    return sc


def _regleta(rig, profundidad=0.02, grosor=0.03):
    """Regleta de madera de 'profundidad' metros justo bajo las yemas."""
    yemas, dips = [], []
    for d in ("indice", "corazon", "anular", "menique"):
        m = rig.matriz_hueso(f"{d}.P3")
        largo = rig.arm.data.bones[f"{d}.P3"].length
        palmar = -(m.to_3x3().col[2]).normalized()
        yemas.append(m.translation + m.to_3x3().col[1].normalized() * largo * 0.55 + palmar * 0.0065)
        dips.append(m.translation)
    z = sum(v.z for v in yemas) / len(yemas)
    canto = min(v.y for v in yemas) - 0.004
    x0, x1 = min(v.x for v in dips) - 0.02, max(v.x for v in dips) + 0.02

    bpy.ops.mesh.primitive_cube_add(size=1)
    reg = bpy.context.active_object
    reg.name = "Regleta"
    reg.scale = (x1 - x0 + 0.06, profundidad, grosor)
    reg.location = ((x0 + x1) / 2, canto + profundidad / 2, z - grosor / 2)
    bv = reg.modifiers.new("Canto", "BEVEL")
    bv.width = 0.004
    bv.segments = 6
    bv.limit_method = "ANGLE"
    reg.data.materials.append(materiales.madera())
    for p in reg.data.polygons:
        p.use_smooth = True

    bpy.ops.mesh.primitive_plane_add(size=2)
    pared = bpy.context.active_object
    pared.name = "Pared"
    pared.rotation_euler = (math.radians(90), 0, 0)
    pared.location = ((x0 + x1) / 2, canto + profundidad, z)
    pared.data.materials.append(materiales.mate("Pared", (0.035, 0.04, 0.05), 0.85))
    return reg, pared


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="frames")
    ap.add_argument("--calidad", default="borrador", choices=("borrador", "final"))
    ap.add_argument("--samples", type=int, default=None)
    ap.add_argument("--res", type=int, default=None, help="porcentaje de resolución")
    ap.add_argument("--frames", default=None, help="rango, p. ej. 1-240")
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
