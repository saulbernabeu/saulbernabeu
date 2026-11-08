"""Herramientas de animación para movimientos creíbles.

- pose_dedo():    flexiona un dedo con desfase entre articulaciones (acción superpuesta).
- muelle():       oscilación amortiguada (rebotes que se apagan), para golpes y roturas.
- ruido():        temblor o deriva aleatoria suave en un canal (esfuerzo, cámara en mano).
- romper_polea(): rotura de una polea partida en dos mitades, con desgarro de fibras.
- desplazar():    deforma un tramo (cuerda de arco del tendón, abombamiento de la piel).
- ralenti():      estira un tramo de tiempo para hacer cámara lenta.
"""
import math
import random

import bpy
import numpy as np
from mathutils import Vector

try:
    from bpy_extras.anim_utils import action_get_channelbag_for_slot
except ImportError:          # Blender < 4.4
    action_get_channelbag_for_slot = None


# ---------------------------------------------------------------- curvas

def fcurve(dato, ruta, indice=0):
    """Devuelve la F-Curve de un canal (compatible con las acciones por capas de Blender 4.4+).

    'dato' puede ser un objeto o una parte de él (hueso de pose, shape key...).
    """
    id_data = dato.id_data
    if dato != id_data:
        ruta = dato.path_from_id(ruta)
    ad = id_data.animation_data
    if not ad or not ad.action:
        return None
    act = ad.action
    if action_get_channelbag_for_slot and getattr(ad, "action_slot", None):
        cb = action_get_channelbag_for_slot(act, ad.action_slot)
        curvas = cb.fcurves if cb else []
    else:
        curvas = act.fcurves
    for fc in curvas:
        if fc.data_path == ruta and fc.array_index == indice:
            return fc
    return None


def todas_las_fcurves():
    for act in bpy.data.actions:
        if hasattr(act, "layers") and act.layers:
            for capa in act.layers:
                for tira in capa.strips:
                    for cb in tira.channelbags:
                        yield from cb.fcurves
        else:
            yield from getattr(act, "fcurves", [])


def _valor(id_data, ruta, indice):
    v = id_data.path_resolve(ruta)
    try:
        return v[indice]
    except TypeError:
        return v


def _poner(id_data, ruta, indice, valor, frame):
    actual = id_data.path_resolve(ruta)
    if hasattr(actual, "__len__"):
        actual[indice] = valor
        id_data.keyframe_insert(ruta, index=indice, frame=frame)
    else:
        setattr(id_data, ruta, valor)
        id_data.keyframe_insert(ruta, frame=frame)


# ---------------------------------------------------------------- poses

def pose_dedo(rig, dedo, angulos, frame, desfase=2, base=None):
    """Clave de flexión de un dedo (grados, + = hacia la palma).

    angulos: {'P1': 20, 'P2': 100, 'P3': -25}  (opcional 'MC', 'abd' para separar)
    desfase: fotogramas de retraso entre una articulación y la siguiente; con
             dos claves (inicio y fin) cada articulación arranca y llega un poco
             después que la anterior, como en un dedo real.
    """
    for i, (fal, ang) in enumerate(angulos.items()):
        if fal == "abd":
            continue
        pb = rig.pb(f"{dedo}.{fal}")
        abd = math.radians(angulos.get("abd", 0)) if fal == "P1" else pb.rotation_euler[2]
        pb.rotation_euler = (rig.signo * math.radians(ang), 0, abd)
        pb.keyframe_insert("rotation_euler", frame=frame + i * desfase)


def pose_mano(rig, poses, frame, desfase_dedos=1, desfase=2):
    """Aplica varias poses de dedo con un pequeño desfase entre dedos."""
    for k, (dedo, ang) in enumerate(poses.items()):
        pose_dedo(rig, dedo, ang, frame + k * desfase_dedos, desfase)


# Poses de agarre de referencia (grados respecto a la mano relajada de Z-Anatomy)
AGARRES = {
    "relajada": {"P1": 0, "P2": 0, "P3": 0},
    "abierta": {"P1": -25, "P2": -25, "P3": -10},
    "extendido": {"P1": 15, "P2": 25, "P3": 35},        # dedos casi rectos, colgado
    "semiarqueo": {"P1": 10, "P2": 70, "P3": 15},
    "arqueo": {"P1": 0, "P2": 95, "P3": -30},           # DIP en hiperextensión
}


