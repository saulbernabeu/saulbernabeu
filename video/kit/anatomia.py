"""Anatomía de Z-Anatomy: carga de regiones, rigs y estructuras generadas.

Mano:
    mano = anatomia.cargar_mano()
    rig = anatomia.crear_rig(mano)
    poleas = anatomia.crear_poleas(mano, rig, "anular")
Pierna (rodilla):
    pierna = anatomia.cargar_pierna()
    rig = anatomia.crear_rig_pierna(pierna)
    pierna.epicondilo_lateral()        # punto donde roza la cintilla iliotibial
"""
import math
import os

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
ASSET = os.path.join(ASSETS, "mano_derecha.blend")
ASSET_PIERNA = os.path.join(ASSETS, "pierna_derecha.blend")
COLECCIONES = ("Huesos", "Articulaciones", "Musculos_tendones", "Piel")

# nombre en castellano -> ordinal usado por Z-Anatomy
DEDOS = {"pulgar": "first", "indice": "second", "corazon": "third",
         "anular": "fourth", "menique": "fifth"}

# Tejidos blandos que se deforman con el esqueleto
FLEXORES = ("Flexor digitorum profundus", "Humero-ulnar head of flexor digitorum superficialis",
            "Synovial sheaths of digits of hand")

# Poleas anulares: falange a la que se anclan y tramo que ocupan
# (fracción de la longitud de esa falange; negativo = antes de la articulación)
POLEAS = {
    "A1": ("P1", -0.10, 0.12),
    "A2": ("P1", 0.16, 0.62),
    "A3": ("P2", -0.07, 0.07),
    "A4": ("P2", 0.30, 0.68),
    "A5": ("P3", -0.06, 0.10),
}


class Region:
    """Objetos de una región del cuerpo agrupados por colección."""

    def __init__(self, objetos):
        self.obj = objetos                      # nombre (en inglés) -> objeto
        self.piel = objetos.get("Piel")

    def __getitem__(self, nombre):
        return self.obj[nombre]

    def __contains__(self, nombre):
        return nombre in self.obj

    def coleccion(self, nombre):
        if nombre not in bpy.data.collections:
            return []
        return [o for o in bpy.data.collections[nombre].objects]

    def buscar(self, texto):
        """Objetos cuyo nombre contiene 'texto' (sin distinguir mayúsculas)."""
        t = texto.lower()
        return [o for n, o in self.obj.items() if t in n.lower()]

    def ocultar(self, *textos):
        """Oculta en el render los objetos cuyo nombre contiene alguno de los textos."""
        for t in textos:
            for o in self.buscar(t):
                o.hide_render = True


class Mano(Region):
    """Mano derecha."""

    def hueso(self, dedo, falange):
        """Malla de un hueso: falange 'MC', 'P1', 'P2' o 'P3'."""
        o = DEDOS[dedo]
        if falange == "MC":
            return self.obj[f"{o.capitalize()} metacarpal bone"]
        if dedo == "pulgar" and falange == "P2":
            falange = "P3"   # el pulgar no tiene falange media
        nombre = {"P1": "Proximal", "P2": "Middle", "P3": "Distal"}[falange]
        return self.obj[f"{nombre} phalanx of {o} finger of hand"]

    def falanges(self, dedo):
        return ["MC", "P1", "P3"] if dedo == "pulgar" else ["MC", "P1", "P2", "P3"]


# ---------------------------------------------------------------- carga

def cargar_mano(ruta=ASSET, colecciones=COLECCIONES, unir_piel=True):
    """Añade la mano a la escena actual y devuelve un objeto Mano."""
    return Mano(cargar(ruta, colecciones, unir_piel, voxel=0.0007))


def cargar_pierna(ruta=ASSET_PIERNA, colecciones=COLECCIONES, unir_piel=True):
    """Añade la pierna derecha (cadera a tobillo) y devuelve un objeto Pierna.

    Los tendones que siguen hacia el pie (que no está incluido) se recortan a
    la altura del tobillo.
    """
    p = Pierna(cargar(ruta, colecciones, unir_piel, voxel=0.0018))
    if "Tibia" in p:
        z = p.tobillo().z + 0.015
        for ob in p.coleccion("Musculos_tendones"):
            recortar_debajo(ob, z)
    return p


