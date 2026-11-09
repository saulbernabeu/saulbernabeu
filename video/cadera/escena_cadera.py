"""Escena 3D del reel «¿Te duele el lateral de la cadera al dormir de lado?».

Uso:
    python escena_cadera.py --out frames/ [--frames 0-143] [--samples 48] [--res 100]
    python escena_cadera.py --still 300 --out pruebas/ --res 40

Construye toda la escena con bpy (Blender como módulo de Python) y la renderiza
con Cycles. La anatomía (pelvis, fémur y glúteos) viene de TACs reales:
modelo/s1045.glb del conjunto «CT Anatomy GLB» (CC BY 4.0), basado en
TotalSegmentator (Wasserthal et al., 2023).

El maniquí se construye con metaballs y se posa por cinemática directa en cada
fotograma. Además de las imágenes, el script guarda en <out>/anclas.json la
posición en pantalla de los puntos anatómicos, para colocar los rótulos.
"""
import argparse
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector
from bpy_extras.object_utils import world_to_camera_view

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from humano import Humano  # noqa: E402
GLB = os.path.join(HERE, "modelo", "s1045.glb")
FPS = 24
N_FRAMES = 1440

# ------------------------------------------------------------------ guion
# Planos (segundos de la locución ya acelerada). Ver audio/palabras.json.
SHOTS = [
    ("gancho", 0.00, 6.00),
    ("escaleras", 6.00, 8.20),
    ("cruzar", 8.20, 9.85),
    ("unapierna", 9.85, 11.65),
    ("rayosx", 11.65, 14.30),
    ("anatomia", 14.30, 22.80),
    ("noche", 22.80, 26.50),
    ("tres", 26.50, 29.20),        # rótulo 2D: no se renderiza
    ("error1", 29.20, 34.90),
    ("error2", 34.90, 39.10),
    ("error3", 39.10, 45.20),
    ("solucion", 45.20, 53.30),
    ("cierre", 53.30, 60.00),
]


def shot_of(t):
    for name, a, b in SHOTS:
        if a <= t < b:
            return name, a, b
    return SHOTS[-1]


# ------------------------------------------------------------------ utilidades

def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def smooth(t):
    t = clamp(t)
    return t * t * (3 - 2 * t)


def ease(t, a, b):
    """0 antes de a, 1 después de b, suave entre medias."""
    if b <= a:
        return 1.0 if t >= a else 0.0
    return smooth((t - a) / (b - a))


def lerp(a, b, f):
    return a + (b - a) * f


def pulse(t, hz=1.1):
    return 0.5 + 0.5 * math.sin(2 * math.pi * hz * t)


def R(axis, deg):
    return Matrix.Rotation(math.radians(deg), 4, axis)


def T(x, y, z):
    return Matrix.Translation((x, y, z))


def look_at(obj, loc, target, roll=0.0):
    obj.location = loc
    d = Vector(target) - Vector(loc)
    q = d.to_track_quat("-Z", "Y")
    if roll:
        q = q @ Quaternion((0, 0, 1), math.radians(roll))
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = q


def link(ob):
    bpy.context.scene.collection.objects.link(ob)
    return ob


# ------------------------------------------------------------------ materiales