# ---------------------------------------------------------------- dinámica

def muelle(id_data, ruta, indice, frame, desde, hasta, frecuencia=6.0, amortiguacion=0.3,
           duracion=None, fps=None):
    """Oscilación amortiguada desde 'desde' hasta 'hasta' a partir de 'frame'.

    frecuencia en Hz; amortiguacion entre 0 (rebota sin parar) y 1 (sin rebote).
    Inserta una clave por fotograma hasta que la oscilación se apaga.
    """
    fps = fps or bpy.context.scene.render.fps
    w = 2 * math.pi * frecuencia
    z = amortiguacion
    wd = w * math.sqrt(max(1e-6, 1 - z * z))
    if duracion is None:
        duracion = int(math.ceil(4.6 / (z * w) * fps)) + 1
    for k in range(duracion + 1):
        t = k / fps
        v = hasta + (desde - hasta) * math.exp(-z * w * t) * math.cos(wd * t)
        _poner(id_data, ruta, indice, v, frame + k)
    fc = fcurve(id_data, ruta, indice)
    if fc:
        for kp in fc.keyframe_points:
            if frame <= kp.co.x <= frame + duracion:
                kp.interpolation = "BEZIER"
                kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"


def ruido(id_data, ruta, indice, amplitud, periodo=20, desde=None, hasta=None, fundido=8,
          semilla=0):
    """Añade un modificador de ruido a un canal (necesita al menos una clave).

    amplitud en las unidades del canal (radianes para rotaciones), periodo en
    fotogramas. desde/hasta limitan el efecto a un tramo con fundidos suaves.
    """
    fc = fcurve(id_data, ruta, indice)
    if fc is None:
        id_data.keyframe_insert(ruta, index=indice, frame=bpy.context.scene.frame_start)
        fc = fcurve(id_data, ruta, indice)
    mod = fc.modifiers.new("NOISE")
    mod.scale = periodo
    mod.strength = amplitud * 2
    mod.phase = semilla * 13.7
    mod.offset = semilla * 101
    mod.blend_type = "ADD"
    if desde is not None and hasta is not None:
        mod.use_restricted_range = True
        mod.frame_start, mod.frame_end = desde, hasta
        mod.blend_in = mod.blend_out = fundido
    return mod


def temblor(rig, huesos, desde, hasta, grados=0.4, periodo=3):
    """Temblor fino de esfuerzo (dedos apretando al máximo)."""
    for i, h in enumerate(huesos):
        ruido(rig.pb(h), "rotation_euler", 0, math.radians(grados), periodo, desde, hasta,
              semilla=i + 1)
        ruido(rig.pb(h), "rotation_euler", 0, math.radians(grados * 0.5), periodo * 5, desde,
              hasta, semilla=i + 50)


def suavizar(easing="AUTO"):
    """Interpolación Bézier en todas las claves que no la tengan."""
    for fc in todas_las_fcurves():
        for kp in fc.keyframe_points:
            if kp.interpolation == "CONSTANT":
                continue
            kp.interpolation = "BEZIER"


def ralenti(desde, hasta, factor=3.0):
    """Cámara lenta: estira el tramo [desde, hasta] 'factor' veces.

    Llamar al final, cuando ya está toda la animación. Mueve las claves y los
    rangos de los modificadores, y alarga la escena.
    """
    extra = (hasta - desde) * (factor - 1)

    def f(x):
        if x <= desde:
            return x
        if x <= hasta:
            return desde + (x - desde) * factor
        return x + extra

    for fc in todas_las_fcurves():
        for kp in fc.keyframe_points:
            x0 = kp.co.x
            nx = f(x0)
            kp.co.x = nx
            kp.handle_left.x = nx + (kp.handle_left.x - x0) * (factor if desde < x0 <= hasta else 1)
            kp.handle_right.x = nx + (kp.handle_right.x - x0) * (factor if desde <= x0 < hasta else 1)
        for m in fc.modifiers:
            if m.use_restricted_range:
                m.frame_start, m.frame_end = f(m.frame_start), f(m.frame_end)
        fc.update()
    sc = bpy.context.scene
    sc.frame_end = int(f(sc.frame_end))


# ---------------------------------------------------------------- lesiones