def recortar_debajo(ob, z):
    """Borra la geometría de un objeto por debajo de la altura z (mundo)."""
    mw = ob.matrix_world
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    fuera = [v for v in bm.verts if (mw @ v.co).z < z]
    if fuera:
        bmesh.ops.delete(bm, geom=fuera, context="VERTS")
        bm.to_mesh(ob.data)
    bm.free()


def cargar(ruta, colecciones=COLECCIONES, unir_piel=True, voxel=0.001):
    """Carga cualquier asset de video/assets y devuelve {nombre: objeto}.

    voxel: tamaño (m) del remallado que funde los parches de piel; más pequeño
    = más detalle y más vértices.
    """
    with bpy.data.libraries.load(ruta, link=False) as (src, dst):
        dst.collections = [c for c in src.collections if c in colecciones]
    objetos = {}
    for col in dst.collections:
        bpy.context.scene.collection.children.link(col)
        for ob in col.objects:
            objetos[ob.name] = ob
            for p in ob.data.polygons:
                p.use_smooth = True
    if unir_piel and "Piel" in colecciones:
        objetos = _unir_piel(objetos, voxel)
    return objetos


def _unir_piel(objetos, voxel):
    partes = [o for o in bpy.data.collections["Piel"].objects]
    nombres = [o.name for o in partes]
    bpy.ops.object.select_all(action="DESELECT")
    for o in partes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = partes[0]
    bpy.ops.object.join()
    piel = bpy.context.active_object
    piel.name = "Piel"
    # Los parches (dorso, palma, dedos) son volúmenes cerrados que se solapan:
    # un remallado por vóxeles los funde en una sola superficie sin costuras.
    rm = piel.modifiers.new("Fundir", "REMESH")
    rm.mode = "VOXEL"
    rm.voxel_size = voxel
    rm.adaptivity = 0.0
    sm = piel.modifiers.new("Suavizar", "CORRECTIVE_SMOOTH")
    sm.iterations = 2
    sm.smooth_type = "LENGTH_WEIGHTED"
    sm.use_only_smooth = True
    bpy.ops.object.modifier_apply(modifier=rm.name)
    bpy.ops.object.modifier_apply(modifier=sm.name)
    for p in piel.data.polygons:
        p.use_smooth = True
    sub = piel.modifiers.new("Subsurf", "SUBSURF")
    sub.levels, sub.render_levels = 0, 1
    for n in nombres:
        objetos.pop(n, None)
    objetos["Piel"] = piel
    return objetos


# ---------------------------------------------------------------- geometría

def _verts_mundo(ob):
    n = len(ob.data.vertices)
    co = np.empty(n * 3)
    ob.data.vertices.foreach_get("co", co)
    co = co.reshape(n, 3)
    m = np.array(ob.matrix_world)
    return co @ m[:3, :3].T + m[:3, 3]


def _eje(ob, hacia):
    """Extremos (proximal, distal) del eje principal de un hueso.

    'hacia' es un punto distal de referencia para orientar el eje.
    """
    v = _verts_mundo(ob)
    c = v.mean(axis=0)
    _, _, vt = np.linalg.svd(v - c, full_matrices=False)
    d = vt[0]
    if np.dot(np.array(hacia) - c, d) < 0:
        d = -d
    t = (v - c) @ d
    return Vector(c + d * t.min()), Vector(c + d * t.max())


def _centro(ob):
    return Vector(_verts_mundo(ob).mean(axis=0))


# ---------------------------------------------------------------- rig