def new_mat(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    return m, m.node_tree.nodes, m.node_tree.links


def principled(name, color, rough=0.5, sss=0.0, sss_scale=0.01, coat=0.0,
               sheen=0.0, spec=0.5, sss_radius=(1.0, 0.35, 0.2)):
    m, nodes, _ = new_mat(name)
    b = nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Subsurface Weight"].default_value = sss
    b.inputs["Subsurface Scale"].default_value = sss_scale
    b.inputs["Subsurface Radius"].default_value = sss_radius
    b.inputs["Coat Weight"].default_value = coat
    b.inputs["Sheen Weight"].default_value = sheen
    b.inputs["Specular IOR Level"].default_value = spec
    return m


def value_node(nodes, name, v=0.0):
    n = nodes.new("ShaderNodeValue")
    n.name = name
    n.outputs[0].default_value = v
    return n.outputs[0]


def dist_factor(nodes, links, empty, radius, power=2.0):
    """Factor 1 en el centro del empty y 0 a `radius` (en metros)."""
    tc = nodes.new("ShaderNodeTexCoord")
    tc.object = empty
    ln = nodes.new("ShaderNodeVectorMath")
    ln.operation = "LENGTH"
    links.new(tc.outputs["Object"], ln.inputs[0])
    mr = nodes.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = 0.0
    mr.inputs["From Max"].default_value = radius
    mr.inputs["To Min"].default_value = 1.0
    mr.inputs["To Max"].default_value = 0.0
    links.new(ln.outputs["Value"], mr.inputs["Value"])
    pw = nodes.new("ShaderNodeMath")
    pw.operation = "POWER"
    pw.inputs[1].default_value = power
    links.new(mr.outputs["Result"], pw.inputs[0])
    return pw.outputs[0]


def math_node(nodes, links, op, a, b=None, val=None):
    n = nodes.new("ShaderNodeMath")
    n.operation = op
    if isinstance(a, (int, float)):
        n.inputs[0].default_value = a
    else:
        links.new(a, n.inputs[0])
    if b is not None:
        if isinstance(b, (int, float)):
            n.inputs[1].default_value = b
        else:
            links.new(b, n.inputs[1])
    return n.outputs[0]


def mix_color(nodes, links, fac, a, b):
    n = nodes.new("ShaderNodeMix")
    n.data_type = "RGBA"
    links.new(fac, n.inputs["Factor"])
    for sock, v in ((n.inputs["A"], a), (n.inputs["B"], b)):
        if isinstance(v, tuple):
            sock.default_value = (*v, 1)
        else:
            links.new(v, sock)
    return n.outputs["Result"]


HEAT = (1.0, 0.16, 0.05)     # rojo-anaranjado de inflamación
COOL = (0.1, 0.85, 0.75)     # turquesa de recuperación


def _tex(nodes, links, path, uv, non_color=True):
    t = nodes.new("ShaderNodeTexImage")
    t.image = bpy.data.images.load(path, check_existing=True)
    if non_color:
        t.image.colorspace_settings.name = "Non-Color"
    links.new(uv, t.inputs["Vector"])
    return t.outputs["Color"]


def _attr(nodes, name):
    a = nodes.new("ShaderNodeAttribute")
    a.attribute_name = name
    return a.outputs["Fac"]


def _noise(nodes, links, vec, scale, detail=4.0, rough=0.6):
    n = nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    n.inputs["Roughness"].default_value = rough
    if vec is not None:
        links.new(vec, n.inputs["Vector"])
    return n.outputs["Fac"]


def heat_xray(m, nodes, links, b, col, hot, emis=30.0):
    """Tinte y brillo de dolor (HEAT) o recuperación (COOL) y modo rayos X."""
    out = nodes["Material Output"]
    heat = value_node(nodes, "HEAT", 0.0)
    cool = value_node(nodes, "COOL", 0.0)
    xray = value_node(nodes, "XRAY", 0.0)
    f_core = dist_factor(nodes, links, hot, 0.07, 1.5)
    f_wide = dist_factor(nodes, links, hot, 0.16, 2.0)
    tint = math_node(nodes, links, "MULTIPLY", f_wide, heat)
    tint = math_node(nodes, links, "MINIMUM", tint, 0.85)
    col = mix_color(nodes, links, tint, col, (0.75, 0.10, 0.06))
    ctint = math_node(nodes, links, "MULTIPLY", f_wide, cool)
    col = mix_color(nodes, links, ctint, col, (0.15, 0.7, 0.62))
    links.new(col, b.inputs["Base Color"])
    e_h = math_node(nodes, links, "MULTIPLY", f_core, heat)
    e_c = math_node(nodes, links, "MULTIPLY", f_core, cool)
    ecol = mix_color(nodes, links, math_node(nodes, links, "DIVIDE", e_c,
                                             math_node(nodes, links, "ADD", e_h, e_c)),
                     HEAT, COOL)
    links.new(ecol, b.inputs["Emission Color"])
    links.new(math_node(nodes, links, "MULTIPLY",
                        math_node(nodes, links, "ADD", e_h, e_c), emis),
              b.inputs["Emission Strength"])
    # rayos X: transparente con borde azulado (efecto Fresnel)
    lw = nodes.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.35
    em = nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (0.45, 0.75, 1.0, 1)
    links.new(math_node(nodes, links, "MULTIPLY", lw.outputs["Facing"], 0.8),
              em.inputs["Strength"])
    tr = nodes.new("ShaderNodeBsdfTransparent")
    add = nodes.new("ShaderNodeAddShader")
    links.new(tr.outputs[0], add.inputs[0])
    links.new(em.outputs[0], add.inputs[1])
    mix = nodes.new("ShaderNodeMixShader")
    links.new(xray, mix.inputs[0])
    links.new(b.outputs[0], mix.inputs[1])
    links.new(add.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Surface"])
    return m


TEX = os.path.join(HERE, "modelo", "makehuman", "texturas")


def skin_material(hot):
    """Piel realista: dispersión subsuperficial, poros, labios, barba de dos días y cejas."""
    m, nodes, links = new_mat("Piel")
    b = nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = 0.5
    b.inputs["Specular IOR Level"].default_value = 0.45
    b.inputs["Subsurface Weight"].default_value = 1.0
    b.inputs["Subsurface Scale"].default_value = 0.0025
    b.inputs["Subsurface Radius"].default_value = (1.0, 0.4, 0.25)
    uvn = nodes.new("ShaderNodeUVMap")
    uvn.uv_map = "UV"
    uv = uvn.outputs["UV"]
    tc = nodes.new("ShaderNodeTexCoord")
    gen = tc.outputs["Generated"]
    # tono base con variación suave
    var = _noise(nodes, links, gen, 9.0, 3.0)
    col = mix_color(nodes, links, var, (0.66, 0.39, 0.27), (0.56, 0.30, 0.21))
    face = _tex(nodes, links, os.path.join(TEX, "mpfb_face.jpg"), uv)
    col = mix_color(nodes, links, math_node(nodes, links, "MULTIPLY", face, 0.08), col, (0.62, 0.30, 0.22))
    lips = _tex(nodes, links, os.path.join(TEX, "mpfb_lips.jpg"), uv)
    col = mix_color(nodes, links, math_node(nodes, links, "MULTIPLY", lips, 0.75), col, (0.42, 0.15, 0.13))
    nails = math_node(nodes, links, "MAXIMUM",
                      _tex(nodes, links, os.path.join(TEX, "mpfb_fingernails.jpg"), uv),
                      _tex(nodes, links, os.path.join(TEX, "mpfb_toenails.jpg"), uv))
    col = mix_color(nodes, links, math_node(nodes, links, "MULTIPLY", nails, 0.5), col, (0.75, 0.55, 0.48))
    # barba de dos días y cejas: puntos finos oscuros
    fine = _noise(nodes, links, gen, 900.0, 1.0, 0.5)
    dots = math_node(nodes, links, "GREATER_THAN", fine, 0.52)
    stub = math_node(nodes, links, "MULTIPLY", _attr(nodes, "barba"),
                     math_node(nodes, links, "ADD", math_node(nodes, links, "MULTIPLY", dots, 0.35), 0.18))
    col = mix_color(nodes, links, stub, col, (0.12, 0.08, 0.06))
    brow_n = _noise(nodes, links, gen, 500.0, 2.0, 0.6)
    brow = math_node(nodes, links, "MULTIPLY", _attr(nodes, "cejas"),
                     math_node(nodes, links, "ADD", math_node(nodes, links, "MULTIPLY", brow_n, 0.5), 0.45))
    col = mix_color(nodes, links, math_node(nodes, links, "MINIMUM", brow, 0.95), col, (0.04, 0.025, 0.018))
    scalp = math_node(nodes, links, "MULTIPLY", _attr(nodes, "pelo"), 0.8)
    col = mix_color(nodes, links, scalp, col, (0.07, 0.045, 0.03))
    # relieve: poros y arrugas suaves
    pores = _noise(nodes, links, gen, 2600.0, 2.0, 0.7)
    wr = _noise(nodes, links, gen, 60.0, 6.0, 0.65)
    h = math_node(nodes, links, "ADD", pores, math_node(nodes, links, "MULTIPLY", wr, 0.6))
    bp = nodes.new("ShaderNodeBump")
    bp.inputs["Strength"].default_value = 0.12
    bp.inputs["Distance"].default_value = 0.0006
    links.new(h, bp.inputs["Height"])
    links.new(bp.outputs[0], b.inputs["Normal"])
    rv = _noise(nodes, links, gen, 25.0, 2.0)
    links.new(math_node(nodes, links, "ADD", math_node(nodes, links, "MULTIPLY", rv, 0.15), 0.42),
              b.inputs["Roughness"])
    return heat_xray(m, nodes, links, b, col, hot)


def cloth_material(name, color, hot, knit=1400.0, sheen=0.5):
    m, nodes, links = new_mat(name)
    b = nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = 0.88
    b.inputs["Sheen Weight"].default_value = sheen
    b.inputs["Sheen Tint"].default_value = (1, 1, 1, 1)
    b.inputs["Specular IOR Level"].default_value = 0.3
    tc = nodes.new("ShaderNodeTexCoord")
    gen = tc.outputs["Generated"]
    mp = nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (0.6, 0.35, 1.8)    # tamaño aproximado del cuerpo
    links.new(gen, mp.inputs["Vector"])
    v = mp.outputs[0]
    wv = nodes.new("ShaderNodeTexWave")
    wv.inputs["Scale"].default_value = knit
    wv.inputs["Distortion"].default_value = 2.0
    links.new(v, wv.inputs["Vector"])
    nz = _noise(nodes, links, v, 30.0, 4.0)
    wr = _noise(nodes, links, v, 8.0, 3.0)
    h = math_node(nodes, links, "ADD", wv.outputs[1], math_node(nodes, links, "MULTIPLY", nz, 2.0))
    h = math_node(nodes, links, "ADD", h, math_node(nodes, links, "MULTIPLY", wr, 3.0))
    bp = nodes.new("ShaderNodeBump")
    bp.inputs["Strength"].default_value = 0.2
    bp.inputs["Distance"].default_value = 0.002
    links.new(h, bp.inputs["Height"])
    links.new(bp.outputs[0], b.inputs["Normal"])
    col = mix_color(nodes, links, nz, color, tuple(c * 0.8 for c in color))
    return heat_xray(m, nodes, links, b, col, hot, emis=12.0)


def eye_material(hot):
    m, nodes, links = new_mat("Ojo")
    b = nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = 0.25
    b.inputs["Coat Weight"].default_value = 1.0
    b.inputs["Coat Roughness"].default_value = 0.02
    b.inputs["Subsurface Weight"].default_value = 0.3
    b.inputs["Subsurface Scale"].default_value = 0.003
    ramp = nodes.new("ShaderNodeValToRGB")
    links.new(_attr(nodes, "iris"), ramp.inputs["Fac"])
    els = ramp.color_ramp.elements
    els[0].position, els[0].color = 0.0, (0.55, 0.5, 0.45, 1)
    els[1].position, els[1].color = 0.80, (0.78, 0.74, 0.70, 1)
    for pos, c in ((0.905, (0.75, 0.70, 0.66, 1)), (0.915, (0.10, 0.05, 0.025, 1)),
                   (0.96, (0.16, 0.08, 0.035, 1)), (0.968, (0.005, 0.004, 0.004, 1))):
        e = els.new(pos)
        e.color = c
    return heat_xray(m, nodes, links, b, ramp.outputs["Color"], hot, emis=0.0)


def hair_material():
    m, nodes, links = new_mat("Pelo")
    out = nodes["Material Output"]
    nodes.remove(nodes["Principled BSDF"])
    h = nodes.new("ShaderNodeBsdfHairPrincipled")
    h.parametrization = "MELANIN"
    vals = {"Melanin": 0.88, "Melanin Redness": 0.35, "Roughness": 0.35,
            "Radial Roughness": 0.5, "Random Color": 0.15}
    for i in h.inputs:
        if i.name in vals:
            i.default_value = vals[i.name]
    links.new(h.outputs[0], out.inputs["Surface"])
    return m


def tissue_material(name, base, gt, tendon=True, bump_scale=900.0, fibers=True):
    """Músculo o hueso con zona tendinosa cerca del trocánter y calor/frescor."""
    m, nodes, links = new_mat(name)
    b = nodes["Principled BSDF"]
    out = nodes["Material Output"]
    heat = value_node(nodes, "HEAT", 0.0)
    cool = value_node(nodes, "COOL", 0.0)
    glow = value_node(nodes, "GLOW", 0.0)     # resaltado del músculo entero
    alpha = value_node(nodes, "ALPHA", 1.0)
    col = base
    rough = 0.45 if fibers else 0.55
    if tendon:
        ft = dist_factor(nodes, links, gt, 0.045, 1.2)
        col = mix_color(nodes, links, ft, base, (0.86, 0.82, 0.74))
        links.new(math_node(nodes, links, "SUBTRACT", 0.45,
                            math_node(nodes, links, "MULTIPLY", ft, 0.25)),
                  b.inputs["Roughness"])
    else:
        b.inputs["Roughness"].default_value = rough
    fh = dist_factor(nodes, links, gt, 0.05, 1.3)
    e_h = math_node(nodes, links, "MULTIPLY", fh, heat)
    e_c = math_node(nodes, links, "MULTIPLY", fh, cool)
    tint = math_node(nodes, links, "MINIMUM", math_node(nodes, links, "ADD", e_h, e_c), 1.0)
    hot_col = mix_color(nodes, links, math_node(nodes, links, "DIVIDE", e_c,
                                                math_node(nodes, links, "ADD", e_h, 1e-4)),
                        HEAT, COOL)
    col = mix_color(nodes, links, math_node(nodes, links, "MULTIPLY", tint, 0.8), col, hot_col)
    links.new(col, b.inputs["Base Color"])
    links.new(hot_col, b.inputs["Emission Color"])
    strength = math_node(nodes, links, "ADD",
                         math_node(nodes, links, "MULTIPLY", e_h, 9.0),
                         math_node(nodes, links, "MULTIPLY", e_c, 6.0))
    links.new(strength, b.inputs["Emission Strength"])
    b.inputs["Subsurface Weight"].default_value = 0.35 if fibers else 0.15
    b.inputs["Subsurface Scale"].default_value = 0.004
    b.inputs["Subsurface Radius"].default_value = (1.0, 0.3, 0.2)
    b.inputs["Coat Weight"].default_value = 0.35 if fibers else 0.1
    b.inputs["Coat Roughness"].default_value = 0.25
    # relieve: fibras para músculo, poros para hueso
    tc = nodes.new("ShaderNodeTexCoord")
    if fibers:
        tx = nodes.new("ShaderNodeTexWave")
        tx.wave_type = "BANDS"
        tx.bands_direction = "Z"
        tx.inputs["Scale"].default_value = 260.0
        tx.inputs["Distortion"].default_value = 6.0
        tx.inputs["Detail"].default_value = 3.0
    else:
        tx = nodes.new("ShaderNodeTexNoise")
        tx.inputs["Scale"].default_value = bump_scale
        tx.inputs["Detail"].default_value = 6.0
    links.new(tc.outputs["Object"], tx.inputs["Vector"])
    bp = nodes.new("ShaderNodeBump")
    bp.inputs["Strength"].default_value = 0.18 if fibers else 0.12
    bp.inputs["Distance"].default_value = 0.0006
    links.new(tx.outputs[1] if fibers else tx.outputs[0], bp.inputs["Height"])
    links.new(bp.outputs[0], b.inputs["Normal"])
    # resaltado global (cuando se nombra el músculo): brillo suave
    gl = nodes.new("ShaderNodeEmission")
    gl.inputs["Color"].default_value = (1.0, 0.28, 0.16, 1)
    links.new(math_node(nodes, links, "MULTIPLY", glow, 0.9), gl.inputs["Strength"])
    add = nodes.new("ShaderNodeAddShader")
    links.new(b.outputs[0], add.inputs[0])
    links.new(gl.outputs[0], add.inputs[1])
    # transparencia
    tr = nodes.new("ShaderNodeBsdfTransparent")
    mix = nodes.new("ShaderNodeMixShader")
    links.new(alpha, mix.inputs[0])
    links.new(tr.outputs[0], mix.inputs[1])
    links.new(add.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Surface"])
    return m


def set_val(mat, name, v):
    mat.node_tree.nodes[name].outputs[0].default_value = v


# ------------------------------------------------------------------ maniquí

class Figure:
    """Maniquí de metaballs posado por cinemática directa.

    Sistema local de la pelvis: +Z hacia la cabeza, -Y hacia delante,
    -X es el lado derecho del maniquí (como en el TAC).
    """
    THIGH, SHIN = 0.44, 0.42
    FAMILIES = ["Tronco", "PiernaD", "PiernaI", "BrazoD", "BrazoI"]
    K = 0.575   # radio visible / radio de influencia de una metaball aislada

    def __init__(self, mat, hip_half=0.09):
        self.hip = hip_half
        self.merge = False   # todo en una sola familia (para rayos X)
        self.objs = {}
        for fam in self.FAMILIES:
            mb = bpy.data.metaballs.new(fam)
            mb.resolution = 0.03
            mb.render_resolution = 0.007
            mb.threshold = 0.6
            mb.materials.append(mat)
            ob = link(bpy.data.objects.new(fam, mb))
            self.objs[fam] = ob
        self.frames = {}

    # -- cinemática
    def solve(self, p):
        F = {}
        P = T(*p["root"]) @ p["rot"]
        F["pelvis"] = P
        S = P @ T(0, 0, 0.10) @ R("X", p["spine"][0]) @ R("Y", p["spine"][1]) @ R("Z", p["spine"][2])
        C = S @ T(0, 0, 0.19) @ R("X", p["chest"][0]) @ R("Y", p["chest"][1]) @ R("Z", p["chest"][2])
        H = C @ T(0, 0, 0.23) @ R("X", p["neck"][0]) @ R("Y", p["neck"][1]) @ R("Z", p["neck"][2])
        F.update(spine=S, chest=C, head=H)
        for side, sx in (("R", -1), ("L", 1)):
            fl, ab, ro = p["hip" + side]
            Hp = P @ T(sx * self.hip, 0, 0) @ R("X", -fl) @ R("Y", -sx * ab) @ R("Z", -sx * ro)
            K = Hp @ T(0, 0, -self.THIGH) @ R("X", p["knee" + side])
            A = K @ T(0, 0, -self.SHIN) @ R("X", -p["ankle" + side])
            F["hip" + side], F["knee" + side], F["ankle" + side] = Hp, K, A
            sf, sa = p["sh" + side]
            Sh = C @ T(sx * 0.175, 0.01, 0.17) @ R("X", -sf) @ R("Y", -sx * sa)
            E = Sh @ T(0, 0, -0.29) @ R("X", -p["elb" + side])
            W = E @ T(0, 0, -0.25)
            F["sh" + side], F["elb" + side], F["wri" + side] = Sh, E, W
        self.frames = F
        return F

    @staticmethod
    def pt(M, x=0.0, y=0.0, z=0.0):
        return M @ Vector((x, y, z))

    # -- elementos (familia, tipo, centro, radio visible, tamaños, rotación)
    def elements(self):
        F = self.frames
        E = []

        def ball(fam, M, loc, r, size=(1, 1, 1)):
            q = M.to_quaternion()
            E.append((fam, "ELLIPSOID", self.pt(M, *loc), r, size, q))

        def capsule(fam, a, b, r):
            d = b - a
            q = Vector((1, 0, 0)).rotation_difference(d.normalized())
            E.append((fam, "CAPSULE", (a + b) / 2, r, (d.length / 2, 1, 1), q))

        P, S, C, H = F["pelvis"], F["spine"], F["chest"], F["head"]
        # tronco
        ball("Tronco", P, (0, 0.012, 0.0), 0.165, (1.0, 0.68, 0.72))
        ball("Tronco", P, (-0.075, 0.05, -0.035), 0.085, (1, 0.9, 1))
        ball("Tronco", P, (0.075, 0.05, -0.035), 0.085, (1, 0.9, 1))
        ball("Tronco", S, (0, 0.0, 0.07), 0.14, (1.0, 0.68, 0.85))
        ball("Tronco", C, (0, 0.0, 0.08), 0.165, (1.0, 0.64, 0.9))
        ball("Tronco", C, (0, -0.03, 0.1), 0.13, (1.0, 0.7, 0.75))
        ball("Tronco", C, (-0.13, 0.0, 0.16), 0.075)
        ball("Tronco", C, (0.13, 0.0, 0.16), 0.075)
        capsule("Tronco", self.pt(C, 0, 0.005, 0.18), self.pt(H, 0, 0.0, 0.06), 0.055)
        ball("Tronco", H, (0, -0.008, 0.135), 0.105, (0.82, 0.95, 1.12))
        ball("Tronco", H, (0, -0.088, 0.13), 0.02, (0.8, 1.0, 1.5))     # nariz
        ball("Tronco", H, (0, -0.06, 0.06), 0.045, (1.2, 0.9, 0.8))     # mentón
        # piernas
        for side, sx in (("R", -1), ("L", 1)):
            fam = "Pierna" + ("D" if side == "R" else "I")
            Hp, K, A = F["hip" + side], F["knee" + side], F["ankle" + side]
            hip_c = self.pt(Hp, 0, 0, 0)
            knee_c = self.pt(K, 0, 0, 0)
            ankle_c = self.pt(A, 0, 0, 0)
            capsule(fam, self.pt(Hp, sx * 0.012, 0.005, -0.02), self.pt(Hp, 0, 0.0, -0.24), 0.083)
            capsule(fam, self.pt(Hp, 0, 0.0, -0.24), knee_c, 0.06)
            ball(fam, Hp, (0, -0.012, -0.16), 0.085, (0.95, 1.0, 1.6))
            ball(fam, K, (0, -0.008, 0.0), 0.05)
            capsule(fam, knee_c, self.pt(K, 0, 0, -0.30), 0.05)
            capsule(fam, self.pt(K, 0, 0, -0.30), ankle_c, 0.036)
            ball(fam, K, (0, 0.025, -0.13), 0.05, (1.0, 1.0, 1.9))
            capsule(fam, self.pt(A, 0, 0.035, -0.045), self.pt(A, 0, -0.15, -0.055), 0.034)
            ball(fam, A, (0, -0.07, -0.05), 0.045, (1.0, 1.9, 0.6))
            # brazos
            famb = "Brazo" + ("D" if side == "R" else "I")
            Sh, El, W = F["sh" + side], F["elb" + side], F["wri" + side]
            capsule(famb, self.pt(Sh), self.pt(El), 0.047)
            ball(famb, Sh, (0, 0, -0.1), 0.052, (1, 1, 1.7))
            capsule(famb, self.pt(El), self.pt(W), 0.036)
            ball(famb, W, (0, -0.005, -0.075), 0.042, (0.55, 1.0, 1.7))
        return E

    def lowest(self, E=None, fams=None):
        E = E or self.elements()
        lo = 1e9
        for fam, typ, c, r, size, q in E:
            if fams and fam not in fams:
                continue
            if typ == "CAPSULE":
                d = q @ Vector((size[0], 0, 0))
                lo = min(lo, (c + d).z - r, (c - d).z - r)
            else:
                lo = min(lo, c.z - r * max(size))
        return lo

    def apply(self, E):
        by = {f: [] for f in self.FAMILIES}
        for e in E:
            by["Tronco" if self.merge else e[0]].append(e)
        for fam, els in by.items():
            mb = self.objs[fam].data
            while len(mb.elements) < len(els):
                mb.elements.new()
            while len(mb.elements) > len(els):
                mb.elements.remove(mb.elements[-1])
            for el, (_, typ, c, r, size, q) in zip(mb.elements, els):
                el.type = typ
                el.co = c
                el.radius = r / self.K
                el.stiffness = 2.0
                el.rotation = q
                if typ == "CAPSULE":
                    el.size_x = size[0]
                else:
                    el.size_x, el.size_y, el.size_z = size

    def set_visible(self, v):
        for ob in self.objs.values():
            ob.hide_render = not v


# ------------------------------------------------------------------ posturas

def base_pose():
    return dict(root=(0.0, 0.0, 0.93), rot=Matrix.Identity(4),
                spine=(2, 0, 0), chest=(0, 0, 0), neck=(-2, 0, 0),
                hipR=(0, 3, 0), hipL=(0, 3, 0), kneeR=3, kneeL=3,
                ankleR=0, ankleL=0, shR=(4, 7), shL=(4, 7), elbR=12, elbL=12)


ROT_LIE_R = R("Y", -90)                       # tumbado sobre el lado derecho
ROT_LIE_L = R("X", 180) @ ROT_LIE_R           # tumbado sobre el izquierdo
ROT_SUPINE = Matrix(((0, 1, 0, 0), (0, 0, -1, 0), (-1, 0, 0, 0), (0, 0, 0, 1))).transposed()


def pose(**kw):
    p = base_pose()
    p.update(kw)
    return p


POSES = {
    "pie": pose(),
    "pieX": pose(hipR=(0, 6, 0), hipL=(0, 6, 0), shR=(4, 14), shL=(4, 14)),
    "tumbadoD": pose(rot=ROT_LIE_R, spine=(12, 0, 0), chest=(8, 0, 0), neck=(10, -8, 0),
                     hipR=(42, 0, 0), kneeR=62, hipL=(48, -10, 0), kneeL=70,
                     ankleR=-15, ankleL=-15, shR=(80, 0), elbR=95, shL=(60, -38), elbL=40),
    "tumbadoI": pose(rot=ROT_LIE_L, spine=(12, 0, 0), chest=(8, 0, 0), neck=(10, 8, 0),
                     hipR=(48, 3, 0), kneeR=72, hipL=(42, 0, 0), kneeL=62,
                     ankleR=-15, ankleL=-15, shR=(60, -38), elbR=40, shL=(80, 0), elbL=95),
    "escalon": pose(root=(0, 0.02, 0.93), spine=(8, 0, 0), hipR=(48, 3, 0), kneeR=64,
                    hipL=(-12, 2, 0), kneeL=8, ankleL=8, shR=(-18, 8), elbR=20, shL=(24, 8), elbL=25),
    "cruzado": pose(spine=(-6, 0, 0), chest=(4, 0, 0), hipR=(114, -22, 0), kneeR=98,
                    hipL=(84, 5, 0), kneeL=84, ankleR=20, shR=(16, 12), elbR=95, shL=(16, 10), elbL=95),
    "unapierna": pose(root=(0.025, 0, 0.93), spine=(2, -3, 0), hipR=(0, -2, 0), kneeR=4,
                      hipL=(42, 4, 0), kneeL=75, ankleL=15, shR=(4, 18), elbR=10, shL=(4, 22), elbL=10),
    "colgado": pose(root=(-0.06, 0, 0.91), rot=R("Y", 9), spine=(2, -9, 0), chest=(0, -5, 0),
                    neck=(-2, 5, 0), hipR=(0, -12, 0), kneeR=1, hipL=(16, 6, 8), kneeL=26,
                    ankleL=8, shR=(6, 10), elbR=14, shL=(6, 10), elbL=14),
    "estiramiento": pose(rot=ROT_SUPINE, spine=(0, 0, 0), neck=(18, 0, 0),
                         hipR=(112, -30, 0), kneeR=118, hipL=(4, 2, 0), kneeL=6,
                         shR=(70, -12), elbR=60, shL=(62, -28), elbL=70),
    "supino": pose(rot=ROT_SUPINE, neck=(10, 0, 0), hipR=(55, 4, 0), kneeR=100,
                   hipL=(55, 4, 0), kneeL=100, ankleR=10, ankleL=10,
                   shR=(5, 14), elbR=5, shL=(5, 14), elbL=5),
}


def mix_pose(a, b, f):
    out = {}
    for k in a:
        va, vb = a[k], b[k]
        if k == "rot":
            out[k] = va.to_quaternion().slerp(vb.to_quaternion(), f).to_matrix().to_4x4()
        elif isinstance(va, tuple):
            out[k] = tuple(lerp(x, y, f) for x, y in zip(va, vb))
        else:
            out[k] = lerp(va, vb, f)
    return out


def rest_on(fig, p, height, sink=0.012, fams=None):
    """Ajusta la altura de la raíz para que el punto más bajo apoye en `height`."""
    fig.solve(p)
    lo = fig.lowest(fams=fams)
    x, y, z = p["root"]
    p["root"] = (x, y, z + (height - sink) - lo)
    fig.solve(p)
    return p


def leg_ik(fig, p, side, ankle):
    """Flexión de cadera y rodilla para llevar el tobillo a `ankle` (plano sagital)."""
    fig.solve(p)
    H = fig.frames["hip" + side].translation
    Rp = fig.frames["pelvis"].to_3x3()
    d = Rp.inverted() @ (Vector(ankle) - H)
    L1, L2 = fig.THIGH, fig.SHIN
    D = min(math.hypot(d.y, d.z), L1 + L2 - 1e-3)
    gamma = math.atan2(-d.y, -d.z)
    a1 = math.acos(clamp((L1 * L1 + D * D - L2 * L2) / (2 * L1 * D), -1, 1))
    kn = math.pi - math.acos(clamp((L1 * L1 + L2 * L2 - D * D) / (2 * L1 * L2), -1, 1))
    _, ab, ro = p["hip" + side]
    p["hip" + side] = (math.degrees(gamma + a1), 0.0, 0.0)
    p["knee" + side] = math.degrees(kn)
    return p


_BRIDGE = {}


def bridge_pose(fig, lift, mat_top):
    """Puente de glúteo: hombros apoyados, pies fijos y cadera elevada `lift` (0-1)."""
    if not _BRIDGE:
        p0 = rest_on(fig, dict(POSES["supino"]), mat_top)
        F = fig.frames
        S = fig.pt(F["chest"], 0, 0.04, 0.17)
        P = F["pelvis"].translation.copy()
        _BRIDGE.update(p0=p0, S=S, P=P, Lt=math.hypot(P.x - S.x, P.z - S.z),
                       b0=math.atan2(P.z - S.z, P.x - S.x),
                       aR=F["ankleR"].translation.copy(), aL=F["ankleL"].translation.copy())
    B = _BRIDGE
    p = dict(B["p0"])
    zp = B["P"].z + 0.2 * lift
    b1 = math.asin(clamp((zp - B["S"].z) / B["Lt"], -1, 1))
    px = B["S"].x + B["Lt"] * math.cos(b1)
    tilt = math.degrees(b1 - B["b0"])
    p["rot"] = ROT_SUPINE @ R("X", -tilt)
    p["root"] = (px, B["P"].y, zp)
    p["shR"] = (5 - tilt, 14)
    p["shL"] = (5 - tilt, 14)
    p["neck"] = (10 + 0.6 * tilt, 0, 0)
    p = leg_ik(fig, p, "R", B["aR"])
    p = leg_ik(fig, p, "L", B["aL"])
    fig.solve(p)
    return p


# ------------------------------------------------------------------ anatomía

ANAT_PELVIS = ["hip_right", "hip_left", "sacrum",
               "gluteus_medius_right", "gluteus_minimus_right", "gluteus_maximus_right",
               "gluteus_medius_left", "gluteus_minimus_left", "gluteus_maximus_left"]
ANAT_FEMUR_R = ["femur_right"]
ANAT_FEMUR_L = ["femur_left"]


def sphere_fit(pts):
    import numpy as np
    A = np.array([[2 * p.x, 2 * p.y, 2 * p.z, 1] for p in pts])
    b = np.array([p.x * p.x + p.y * p.y + p.z * p.z for p in pts])
    c = np.linalg.lstsq(A, b, rcond=None)[0]
    return Vector(c[:3]), math.sqrt(c[3] + c[0] ** 2 + c[1] ** 2 + c[2] ** 2)


class Anatomy:
    def __init__(self):
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=GLB)
        keep = set(ANAT_PELVIS + ANAT_FEMUR_R + ANAT_FEMUR_L)
        for ob in list(bpy.data.objects):
            if ob in before:
                continue
            if ob.type == "MESH" and ob.name not in keep:
                bpy.data.objects.remove(ob)
            elif ob.type == "EMPTY":
                bpy.data.objects.remove(ob)
        self.obs = {n: bpy.data.objects[n] for n in keep}
        for ob in self.obs.values():
            mw = ob.matrix_world.copy()
            ob.parent = None
            ob.matrix_world = mw
            # aplicar transformación a la malla: todo en coordenadas del TAC
            ob.data.transform(ob.matrix_world)
            ob.matrix_world = Matrix.Identity(4)
            for poly in ob.data.polygons:
                poly.use_smooth = True
            sm = ob.modifiers.new("Suavizar", "CORRECTIVE_SMOOTH")
            sm.factor = 0.5
            sm.iterations = 4
            sm.smooth_type = "LENGTH_WEIGHTED"
            sm.use_only_smooth = True
            ss = ob.modifiers.new("Subdiv", "SUBSURF")
            ss.levels = 1
            ss.render_levels = 2
        fr = [v.co.copy() for v in self.obs["femur_right"].data.vertices]
        fl = [v.co.copy() for v in self.obs["femur_left"].data.vertices]
        top_r = max(v.z for v in fr)
        top_l = max(v.z for v in fl)
        # cabeza femoral: parte medial y alta del fémur
        self.head_r, rr = sphere_fit([v for v in fr if v.z > top_r - 0.045 and v.x > -0.105])
        self.head_l, rl = sphere_fit([v for v in fl if v.z > top_l - 0.045 and v.x < 0.085])
        self.center = (self.head_r + self.head_l) / 2
        self.hip_half = (self.head_l - self.head_r).length / 2
        # trocánter mayor: el punto más lateral de la mitad alta del fémur derecho
        lat = min((v for v in fr if v.z > top_r - 0.06), key=lambda v: v.x)
        tip = max((v for v in fr if v.x < lat.x + 0.02), key=lambda v: v.z)
        self.gt = Vector((lat.x + 0.006, (lat.y + tip.y) / 2, (lat.z + tip.z) / 2))
        print(f"cabezas femorales R={tuple(round(c, 4) for c in self.head_r)} r={rr:.4f} "
              f"L={tuple(round(c, 4) for c in self.head_l)} r={rl:.4f}; "
              f"trocánter={tuple(round(c, 4) for c in self.gt)}")
        # empties de referencia: punto del trocánter (para materiales y rótulos)
        self.gt_empty = link(bpy.data.objects.new("Trocanter", None))
        self.gt_empty.location = self.gt
        self.med_anchor = link(bpy.data.objects.new("AnclaMedio", None))
        self.min_anchor = link(bpy.data.objects.new("AnclaMenor", None))
        self.med_anchor.location = self._centroid("gluteus_medius_right", lambda v: v.x < -0.12)
        self.min_anchor.location = self._centroid("gluteus_minimus_right", lambda v: v.x < -0.11)
        # materiales
        bone = (0.80, 0.72, 0.58)
        self.mats = {}
        for n, ob in self.obs.items():
            if n.startswith(("hip", "femur", "sacrum", "vert")):
                m = tissue_material("Hueso_" + n, bone, self.gt_empty, tendon=False, fibers=False)
            elif "maximus" in n:
                m = tissue_material("Musc_" + n, (0.42, 0.07, 0.06), self.gt_empty, tendon=False)
            elif "minimus" in n:
                m = tissue_material("Musc_" + n, (0.55, 0.12, 0.08), self.gt_empty)
            elif "medius" in n:
                m = tissue_material("Musc_" + n, (0.46, 0.06, 0.05), self.gt_empty)
            else:
                m = tissue_material("Musc_" + n, (0.40, 0.08, 0.07), self.gt_empty, tendon=False)
            ob.data.materials.clear()
            ob.data.materials.append(m)
            self.mats[n] = m
        self.rest = {n: Matrix.Identity(4) for n in self.obs}

    def _centroid(self, name, cond):
        vs = [v.co for v in self.obs[name].data.vertices if cond(v.co)]
        return sum(vs, Vector()) / len(vs)

    def place(self, P, hipR=Matrix.Identity(4), hipL=Matrix.Identity(4)):
        """P: matriz mundo de la pelvis (origen = centro entre cabezas femorales)."""
        base = P @ T(*(-self.center))
        for n in ANAT_PELVIS:
            self.obs[n].matrix_world = base
        fr = P @ T(*(self.head_r - self.center)) @ hipR @ T(*(-self.head_r))
        fl = P @ T(*(self.head_l - self.center)) @ hipL @ T(*(-self.head_l))
        self.obs["femur_right"].matrix_world = fr
        self.obs["femur_left"].matrix_world = fl
        self.gt_empty.matrix_world = fr @ T(*self.gt)
        self.med_anchor.matrix_world = base @ T(*self.med_anchor_local())
        self.min_anchor.matrix_world = base @ T(*self.min_anchor_local())

    def med_anchor_local(self):
        return self._med if hasattr(self, "_med") else self._cache()[0]

    def min_anchor_local(self):
        return self._min if hasattr(self, "_min") else self._cache()[1]

    def _cache(self):
        self._med = self._centroid("gluteus_medius_right", lambda v: v.x < -0.12)
        self._min = self._centroid("gluteus_minimus_right", lambda v: v.x < -0.11)
        return self._med, self._min

    def set_visible(self, v, left=True):
        for n, ob in self.obs.items():
            ob.hide_render = not v or (not left and n.endswith("_left"))

    def set(self, key, v, names=None):
        for n, m in self.mats.items():
            if names is None or n in names:
                set_val(m, key, v)


# ------------------------------------------------------------------ decorado

def rounded_box(name, size, loc, mat, bevel=0.03, segs=6, subsurf=0):
    me = bpy.data.meshes.new(name)
    ob = link(bpy.data.objects.new(name, me))
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me)
    bm.free()
    ob.scale = size
    ob.location = loc
    bpy.context.view_layer.update()
    me.transform(Matrix.Diagonal((*size, 1)))
    ob.scale = (1, 1, 1)
    bv = ob.modifiers.new("Bisel", "BEVEL")
    bv.width = bevel
    bv.segments = segs
    bv.limit_method = "NONE"
    if subsurf:
        s = ob.modifiers.new("Sub", "SUBSURF")
        s.levels = subsurf
        s.render_levels = subsurf
    for p in me.polygons:
        p.use_smooth = True
    me.materials.append(mat)
    return ob


def fabric_material(name, color, scale=1800.0):
    m, nodes, links = new_mat(name)
    b = nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = 0.85
    b.inputs["Sheen Weight"].default_value = 0.6
    b.inputs["Sheen Tint"].default_value = (1, 1, 1, 1)
    tc = nodes.new("ShaderNodeTexCoord")
    wv = nodes.new("ShaderNodeTexWave")
    wv.inputs["Scale"].default_value = scale
    wv.inputs["Distortion"].default_value = 1.5
    nz = nodes.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 40.0
    links.new(tc.outputs["Object"], wv.inputs["Vector"])
    links.new(tc.outputs["Object"], nz.inputs["Vector"])
    add = nodes.new("ShaderNodeMath")
    add.operation = "ADD"
    links.new(wv.outputs[1], add.inputs[0])
    links.new(nz.outputs[0], add.inputs[1])
    bp = nodes.new("ShaderNodeBump")
    bp.inputs["Strength"].default_value = 0.15
    links.new(add.outputs[0], bp.inputs["Height"])
    links.new(bp.outputs[0], b.inputs["Normal"])
    return m


class Set:
    def __init__(self):
        floor_m = principled("Suelo", (0.035, 0.038, 0.045), rough=0.32, spec=0.6)
        me = bpy.data.meshes.new("Suelo")
        import bmesh
        bm = bmesh.new()
        # ciclorama: suelo que se curva hacia una pared al fondo
        prof = []
        for i in range(25):
            a = math.pi / 2 * i / 24
            prof.append((0, 6 + 1.5 * math.sin(a), 1.5 - 1.5 * math.cos(a)))
        prof = [(0, -8, 0)] + prof + [(0, 7.5, 6)]
        rows = []
        for x in (-10, 10):
            rows.append([bm.verts.new((x, y, z)) for _, y, z in prof])
        for i in range(len(prof) - 1):
            bm.faces.new((rows[0][i], rows[1][i], rows[1][i + 1], rows[0][i + 1]))
        bm.to_mesh(me)
        bm.free()
        for p in me.polygons:
            p.use_smooth = True
        me.materials.append(floor_m)
        self.floor = link(bpy.data.objects.new("Suelo", me))
        # cama
        sheet = fabric_material("Sabana", (0.10, 0.13, 0.19))
        base = principled("Madera", (0.09, 0.06, 0.045), rough=0.45, coat=0.4)
        self.bed = [
            rounded_box("Colchon", (2.1, 1.0, 0.24), (0, 0.15, 0.38), sheet, 0.06, 8),
            rounded_box("Somier", (2.16, 1.06, 0.2), (0, 0.15, 0.17), base, 0.02, 4),
            rounded_box("Almohada", (0.34, 0.6, 0.12), (-0.88, 0.15, 0.55),
                        fabric_material("Funda", (0.22, 0.26, 0.34)), 0.05, 6, 2),
        ]
        self.bed_top = 0.50
        # cojín entre las rodillas
        self.pillow = rounded_box("Cojin", (0.36, 0.26, 0.11), (0, 0, 0),
                                  fabric_material("Cojin", (0.18, 0.55, 0.52)), 0.045, 6, 2)
        # escalones
        stair_m = principled("Escalon", (0.55, 0.56, 0.58), rough=0.5, coat=0.2)
        self.stairs = [rounded_box(f"Escalon{i}", (1.1, 0.32, 0.17 * (i + 1)),
                                   (0, -0.17 + 0.32 * i, 0.085 * (i + 1)), stair_m, 0.012, 3)
                       for i in range(3)]
        # taburete
        self.stool = [rounded_box("Asiento", (0.46, 0.42, 0.06), (0, 0.06, 0.45),
                                  principled("Cuero", (0.06, 0.06, 0.07), rough=0.35, coat=0.5), 0.025, 5),
                      rounded_box("Patas", (0.36, 0.32, 0.42), (0, 0.06, 0.21),
                                  principled("Metal", (0.5, 0.5, 0.52), rough=0.25), 0.01, 2)]
        self.stool_top = 0.48
        # esterilla
        self.mat = rounded_box("Esterilla", (1.9, 0.68, 0.012), (0, 0.0, 0.006),
                               principled("Goma", (0.05, 0.32, 0.31), rough=0.7), 0.005, 2)
        self.mat_top = 0.012
        # disco de peso
        me = bpy.data.meshes.new("Disco")
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=64, radius1=0.17, radius2=0.17, depth=0.04)
        bm.to_mesh(me)
        bm.free()
        for p in me.polygons:
            p.use_smooth = len(p.vertices) == 4
        me.materials.append(principled("Hierro", (0.03, 0.03, 0.035), rough=0.3, coat=0.6))
        self.plate = link(bpy.data.objects.new("Disco", me))
        bv = self.plate.modifiers.new("Bisel", "BEVEL")
        bv.width = 0.006
        bv.segments = 3
        # colchón de compresión (plano anatómico)
        self.slab = rounded_box("Presion", (0.7, 0.5, 0.16), (0, 0, -5),
                                fabric_material("Presion", (0.12, 0.15, 0.22), 2600), 0.06, 8, 1)
        # motas de luz flotando (fondo desenfocado)
        dust_m, nodes, links = new_mat("Mota")
        em = nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = (0.55, 0.8, 1.0, 1)
        em.inputs["Strength"].default_value = 6.0
        links.new(em.outputs[0], nodes["Material Output"].inputs["Surface"])
        import random
        rnd = random.Random(7)
        self.dust = []
        for i in range(70):
            me = bpy.data.meshes.new(f"Mota{i}")
            bm = bmesh.new()
            bmesh.ops.create_icosphere(bm, subdivisions=2, radius=rnd.uniform(0.0015, 0.004))
            bm.to_mesh(me)
            bm.free()
            me.materials.append(dust_m)
            ob = link(bpy.data.objects.new(f"Mota{i}", me))
            ob["base"] = (rnd.uniform(-0.6, 0.6), rnd.uniform(0.1, 0.9), rnd.uniform(-0.5, 0.6))
            ob["ph"] = rnd.uniform(0, 6.28)
            ob.visible_shadow = False
            self.dust.append(ob)

    def show(self, *groups):
        allg = {"bed": self.bed, "pillow": [self.pillow], "stairs": self.stairs,
                "stool": self.stool, "mat": [self.mat], "plate": [self.plate],
                "slab": [self.slab], "dust": self.dust, "floor": [self.floor]}
        for g, obs in allg.items():
            for ob in obs:
                ob.hide_render = g not in groups

    def place_dust(self, center, t, spread=1.0):
        for ob in self.dust:
            bx, by, bz = ob["base"]
            ph = ob["ph"]
            ob.location = (center[0] + spread * bx + 0.02 * math.sin(0.4 * t + ph),
                           center[1] + spread * by,
                           center[2] + spread * bz + 0.03 * math.sin(0.25 * t + ph * 2))