def romper_polea(mitades, frame, apertura=70, desgarro=1.0, semilla=0):
    """Rotura de una polea creada en dos mitades (anatomia.crear_poleas(partida=...)).

    Cada mitad gira hacia fuera sobre su anclaje con rebote amortiguado y su
    borde libre se deshilacha (shape key 'Desgarro').
    """
    rnd = random.Random(semilla)
    izq, der = mitades
    for ob, sgn in ((izq, -1), (der, 1)):
        _deshilachar(ob, sgn, rnd)
        ob.rotation_mode = "XYZ"
        base = ob.rotation_euler[1]
        ob.keyframe_insert("rotation_euler", index=1, frame=frame)
        objetivo = base + sgn * math.radians(apertura * rnd.uniform(0.85, 1.0))
        muelle(ob, "rotation_euler", 1, frame, base, objetivo, frecuencia=rnd.uniform(4, 6),
               amortiguacion=0.28)
        k = ob.data.shape_keys.key_blocks["Desgarro"]
        k.value = 0
        k.keyframe_insert("value", frame=frame - 1)
        k.value = desgarro
        k.keyframe_insert("value", frame=frame + 2)


def _deshilachar(ob, sgn, rnd):
    """Shape key con el borde libre roto en flecos irregulares."""
    me = ob.data
    if not me.shape_keys:
        ob.shape_key_add(name="Basis")
    sk = ob.shape_key_add(name="Desgarro")
    co = np.array([v.co[:] for v in me.vertices])
    # el borde libre es el más alejado del origen (anclaje) en el plano XZ
    r = np.hypot(co[:, 0], co[:, 2])
    rmax = r.max()
    ys = co[:, 1]
    flecos = {}
    for i, v in enumerate(me.vertices):
        cerca = (r[i] / rmax) ** 3
        clave = round(ys[i] * 2000)
        if clave not in flecos:
            flecos[clave] = rnd.uniform(0.2, 1.0)
        f = flecos[clave] * cerca
        d = Vector((co[i, 0], 0, co[i, 2]))
        d = d.normalized() if d.length else Vector((0, 0, 1))
        # se encoge (fibras rotas de longitudes distintas) y se riza un poco
        sk.data[i].co = v.co - d * f * 0.35 * rmax + Vector((0, rnd.uniform(-1, 1) * 0.0004, 0)) * cerca
    return sk


def desplazar(objetos, rig, hueso, direccion_local, frame, cantidad, desde=0.15, hasta=0.85,
              lado=-1, radio=0.008, frecuencia=7.0, amortiguacion=0.3, nombre="Desplazar"):
    """Desplaza un tramo de varios objetos siguiendo al hueso, con rebote.

    Sirve para la 'cuerda de arco' (el tendón se separa del hueso al romperse
    la polea) y para el abombamiento de la piel. direccion_local es un vector
    en el marco del hueso (Y = eje, Z = dorsal); (0, 0, -1) = hacia la palma.
    Devuelve el empty que mueve el tramo.
    """
    from . import anatomia
    m = anatomia._marco_reposo(rig, hueso)
    e = bpy.data.objects.new(f"{nombre}_{hueso}", None)
    e.empty_display_size = 0.005
    bpy.context.scene.collection.objects.link(e)
    e.matrix_world = m
    e.parent = rig.arm
    e.matrix_parent_inverse = rig.arm.matrix_world.inverted()
    for ob in objetos:
        g, _ = anatomia.grupo_tramo(ob, rig, hueso, desde, hasta, lado, nombre=f"{nombre}_{hueso}",
                                    radio=radio)
        h = ob.modifiers.new(f"{nombre}_{hueso}", "HOOK")
        h.object = e
        h.vertex_group = g.name
        h.falloff_type = "NONE"
        # matriz inversa: el hook no mueve nada hasta que el empty se desplaza
        h.matrix_inverse = (ob.matrix_world.inverted() @ e.matrix_world).inverted()
        ob.modifiers.move(ob.modifiers.find(h.name), 0)   # antes del esqueleto (espacio de reposo)
    # desplazamiento expresado en el espacio del rig (el padre del empty)
    d = (rig.arm.matrix_world.to_3x3().inverted() @ m.to_3x3() @ Vector(direccion_local))
    d = d.normalized() * cantidad
    base = e.location.copy()
    for i in range(3):
        e.keyframe_insert("location", index=i, frame=frame)
        muelle(e, "location", i, frame, base[i], base[i] + d[i], frecuencia, amortiguacion)
    return e