class Rig:
    def __init__(self, arm, dorsal, signo_flexion, signos=None):
        self.arm = arm
        self.dorsal = dorsal
        self.signo = signo_flexion   # signo de la rotación X que flexiona (mano)
        self.signos = signos or {}   # signo por hueso (pierna: 'muslo', 'pierna')

    def flexion(self, hueso, grados, frame=None):
        """Flexiona un hueso (grados, + = flexión anatómica) y opcionalmente pone clave."""
        pb = self.pb(hueso)
        s = self.signos.get(hueso, self.signo)
        pb.rotation_euler[0] = s * math.radians(grados)
        if frame is not None:
            pb.keyframe_insert("rotation_euler", index=0, frame=frame)

    def pb(self, nombre):
        return self.arm.pose.bones[nombre]

    def matriz_hueso(self, nombre):
        """Matriz mundial (posada) de un hueso del rig."""
        return self.arm.matrix_world @ self.pb(nombre).matrix


def crear_rig(mano, deformar=True):
    """Crea un esqueleto a partir de las mallas de hueso reales.

    Huesos del rig: 'antebrazo', 'mano' y '<dedo>.MC/P1/P2/P3'.
    Las mallas óseas se emparentan rígidamente; tendones, vainas, ligamentos y
    piel se deforman con pesos calculados por cercanía a cada segmento.
    """
    mun = _centro(mano["Capitate bone"])
    tercer_mc = mano.hueso("corazon", "MC")
    punta_ref = _eje(tercer_mc, _centro(mano.hueso("corazon", "P3")))[1]
    antebrazo = (_centro(mano["Radius"]) + _centro(mano["Ulna"])) / 2

    dorsal = (_centro(mano["Dorsal fascia of hand"]) - _centro(mano["Palmar aponeurosis"])) \
        if "Dorsal fascia of hand" in mano.obj else Vector((0, 1, 0))
    dorsal.normalize()
    radial = (_centro(mano.hueso("indice", "MC")) - _centro(mano.hueso("menique", "MC"))).normalized()

    arm_d = bpy.data.armatures.new("Rig_mano")
    arm = bpy.data.objects.new("Rig_mano", arm_d)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm_d.edit_bones

    b = eb.new("antebrazo")
    b.head, b.tail = antebrazo, mun
    b.align_roll(dorsal)
    b = eb.new("mano")
    b.head, b.tail = mun, punta_ref
    b.align_roll(dorsal)
    b.parent = eb["antebrazo"]

    puntos = {}
    for dedo in DEDOS:
        fal = mano.falanges(dedo)
        tip_ref = _centro(mano.hueso(dedo, "P3")) + (_centro(mano.hueso(dedo, "P3")) - mun) * 0.2
        ejes = [_eje(mano.hueso(dedo, f), tip_ref) for f in fal]
        # articulaciones: punto medio entre el extremo distal de un hueso y el proximal del siguiente
        juntas = [ejes[0][0]]
        for (_, d0), (p1, _) in zip(ejes, ejes[1:]):
            juntas.append((d0 + p1) / 2)
        juntas.append(ejes[-1][1])
        dors = dorsal if dedo != "pulgar" else (dorsal + radial).normalized()
        padre = eb["mano"]
        for i, f in enumerate(fal):
            b = eb.new(f"{dedo}.{f}")
            b.head, b.tail = juntas[i], juntas[i + 1]
            b.align_roll(dors)
            b.parent = padre
            b.use_connect = i > 0
            padre = b
        puntos[dedo] = juntas
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"

    # ¿qué signo de rotación X lleva la punta hacia la palma?
    pb = arm.pose.bones["corazon.P1"]
    antes = (arm.matrix_world @ pb.tail).copy()
    pb.rotation_euler = (math.radians(30), 0, 0)
    bpy.context.view_layer.update()
    despues = arm.matrix_world @ pb.tail
    pb.rotation_euler = (0, 0, 0)
    bpy.context.view_layer.update()
    signo = 1.0 if (despues - antes).dot(dorsal) < 0 else -1.0
    rig = Rig(arm, dorsal, signo)

    # mallas óseas: rígidas
    for dedo in DEDOS:
        for f in mano.falanges(dedo):
            _emparentar(mano.hueso(dedo, f), arm, f"{dedo}.{f}")
    for nombre in ("Radius", "Ulna"):
        if nombre in mano.obj:
            _emparentar(mano[nombre], arm, "antebrazo")
    for ob in mano.coleccion("Huesos"):
        if ob.parent is None:
            _emparentar(ob, arm, "mano")

    if deformar:
        blandos = [o for c in ("Articulaciones", "Musculos_tendones") if c in bpy.data.collections
                   for o in mano.coleccion(c)]
        if mano.piel:
            blandos.append(mano.piel)
        for ob in blandos:
            pesos_por_cercania(ob, rig)
            # emparentado al rig para que, si se mueve o gira la mano entera, la siga
            mundo = ob.matrix_world.copy()
            ob.parent = arm
            ob.matrix_parent_inverse = arm.matrix_world.inverted()
            ob.matrix_world = mundo
    return rig