# ------------------------------------------------------------------ luces y mundo

class Lights:
    def __init__(self):
        sc = bpy.context.scene
        self.world = bpy.data.worlds.new("Mundo")
        sc.world = self.world
        self.world.use_nodes = True
        self.bg = self.world.node_tree.nodes["Background"]
        self.bg.inputs[0].default_value = (0.004, 0.005, 0.009, 1)
        self.bg.inputs[1].default_value = 1.0
        self.L = {}
        for name, typ in (("clave", "AREA"), ("contra", "AREA"), ("relleno", "AREA"),
                          ("cenital", "AREA"), ("luna", "AREA")):
            l = bpy.data.lights.new(name, typ)
            ob = link(bpy.data.objects.new(name, l))
            self.L[name] = ob

    def setup(self, target, key=(-1.5, -2.0, 2.2), rim=(1.4, 1.8, 1.6), fill=(-2.4, 0.4, 0.6),
              ek=420, er=520, ef=60, et=0, night=False, scale=1.0, ec=None):
        tgt = Vector(target)
        conf = {
            "clave": (key, ek, 1.6, (1.0, 0.92, 0.84)),
            "contra": (rim, er, 1.0, (0.55, 0.75, 1.0)),
            "relleno": (fill, ef, 2.5, (0.8, 0.85, 1.0)),
            "cenital": ((0, 0, 3.0), et, 2.0, (1.0, 0.97, 0.95)),
            "luna": ((-1.0, -1.2, 2.6), 0.0, 1.2, (0.45, 0.6, 1.0)),
        }
        if night:
            conf["clave"] = (key, ek * 0.12, 1.6, (1.0, 0.8, 0.6))
            conf["luna"] = ((-0.4, -1.6, 2.8), 260, 1.4, (0.4, 0.55, 1.0))
            conf["relleno"] = (fill, ef * 0.3, 2.5, (0.4, 0.5, 0.9))
        for name, (loc, e, size, col) in conf.items():
            ob = self.L[name]
            loc = tgt + Vector(loc) * scale
            ob.location = loc
            ob.rotation_mode = "QUATERNION"
            ob.rotation_quaternion = (tgt - loc).to_track_quat("-Z", "Y")
            ob.data.energy = e * scale * scale
            ob.data.size = size * scale
            ob.data.color = col