def _emparentar(ob, arm, hueso):
    mundo = ob.matrix_world.copy()
    ob.parent = arm
    ob.parent_type = "BONE"
    ob.parent_bone = hueso
    bpy.context.view_layer.update()
    ob.matrix_world = mundo


def pesos_por_cercania(ob, rig, suavidad=0.0025, huesos=None):
    """Pesa cada vértice según su distancia a los segmentos del esqueleto.

    'suavidad' (metros) controla lo ancha que es la transición en las
    articulaciones. 'huesos' limita qué huesos del rig deforman (todos si None).
    """
    arm = rig.arm
    lista = [b for b in arm.data.bones if huesos is None or b.name in huesos]
    nombres = [b.name for b in lista]
    mw = arm.matrix_world
    a = np.array([tuple(mw @ b.head_local) for b in lista])
    b = np.array([tuple(mw @ b.tail_local) for b in lista])
    v = _verts_mundo(ob)
    ab = b - a
    L = np.linalg.norm(ab, axis=1)
    t_libre = np.einsum("nbk,bk->nb", v[:, None, :] - a[None], ab) / (L ** 2)
    t = np.clip(t_libre, 0, 1)
    p = a[None] + t[..., None] * ab[None]
    # lo que sobresale más allá de los extremos del hueso cuenta el triple: así un
    # tendón que pasa por delante de una articulación sigue al hueso correcto en
    # vez de cortar la esquina
    fuera = np.abs(t_libre - t) * L[None]
    d = np.linalg.norm(v[:, None, :] - p, axis=2) + 3.0 * fuera
    w = np.exp(-(d - d.min(axis=1, keepdims=True)) / suavidad)
    w[w < 0.02] = 0
    w /= w.sum(axis=1, keepdims=True)
    for vg in list(ob.vertex_groups):
        ob.vertex_groups.remove(vg)
    for j, nombre in enumerate(nombres):
        idx = np.nonzero(w[:, j])[0]
        if len(idx) == 0:
            continue
        g = ob.vertex_groups.new(name=nombre)
        for i in idx:
            g.add([int(i)], float(w[i, j]), "REPLACE")
    mod = ob.modifiers.new("Esqueleto", "ARMATURE")
    mod.object = arm
    mod.use_deform_preserve_volume = True
    # el armature debe ir antes que la subdivisión
    ob.modifiers.move(ob.modifiers.find(mod.name), 0)


# ---------------------------------------------------------------- pierna

class Pierna(Region):
    """Pierna derecha (cadera a tobillo). Lateral = -X, anterior = -Y, arriba = +Z."""

    def epicondilo_lateral(self):
        """Punto más externo del cóndilo femoral: donde roza la cintilla iliotibial."""
        v = _verts_mundo(self["Femur"])
        zmin = v[:, 2].min()
        cerca = v[v[:, 2] < zmin + 0.07]
        return Vector(cerca[np.argmin(cerca[:, 0])])

    def cabeza_femoral(self):
        v = _verts_mundo(self["Femur"])
        arriba = v[v[:, 2] > v[:, 2].max() - 0.05]
        medial = arriba[arriba[:, 0] > np.median(arriba[:, 0])]
        return Vector(medial.mean(axis=0))

    def centro_rodilla(self):
        f = _verts_mundo(self["Femur"])
        t = _verts_mundo(self["Tibia"])
        condilos = f[f[:, 2] < f[:, 2].min() + 0.025].mean(axis=0)
        meseta = t[t[:, 2] > t[:, 2].max() - 0.02].mean(axis=0)
        return Vector((condilos + meseta) / 2)

    def tobillo(self):
        t = _verts_mundo(self["Tibia"])
        return Vector(t[t[:, 2] < t[:, 2].min() + 0.02].mean(axis=0))


def crear_rig_pierna(pierna, deformar=True, suavidad=0.012):
    """Esqueleto de la pierna: 'pelvis' (raíz), 'muslo', 'pierna' y 'rotula'.

    Flexión con rig.flexion('muslo', grados) (cadera) y rig.flexion('pierna',
    grados) (rodilla); la rótula sigue sola a la rodilla (≈55 % de su giro),
    deslizándose por la tróclea. Los tejidos blandos se deforman por cercanía.
    """
    cadera = pierna.cabeza_femoral()
    rodilla = pierna.centro_rodilla()
    tobillo = pierna.tobillo()
    rotula_c = _centro(pierna["Patella"])
    anterior = Vector((0, -1, 0))

    arm_d = bpy.data.armatures.new("Rig_pierna")
    arm = bpy.data.objects.new("Rig_pierna", arm_d)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm_d.edit_bones
    b = eb.new("pelvis")
    b.head, b.tail = cadera, cadera + Vector((0, 0, 0.12))
    b.align_roll(anterior)
    b = eb.new("muslo")
    b.head, b.tail = cadera, rodilla
    b.align_roll(anterior)
    b.parent = eb["pelvis"]
    b = eb.new("pierna")
    b.head, b.tail = rodilla, tobillo
    b.align_roll(anterior)
    b.parent = eb["muslo"]
    b.use_connect = True
    b = eb.new("rotula")
    b.head, b.tail = rodilla, rotula_c
    b.align_roll(Vector((0, 0, 1)))
    b.parent = eb["muslo"]
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"

    def signo(hueso, quiere):
        pb = arm.pose.bones[hueso]
        antes = (arm.matrix_world @ pb.tail).copy()
        pb.rotation_euler = (math.radians(20), 0, 0)
        bpy.context.view_layer.update()
        d = (arm.matrix_world @ pb.tail) - antes
        pb.rotation_euler = (0, 0, 0)
        bpy.context.view_layer.update()
        return 1.0 if d.dot(quiere) > 0 else -1.0

    # cadera: flexionar lleva la rodilla hacia delante; rodilla: el tobillo hacia atrás
    signos = {"muslo": signo("muslo", anterior), "pierna": signo("pierna", -anterior)}
    signos["rotula"] = signo("rotula", Vector((0, 0, -1)))
    rig = Rig(arm, anterior, 1.0, signos)

    c = arm.pose.bones["rotula"].constraints.new("TRANSFORM")
    c.target = arm
    c.subtarget = "pierna"
    c.map_from = c.map_to = "ROTATION"
    c.owner_space = c.target_space = "LOCAL"
    c.from_min_x_rot, c.from_max_x_rot = -math.pi, math.pi
    k = 0.55 * signos["rotula"] * signos["pierna"]
    c.to_min_x_rot, c.to_max_x_rot = -math.pi * k, math.pi * k

    for nombre, hueso in (("Hip bone", "pelvis"), ("Femur", "muslo"), ("Tibia", "pierna"),
                          ("Fibula", "pierna"), ("Patella", "rotula")):
        if nombre in pierna:
            _emparentar(pierna[nombre], arm, hueso)

    if deformar:
        blandos = pierna.coleccion("Articulaciones") + pierna.coleccion("Musculos_tendones")
        if pierna.piel:
            blandos.append(pierna.piel)
        for ob in blandos:
            pesos_por_cercania(ob, rig, suavidad, huesos=("pelvis", "muslo", "pierna"))
            mundo = ob.matrix_world.copy()
            ob.parent = arm
            ob.matrix_parent_inverse = arm.matrix_world.inverted()
            ob.matrix_world = mundo
    return rig