# ------------------------------------------------------------------ dirección

class Director:
    def __init__(self, args):
        self.args = args
        sc = bpy.context.scene
        self.sc = sc
        self.lights = Lights()
        self.hot = link(bpy.data.objects.new("PuntoDolor", None))
        self.skin = skin_material(self.hot)
        self.shorts = cloth_material("Pantalon", (0.018, 0.022, 0.04), self.hot, knit=1100.0, sheen=0.35)
        self.shirt = cloth_material("Camiseta", (0.16, 0.165, 0.17), self.hot)
        self.eyes = eye_material(self.hot)
        self.hair = hair_material()
        self.mats = [self.skin, self.shorts, self.shirt, self.eyes]
        self.anat = Anatomy()
        self.fig = Humano(self.skin, self.shorts, self.shirt, self.eyes, self.hair)
        # las posturas de pie se diseñaron con la pelvis a 0.93 m
        dz = self.fig.pel0.z - 0.93
        for p in POSES.values():
            x, y, z = p["root"]
            p["root"] = (x, y, z + dz)
        self.set = Set()
        cam = bpy.data.cameras.new("Camara")
        cam.sensor_width = 36
        self.cam = link(bpy.data.objects.new("Camara", cam))
        sc.camera = self.cam
        self.anchors = {}

    # -- utilidades por plano
    def frame_figure(self, p, anatomy_xray=False):
        F = self.fig.solve(p)
        self.fig.apply(self.fig.elements())
        P = F["pelvis"]
        # cabeza femoral derecha en el maniquí -> trocánter aproximado
        hipR = F["hipR"]
        gt = hipR @ Vector((-0.055, 0.012, -0.03))
        self.hot.location = gt
        pil = self.set.bed[2]
        if not pil.hide_render:
            # la almohada se coloca bajo la cabeza y rellena el hueco hasta el colchón
            hc = F["head"] @ Vector((0, -0.01, 0.10))
            low = hc.z - 0.07
            h = max(0.04, low - self.set.bed_top + 0.012)
            pil.location = (hc.x, hc.y, self.set.bed_top + h / 2 - 0.01)
            pil.scale = (1.0, 1.0, h / 0.12)
        if anatomy_xray:
            rp = P.to_3x3().inverted() @ hipR.to_3x3()
            rl = P.to_3x3().inverted() @ F["hipL"].to_3x3()
            self.anat.place(P, rp.to_4x4(), rl.to_4x4())
        return F, gt

    def camera(self, loc, target, lens=50, fstop=4.0, roll=0.0, t=0.0, shake=1.0):
        # pequeño movimiento de cámara en mano
        s = 0.004 * shake
        loc = Vector(loc) + Vector((s * math.sin(1.3 * t), s * math.sin(0.9 * t + 1), s * math.sin(1.1 * t + 2)))
        look_at(self.cam, loc, target, roll)
        self.cam.data.lens = lens
        self.cam.data.dof.use_dof = True
        self.cam.data.dof.focus_distance = (Vector(target) - loc).length
        self.cam.data.dof.aperture_fstop = fstop

    def heat(self, h, c=0.0):
        for m in self.mats:
            set_val(m, "HEAT", h)
            set_val(m, "COOL", c)

    def xray(self, x):
        for m in self.mats:
            set_val(m, "XRAY", x)
        self.fig.body.modifiers["Pelo"].show_render = x < 0.3

    def anchor(self, name, world):
        co = world_to_camera_view(self.sc, self.cam, world)
        self.anchors[name] = (round(co.x, 4), round(1 - co.y, 4), round(co.z, 3))

    # -- planos
    def setup_frame(self, f):
        t = f / FPS
        name, a, b = shot_of(t)
        u = (t - a) / (b - a)
        self.anchors = {"shot": name}
        fig, anat, st, L = self.fig, self.anat, self.set, self.lights
        fig.set_visible(True)
        anat.set_visible(False)
        self.xray(0.0)
        anat.set("GLOW", 0.0)
        anat.set("HEAT", 0.0)
        anat.set("COOL", 0.0)
        anat.set("ALPHA", 1.0)
        self.heat(0.0)
        L.bg.inputs[1].default_value = 1.0
        getattr(self, "shot_" + name)(t, a, b, u)
        return name

    def shot_gancho(self, t, a, b, u):
        st = self.set
        st.show("floor", "bed", "dust")
        p = rest_on(self.fig, dict(POSES["tumbadoD"]), st.bed_top, 0.03)
        F, gt = self.frame_figure(p)
        h = ease(t, 0.45, 0.9) * (0.75 + 0.25 * pulse(t, 1.3))
        self.heat(h * 1.2)
        body = F["pelvis"].translation + Vector((-0.25, 0, 0.0))
        k = smooth(u)
        far = body + Vector((0.45, 2.3, 1.45))
        near = gt + Vector((0.5, 1.1, 0.32))
        self.camera(far.lerp(near, k), body.lerp(gt + Vector((0, 0, 0.03)), k),
                    lens=lerp(30, 45, k), fstop=lerp(5.6, 3.2, k), t=t)
        self.lights.setup(gt, key=(-1.0, 1.8, 2.0), rim=(1.2, -1.8, 1.4), ek=380, er=420, ef=40)
        st.place_dust(gt, t, 1.4)
        self.anchor("dolor", gt)

    def _pose_shot(self, t, u, pose_name, cam_from, cam_to, tgt_off=(0, 0, 0), lens=(40, 50),
                   groups=("floor", "dust"), ground=None, heat=1.0, fstop=3.2):
        st = self.set
        st.show(*groups)
        p = dict(POSES[pose_name])
        if ground is not None:
            p = rest_on(self.fig, p, ground)
        F, gt = self.frame_figure(p)
        self.heat(heat * (0.7 + 0.3 * pulse(t, 1.4)))
        k = smooth(u)
        tgt = gt + Vector(tgt_off)
        self.camera(Vector(cam_from).lerp(Vector(cam_to), k) + gt, tgt,
                    lens=lerp(lens[0], lens[1], k), fstop=fstop, t=t)
        self.lights.setup(gt)
        st.place_dust(gt, t, 1.6)
        self.anchor("dolor", gt)
        return F, gt

    def shot_escaleras(self, t, a, b, u):
        for s in self.set.stairs:
            pass
        self._pose_shot(t, u, "escalon", (-0.9, -1.7, 0.25), (-0.65, -1.3, 0.12),
                        tgt_off=(0.06, 0, -0.08), groups=("floor", "dust", "stairs"),
                        heat=ease(t, a + 0.3, a + 0.8))

    def shot_cruzar(self, t, a, b, u):
        p = dict(POSES["cruzado"])
        p = rest_on(self.fig, p, self.set.stool_top, 0.01, fams=("Tronco",))
        POSES["_tmp"] = p
        self._pose_shot(t, u, "_tmp", (-1.35, -1.2, 0.35), (-1.05, -0.95, 0.25),
                        tgt_off=(0.12, -0.12, 0.0), groups=("floor", "dust", "stool"),
                        heat=ease(t, a + 0.2, a + 0.6), lens=(38, 45))

    def shot_unapierna(self, t, a, b, u):
        self._pose_shot(t, u, "unapierna", (-1.2, -1.6, 0.05), (-0.95, -1.25, 0.0),
                        tgt_off=(0.05, 0, -0.1), heat=ease(t, a + 0.2, a + 0.6))

    def shot_rayosx(self, t, a, b, u):
        st = self.set
        st.show("floor", "dust")
        p = dict(POSES["pieX"])
        self.fig.merge = True
        F, gt = self.frame_figure(p, anatomy_xray=True)
        self.fig.merge = False
        x = ease(t, a + 0.3, a + 1.3)
        self.xray(x)
        self.anat.set_visible(x > 0.01, left=True)
        self.anat.set("ALPHA", x)
        self.anat.set("ALPHA", 0.0 if x < 0.01 else 0.25 * x, ["gluteus_maximus_right", "gluteus_maximus_left"])
        h = ease(t, 12.75, 13.3) * (0.75 + 0.25 * pulse(t, 1.4))
        self.anat.set("HEAT", h * 1.2)
        self.heat(0.0)
        k = smooth(u)
        hipc = F["pelvis"] @ Vector((0, 0, 0))
        self.camera(Vector((-1.25, -2.4, 0.15)).lerp(Vector((-0.55, -0.85, 0.05)), k) + hipc,
                    hipc + Vector((lerp(0.0, -0.13, k), 0, lerp(0.05, -0.03, k))),
                    lens=lerp(40, 55, k), fstop=lerp(4.0, 3.2, k), t=t)
        self.lights.setup(hipc, ek=300, er=600, ef=30)
        st.place_dust(hipc, t, 1.5)
        self.anchor("trocanter", self.anat.gt_empty.matrix_world.translation)

    def _anat_closeup(self, t, center, dist, yaw, pitch, lens=60, fstop=5.6, show_left=False, off=(-0.11, 0.03, 0.0)):
        self.fig.set_visible(False)
        self.set.show("dust")
        self.anat.place(T(*center))
        self.anat.set_visible(True, left=show_left)
        tgt = Vector(center) + Vector(off)
        d = Vector((math.cos(math.radians(pitch)) * math.sin(math.radians(yaw)),
                    -math.cos(math.radians(pitch)) * math.cos(math.radians(yaw)),
                    math.sin(math.radians(pitch))))
        self.camera(tgt + d * dist, tgt, lens=lens, fstop=fstop, t=t, shake=0.15)
        self.lights.setup(tgt, key=(-0.7, -0.9, 0.9), rim=(0.6, 0.8, 0.6), fill=(-1.0, 0.2, 0.2),
                          ek=70, er=90, ef=12, scale=0.5)
        self.set.place_dust(tgt, t, 0.35)
        return tgt

    def shot_anatomia(self, t, a, b, u):
        center = Vector((0, 0, 1.0))
        an = self.anat
        an.set("ALPHA", 0.0, ["gluteus_maximus_right"])
        self.fig.set_visible(False)
        st = self.set
        st.show("dust", "slab")
        an.set_visible(True, left=False)
        # la pelvis gira sobre el trocánter hasta quedar tumbada sobre el lado derecho
        lie = ease(t, 19.45, 20.45)
        rot = Quaternion().slerp(ROT_LIE_R.to_quaternion(), lie).to_matrix().to_4x4()
        g_local = an.gt - an.center
        gt0 = center + g_local
        c = gt0 - rot.to_3x3() @ g_local
        an.place(T(*c) @ rot)
        # colchón que sube hasta apoyar en la cadera y se hunde un poco
        push = ease(t, 19.9, 20.6)
        squash = 0.006 * push * (0.5 + 0.5 * math.sin(t * 4.0))
        st.slab.location = gt0 + Vector((0.12, 0.05, -0.008 - 0.08 - 0.35 * (1 - push) + squash))
        st.slab.hide_render = push < 0.001
        # cámara: órbita lateral y paso a vista frontal
        o = ease(t, 19.2, 20.5)
        yaw = -62 + 6 * math.sin(t * 0.3)
        d = Vector((math.sin(math.radians(yaw)), -math.cos(math.radians(yaw)), 0.14)).normalized()
        tgt_a = center + Vector((-0.11, 0.03, 0.0))
        loc_a = tgt_a + d * lerp(0.78, 0.64, ease(t, a, 19.2))
        tgt_b = gt0 + Vector((0.03, 0.0, 0.07))
        loc_b = tgt_b + Vector((0.08, -0.62, 0.12))
        self.camera(loc_a.lerp(loc_b, o), tgt_a.lerp(tgt_b, o), lens=60, fstop=5.6, t=t, shake=0.15)
        self.lights.setup(tgt_a.lerp(tgt_b, o), key=(-0.7, -0.9, 0.9), rim=(0.6, 0.8, 0.6),
                          fill=(-1.0, 0.2, 0.2), ek=70, er=90, ef=12, scale=0.5)
        st.place_dust(tgt_a, t, 0.35)
        an.set("GLOW", ease(t, 15.0, 15.4) * (1 - ease(t, 15.95, 16.3)), ["gluteus_medius_right"])
        an.set("GLOW", ease(t, 16.05, 16.4) * (1 - ease(t, 17.4, 17.8)), ["gluteus_minimus_right"])
        h = ease(t, 17.9, 18.4) * 0.55 + ease(t, 20.3, 21.9) * 0.9
        an.set("HEAT", h * (0.8 + 0.2 * pulse(t, 1.6)))
        self.anchor("medio", an.med_anchor.matrix_world.translation)
        self.anchor("menor", an.min_anchor.matrix_world.translation)
        self.anchor("trocanter", an.gt_empty.matrix_world.translation)

    def shot_noche(self, t, a, b, u):
        st = self.set
        st.show("floor", "bed", "dust")
        p = rest_on(self.fig, dict(POSES["tumbadoD"]), st.bed_top, 0.035)
        F, gt = self.frame_figure(p)
        self.heat((0.6 + 0.6 * ease(t, a, b)) * (0.75 + 0.25 * pulse(t, 1.1)))
        k = smooth(u)
        body = F["pelvis"].translation + Vector((-0.3, 0, 0))
        self.camera(body + Vector((0.6, 1.9, 1.7)).lerp(Vector((0.35, 1.45, 1.25)), k),
                    body.lerp(gt, k * 0.6), lens=32, fstop=5.0, t=t, shake=0.5)
        self.lights.setup(gt, key=(-1.0, 1.8, 2.0), rim=(1.2, -1.8, 1.4), er=120, night=True)
        self.lights.bg.inputs[1].default_value = 0.3
        st.place_dust(gt, t, 1.4)
        self.anchor("dolor", gt)

    def shot_tres(self, t, a, b, u):
        # rótulo 2D: se usa un fotograma del maniquí como fondo
        self.shot_rayosx(t, 11.65, 14.30, 0.0)

    def shot_error1(self, t, a, b, u):
        st = self.set
        st.show("floor", "bed", "dust", "pillow")
        roll = ease(t, 31.55, 32.55)
        ang = -180.0 * roll
        A, B = POSES["tumbadoD"], POSES["tumbadoI"]
        p = mix_pose(A, B, ease(t, 31.55, 32.55))
        p["rot"] = R("X", ang) @ ROT_LIE_R
        p = rest_on(self.fig, p, st.bed_top, 0.03)
        F, gt = self.frame_figure(p)
        hot = 1.0 - ease(t, 32.0, 33.2)
        self.heat(1.3 * hot * (0.7 + 0.3 * pulse(t, 1.5)), 0.9 * ease(t, 33.0, 34.0))
        kR, kL = F["kneeR"].translation, F["kneeL"].translation
        pil = ease(t, 32.5, 33.1)
        st.pillow.location = (kR + kL) / 2 + Vector((0, 0, 0.0))
        st.pillow.rotation_euler = (0, 0, 0)
        st.pillow.scale = (pil, pil, max(pil, 0.001))
        st.pillow.hide_render = pil < 0.01
        # cámara: frontal mientras está sobre el lado derecho, desde el otro lado al final
        hipc = F["pelvis"].translation
        k = smooth(u)
        loc = Vector((0.4, 2.0, 1.15)).lerp(Vector((0.25, 1.7, 1.0)), k)
        self.camera(hipc + loc, hipc + Vector((0.1, 0, -0.05)), lens=35, fstop=4.0, t=t)
        self.lights.setup(hipc, key=(-1.2, 1.8, 2.2), rim=(1.4, -1.8, 1.6))
        st.place_dust(hipc, t, 1.5)
        self.anchor("dolor", gt)

    def shot_error2(self, t, a, b, u):
        if t < 37.2:
            uu = (t - a) / (37.2 - a)
            self.shot_cruzar(t, a, 37.2, uu)
        else:
            uu = (t - 37.2) / (b - 37.2)
            self._pose_shot(t, uu, "colgado", (-0.95, -1.85, 0.2), (-0.75, -1.5, 0.15),
                            tgt_off=(0.08, 0, 0.05), lens=(32, 36), heat=ease(t, 37.4, 37.9) * 1.1)

    def shot_error3(self, t, a, b, u):
        if t < 42.9:
            st = self.set
            st.show("floor", "dust", "mat")
            pull = ease(t, 39.5, 40.9)
            p = mix_pose(POSES["supino"], POSES["estiramiento"], pull)
            p = rest_on(self.fig, p, st.mat_top)
            F, gt = self.frame_figure(p)
            self.heat((0.25 + 1.05 * ease(t, 40.4, 42.0)) * (0.7 + 0.3 * pulse(t, 1.6)))
            uu = (t - a) / (42.9 - a)
            hipc = F["pelvis"].translation
            self.camera(hipc + Vector((0.35, -1.9, 1.15)).lerp(Vector((0.15, -1.25, 0.8)), smooth(uu)),
                        hipc + Vector((0.1, 0, 0.02)), lens=38, fstop=3.5, t=t)
            self.lights.setup(hipc)
            st.place_dust(hipc, t, 1.5)
            self.anchor("dolor", gt)
        else:
            # plano anatómico: aducción del fémur y compresión sobre el trocánter
            center = (0, 0, 1.0)
            an = self.anat
            an.set("ALPHA", 0.0, ["gluteus_maximus_right"])
            tgt = self._anat_closeup(t, center, 0.6, -10 + 4 * math.sin(t * 0.4), 4)
            add = 9.0 * ease(t, 43.0, 43.9)
            hipR = R("Y", add) @ R("X", -12.0 * ease(t, 43.0, 43.9))
            an.place(T(*center), hipR)
            an.set("HEAT", (0.6 + 0.9 * ease(t, 43.2, 44.3)) * (0.8 + 0.2 * pulse(t, 2.0)))
            self.anchor("trocanter", an.gt_empty.matrix_world.translation)

    def shot_solucion(self, t, a, b, u):
        st = self.set
        st.show("floor", "dust", "mat", "plate")
        # repeticiones de puente con pausa isométrica
        reps = [(45.6, 46.5, 48.6, 49.3), (49.6, 50.4, 53.4, 54.0)]
        lift = 0.0
        for up0, up1, dn0, dn1 in reps:
            lift = max(lift, ease(t, up0, up1) * (1 - ease(t, dn0, dn1)))
        p = bridge_pose(self.fig, lift, st.mat_top)
        F, gt = self.frame_figure(p)
        self.heat(0.0, (0.35 + 0.65 * ease(t, 46.5, 48.0)) * (0.8 + 0.2 * pulse(t, 0.9)))
        P = F["pelvis"]
        plate = ease(t, 50.9, 51.5)
        st.plate.hide_render = plate < 0.01
        top = P @ Vector((0, -0.17, 0.0))
        st.plate.location = top + Vector((0, 0, 0.6 * (1 - plate)))
        st.plate.rotation_mode = "QUATERNION"
        st.plate.rotation_quaternion = P.to_quaternion() @ Quaternion((1, 0, 0), math.radians(90))
        hipc = P.translation
        self.camera(hipc + Vector((0.1, -2.1, 0.75)).lerp(Vector((0.05, -1.6, 0.55)), smooth(u)),
                    hipc + Vector((-0.12, 0, -0.02)), lens=32, fstop=5.0, t=t)
        self.lights.setup(hipc)
        st.place_dust(hipc, t, 1.5)
        self.anchor("dolor", gt)

    def shot_cierre(self, t, a, b, u):
        center = (0, 0, 1.0)
        an = self.anat
        an.set("ALPHA", 0.18, ["gluteus_maximus_right", "gluteus_maximus_left"])
        yaw = -70 + 95 * smooth(u)
        self._anat_closeup(t, center, 0.95, yaw, 10, lens=50, show_left=True, off=(-0.01, 0.06, 0.05))
        an.set("COOL", 0.9 * (0.8 + 0.2 * pulse(t, 0.8)))
        self.anchor("trocanter", an.gt_empty.matrix_world.translation)