def zona(nombre, centro, radios, hueso_rig=None, rig=None, material=None):
    """Elipsoide para marcar una zona (inflamación, punto de dolor...).

    Si se da hueso_rig, se emparenta para seguir al hueso.
    """
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=centro, segments=32, ring_count=16)
    ob = bpy.context.active_object
    ob.name = nombre
    ob.scale = radios
    for p in ob.data.polygons:
        p.use_smooth = True
    if material:
        ob.data.materials.append(material)
    if hueso_rig and rig:
        bpy.context.view_layer.update()
        _emparentar(ob, rig.arm, hueso_rig)
    return ob


# ---------------------------------------------------------------- poleas

def _marco_reposo(rig, hueso):
    """Matriz mundial del hueso en reposo (Y = eje, Z = dorsal)."""
    return rig.arm.matrix_world @ rig.arm.data.bones[hueso].matrix_local


def _seccion(verts_loc, y0, y1):
    sel = verts_loc[(verts_loc[:, 1] >= y0) & (verts_loc[:, 1] <= y1)]
    return sel


def crear_poleas(mano, rig, dedo, cuales=("A1", "A2", "A3", "A4", "A5"), material=None,
                 grosor=0.0007, partida=("A2",)):
    """Genera las poleas anulares de un dedo ajustadas al hueso y a los flexores.

    Las poleas listadas en 'partida' se crean en dos mitades (izquierda y
    derecha) con el origen en su anclaje al hueso, para poder romperlas con
    animacion.romper_polea(). Devuelve {nombre: objeto o (izq, der)}.
    """
    flexores = [mano[n] for n in FLEXORES if n in mano.obj]
    resultado = {}
    for nombre in cuales:
        fal, f0, f1 = POLEAS[nombre]
        if dedo == "pulgar" and fal == "P2":
            continue
        hueso_rig = f"{dedo}.{fal}"
        if hueso_rig not in rig.arm.data.bones:
            continue
        m = _marco_reposo(rig, hueso_rig)
        mi = np.array(m.inverted())
        L = rig.arm.data.bones[hueso_rig].length
        y0, y1 = f0 * L, f1 * L
        # vértices del hueso (y del anterior para poleas sobre la articulación) en el marco local
        hv = _verts_mundo(mano.hueso(dedo, fal))
        if f0 < 0:
            prev = mano.falanges(dedo)[mano.falanges(dedo).index(fal) - 1]
            hv = np.vstack([hv, _verts_mundo(mano.hueso(dedo, prev))])
        hl = hv @ mi[:3, :3].T + mi[:3, 3]
        tl = np.vstack([_verts_mundo(o) for o in flexores]) @ mi[:3, :3].T + mi[:3, 3] \
            if flexores else np.zeros((0, 3))
        filas = []
        n_filas = 9
        for k in range(n_filas):
            y = y0 + (y1 - y0) * k / (n_filas - 1)
            s = _seccion(hl, y - 0.0015, y + 0.0015)
            if len(s) < 4:
                s = _seccion(hl, y - 0.004, y + 0.004)
            w = np.abs(s[:, 0]).max() if len(s) else 0.005
            zc = np.median(s[:, 2]) if len(s) else 0.0
            zb = s[:, 2].min() if len(s) else -0.004
            ts = _seccion(tl, y - 0.002, y + 0.002)
            ts = ts[(np.abs(ts[:, 0]) < w * 1.4) & (ts[:, 2] < zc)] if len(ts) else ts
            zt = min(ts[:, 2].min(), zb) if len(ts) else zb - 0.004
            filas.append((y, w * 1.04 + grosor, zc, zc - zt + grosor * 1.5))
        if nombre in partida:
            izq = _arco(f"{nombre}_{dedo}_izq", filas, -1, m, material, grosor)
            der = _arco(f"{nombre}_{dedo}_der", filas, 1, m, material, grosor)
            for o in (izq, der):
                _emparentar(o, rig.arm, hueso_rig)
            resultado[nombre] = (izq, der)
        else:
            ob = _arco(f"{nombre}_{dedo}", filas, 0, m, material, grosor)
            _emparentar(ob, rig.arm, hueso_rig)
            resultado[nombre] = ob
    return resultado