# ------------------------------------------------------------------ render

def configure(args):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = args.samples
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.05
    sc.cycles.use_denoising = True
    sc.cycles.denoiser = "OPENIMAGEDENOISE"
    sc.cycles.max_bounces = 6
    sc.cycles.diffuse_bounces = 2
    sc.cycles.glossy_bounces = 2
    sc.cycles.transmission_bounces = 4
    sc.cycles.transparent_max_bounces = 12
    sc.cycles.caustics_reflective = False
    sc.cycles.caustics_refractive = False
    sc.cycles.blur_glossy = 1.0
    sc.render.use_persistent_data = True
    sc.render.resolution_x = 1080
    sc.render.resolution_y = 1920
    sc.render.resolution_percentage = args.res
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast"
    sc.view_settings.exposure = 0.0
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_depth = "8"
    sc.render.fps = FPS


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--frames", default=f"0-{N_FRAMES - 1}")
    ap.add_argument("--still", type=int, nargs="*")
    ap.add_argument("--samples", type=int, default=48)
    ap.add_argument("--res", type=int, default=100)
    args = ap.parse_args(argv)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    configure(args)
    d = Director(args)
    os.makedirs(args.out, exist_ok=True)
    if args.still:
        frames = args.still
    else:
        a, b = map(int, args.frames.split("-"))
        frames = range(a, b + 1)
    anchors_path = os.path.join(args.out, "anclas.json")
    anchors = json.load(open(anchors_path)) if os.path.exists(anchors_path) else {}
    import time
    for f in frames:
        t0 = time.time()
        name = d.setup_frame(f)
        anchors[str(f)] = d.anchors
        if name == "tres":
            continue
        d.sc.render.filepath = os.path.join(args.out, f"f_{f:04d}.png")
        bpy.ops.render.render(write_still=True)
        print(f"FRAME {f} {name} {time.time() - t0:.1f}s", flush=True)
        with open(anchors_path, "w") as fh:
            json.dump(anchors, fh)


if __name__ == "__main__":
    main()