def _arco(nombre, filas, lado, m, material, grosor, nu=24):
    """Banda que abraza los flexores por la cara palmar.

    lado: 0 = arco completo, -1 / 1 = solo la mitad de ese lado, con el origen
    en el anclaje óseo (para que gire como una bisagra al romperse).
    """
    if lado == 0:
        a0, a1 = 0.08, math.pi - 0.08
    elif lado > 0:
        a0, a1 = 0.08, math.pi / 2
    else:
        a0, a1 = math.pi / 2, math.pi - 0.08
    bm = bmesh.new()
    grid = []
    n = len(filas)
    for k, (y, a, zc, b) in enumerate(filas):
        borde = math.sin(math.pi * k / (n - 1))   # los bordes de la banda se adelgazan
        fila = []
        for i in range(nu):
            t = a0 + (a1 - a0) * i / (nu - 1)
            x = a * math.cos(t) * (1 + 0.03 * borde)
            z = zc - b * math.sin(t)   # hacia palmar (-Z)
            fila.append(bm.verts.new((x, y, z)))
        grid.append(fila)
    for k in range(n - 1):
        for i in range(nu - 1):
            bm.faces.new((grid[k][i], grid[k][i + 1], grid[k + 1][i + 1], grid[k + 1][i]))
    me = bpy.data.meshes.new(nombre)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    ob = bpy.data.objects.new(nombre, me)
    bpy.context.scene.collection.objects.link(ob)
    ob.matrix_world = m
    # origen en el anclaje (extremo lateral de la mitad)
    if lado != 0:
        y, a, zc, b = filas[n // 2]
        t = a0 if lado > 0 else a1
        piv = Vector((a * math.cos(t), y, zc - b * math.sin(t)))
        me.transform(Matrix.Translation(-piv))
        ob.matrix_world = m @ Matrix.Translation(piv)
    sol = ob.modifiers.new("Grosor", "SOLIDIFY")
    sol.thickness = grosor
    sol.offset = 1.0
    sub = ob.modifiers.new("Subsurf", "SUBSURF")
    sub.levels, sub.render_levels = 1, 2
    if material:
        me.materials.append(material)
    return ob


# ---------------------------------------------------------------- utilidades

def objetos_flexores(mano):
    return [mano[n] for n in FLEXORES if n in mano.obj]


def grupo_tramo(ob, rig, hueso, desde=0.0, hasta=1.0, lado=-1, nombre="Tramo", radio=0.012):
    """Grupo de vértices con peso suave en un tramo de un hueso del rig.

    lado=-1 selecciona la cara palmar, 1 la dorsal y 0 ambas. El peso es
    máximo en el centro del tramo y cae a cero en sus extremos.
    """
    m = _marco_reposo(rig, hueso)
    mi = np.array(m.inverted())
    L = rig.arm.data.bones[hueso].length
    v = _verts_mundo(ob) @ mi[:3, :3].T + mi[:3, 3]
    y = (v[:, 1] / L - desde) / (hasta - desde)
    w = np.where((y > 0) & (y < 1), np.sin(np.pi * np.clip(y, 0, 1)) ** 2, 0.0)
    w *= np.exp(-(v[:, 0] / radio) ** 2)
    if lado:
        w *= (np.sign(v[:, 2]) == np.sign(lado))
    g = ob.vertex_groups.get(nombre) or ob.vertex_groups.new(name=nombre)
    for i in np.nonzero(w > 0.01)[0]:
        g.add([int(i)], float(w[i]), "REPLACE")
    return g, m
