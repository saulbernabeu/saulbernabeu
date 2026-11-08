"""Escena 3D: rotura de la polea A2 en un dedo de escalador.

Uso:
    python escena_poleas.py --out frames/ [--samples 128] [--res 100] [--frames 1-240] [--still 150]

Construye la escena desde cero con bpy (Blender como módulo de Python) y la
renderiza con Cycles.
"""
import argparse
import math
import os
import sys

import bpy
import bmesh
from mathutils import Matrix, Vector

FPS = 24
FRAME_END = 240

# Posiciones de las articulaciones (en reposo, dedo estirado a lo largo de +X)
MCP, PIP, DIP, TIP = 0.0, 4.5, 7.2, 8.9
X_START = -6.0

# Ángulos de flexión en la posición de arqueo (grados)
CRIMP = {"P1": 30.0, "P2": 100.0, "P3": -25.0}

# Momentos clave de la animación (fotogramas)
F_FADE = (30, 70)      # la piel se vuelve translúcida
F_FLEX = (60, 118)     # el dedo pasa a arqueo
F_TENSE = (110, 140)   # la A2 se carga de tensión
F_SNAP = 140           # rotura
F_BOW = (140, 150)     # el tendón se separa del hueso


# ---------------------------------------------------------------- utilidades

def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def new_obj(name, data):
    ob = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def shade_smooth(me):
    for p in me.polygons:
        p.use_smooth = True


def add_subsurf(ob, view=1, render=2):
    m = ob.modifiers.new("Subsurf", "SUBSURF")
    m.levels = view
    m.render_levels = render
    return m


def tube_mesh(name, xs, radius, ry=1.0, rz=1.0, zoff=lambda x: 0.0, segs=48,
              cap_start=True, cap_end=True):
    """Superficie de revolución a lo largo de X con sección elíptica."""
    bm = bmesh.new()
    rings = []
    for x in xs:
        r = radius(x)
        ring = []
        for i in range(segs):
            a = 2 * math.pi * i / segs
            ring.append(bm.verts.new((x, r * ry * math.cos(a), zoff(x) + r * rz * math.sin(a))))
        rings.append(ring)
    for a, b in zip(rings, rings[1:]):
        for i in range(segs):
            j = (i + 1) % segs
            bm.faces.new((a[i], a[j], b[j], b[i]))
    if cap_start:
        c = bm.verts.new((xs[0], 0, zoff(xs[0])))
        for i in range(segs):
            bm.faces.new((c, rings[0][(i + 1) % segs], rings[0][i]))
    if cap_end:
        c = bm.verts.new((xs[-1], 0, zoff(xs[-1])))
        for i in range(segs):
            bm.faces.new((c, rings[-1][i], rings[-1][(i + 1) % segs]))
    me = bpy.data.meshes.new(name)
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    shade_smooth(me)
    return me


def cos_space(a, b, n):
    """Puntos más densos en los extremos (para tapas redondeadas)."""
    return [a + (b - a) * (1 - math.cos(math.pi * i / (n - 1))) / 2 for i in range(n)]


def cap(x, x0, x1, c):
    """Factor que lleva el radio a 0 de forma redondeada en los extremos."""
    f = 1.0
    if x0 is not None and x - x0 < c:
        t = max(0.0, (x - x0) / c)
        f *= math.sqrt(max(0.0, t * (2 - t)))
    if x1 is not None and x1 - x < c:
        t = max(0.0, (x1 - x) / c)
        f *= math.sqrt(max(0.0, t * (2 - t)))
    return f


# ---------------------------------------------------------------- materiales

def principled(name, color, rough=0.5, sss=0.0, sss_radius=(1, 0.4, 0.25),
               sss_scale=0.1, coat=0.0, sheen=0.0, spec=0.5):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Subsurface Weight"].default_value = sss
    b.inputs["Subsurface Radius"].default_value = sss_radius
    b.inputs["Subsurface Scale"].default_value = sss_scale
    b.inputs["Coat Weight"].default_value = coat
    b.inputs["Sheen Weight"].default_value = sheen
    b.inputs["Specular IOR Level"].default_value = spec
    return mat, b


def add_noise_bump(mat, bsdf, scale=40.0, strength=0.15, detail=8.0):
    nt = mat.node_tree
    tex = nt.nodes.new("ShaderNodeTexNoise")
    tex.inputs["Scale"].default_value = scale
    tex.inputs["Detail"].default_value = detail
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = strength
    bump.inputs["Distance"].default_value = 0.02
    nt.links.new(tex.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return tex


def make_fadeable(mat, bsdf, rim=0.35):
    """Mezcla el BSDF con transparencia según un valor animable ('opacity').

    Los bordes (incidencia rasante) se mantienen algo más opacos para que la
    piel translúcida conserve la silueta del dedo.
    """
    nt = mat.node_tree
    out = nt.nodes["Material Output"]
    op = nt.nodes.new("ShaderNodeValue")
    op.name = "opacity"
    op.outputs[0].default_value = 1.0
    lw = nt.nodes.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.45
    inv = nt.nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    nt.links.new(op.outputs[0], inv.inputs[1])
    rimm = nt.nodes.new("ShaderNodeMath")
    rimm.operation = "MULTIPLY"
    nt.links.new(lw.outputs["Facing"], rimm.inputs[0])
    nt.links.new(inv.outputs[0], rimm.inputs[1])
    rimk = nt.nodes.new("ShaderNodeMath")
    rimk.operation = "MULTIPLY"
    rimk.inputs[1].default_value = rim
    nt.links.new(rimm.outputs[0], rimk.inputs[0])
    fac = nt.nodes.new("ShaderNodeMath")
    fac.operation = "ADD"
    fac.use_clamp = True
    nt.links.new(op.outputs[0], fac.inputs[0])
    nt.links.new(rimk.outputs[0], fac.inputs[1])
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(fac.outputs[0], mix.inputs[0])
    nt.links.new(tr.outputs[0], mix.inputs[1])
    nt.links.new(bsdf.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    return op


def key_value(node, frame, value):
    node.outputs[0].default_value = value
    node.outputs[0].keyframe_insert("default_value", frame=frame)


# ---------------------------------------------------------------- escena

def build():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.fps = FPS
    sc.frame_start = 1
    sc.frame_end = FRAME_END

    # --- Mundo: estudio oscuro con un leve degradado
    world = bpy.data.worlds.new("Mundo")
    sc.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.012, 0.016, 0.024, 1)
    bg.inputs["Strength"].default_value = 1.0

    # Fondo curvo (ciclorama) para que la luz tenga dónde caer
    bpy.ops.mesh.primitive_plane_add(size=80, location=(3, 18, -6))
    back = bpy.context.active_object
    back.rotation_euler = (math.radians(90), 0, 0)
    mback, bb = principled("Fondo", (0.035, 0.045, 0.06), rough=0.9)
    back.data.materials.append(mback)

    # --- Armadura (esqueleto que deforma la piel)
    arm_data = bpy.data.armatures.new("Esqueleto")
    arm = new_obj("Esqueleto", arm_data)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    segs = [("MC", X_START, MCP), ("P1", MCP, PIP), ("P2", PIP, DIP), ("P3", DIP, TIP)]
    prev = None
    for name, a, b in segs:
        eb = arm_data.edit_bones.new(name)
        eb.head = (a, 0, 0)
        eb.tail = (b, 0, 0)
        eb.roll = 0
        if prev:
            eb.parent = prev
            eb.use_connect = True
        prev = eb
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"

    # Comprobar qué signo de rotación flexiona el dedo hacia la palma
    pb = arm.pose.bones["P1"]
    pb.rotation_euler = (math.radians(30), 0, 0)
    bpy.context.view_layer.update()
    tail_z = (arm.matrix_world @ pb.tail).z
    pb.rotation_euler = (0, 0, 0)
    flex_sign = 1.0 if tail_z < 0 else -1.0

    # --- Materiales
    m_bone, b_bone = principled("Hueso", (0.86, 0.80, 0.68), rough=0.55, sss=0.25,
                                sss_radius=(1, 0.7, 0.5), sss_scale=0.05)
    add_noise_bump(m_bone, b_bone, scale=25, strength=0.08)
    m_cart, b_cart = principled("Cartilago", (0.80, 0.84, 0.88), rough=0.2, sss=0.3,
                                sss_scale=0.03, coat=0.3)
    m_tendon, b_tendon = principled("Tendon", (0.93, 0.88, 0.76), rough=0.32, sss=0.35,
                                    sss_radius=(1, 0.8, 0.6), sss_scale=0.04, sheen=0.4,
                                    coat=0.2)
    tex_t = add_noise_bump(m_tendon, b_tendon, scale=8, strength=0.25, detail=12)
    # Fibras longitudinales del tendón: estirar el ruido a lo largo de la curva
    mapping = m_tendon.node_tree.nodes.new("ShaderNodeMapping")
    coord = m_tendon.node_tree.nodes.new("ShaderNodeTexCoord")
    mapping.inputs["Scale"].default_value = (0.5, 12, 12)
    m_tendon.node_tree.links.new(coord.outputs["Object"], mapping.inputs["Vector"])
    m_tendon.node_tree.links.new(mapping.outputs["Vector"], tex_t.inputs["Vector"])

    def pulley_mat(name):
        m, b = principled(name, (0.10, 0.38, 0.95), rough=0.35, sss=0.3, sss_scale=0.03,
                          sheen=0.5, coat=0.3)
        b.inputs["Emission Color"].default_value = (1.0, 0.08, 0.04, 1)
        b.inputs["Emission Strength"].default_value = 0.0
        add_noise_bump(m, b, scale=30, strength=0.2)
        return m, b

    m_a2, b_a2 = pulley_mat("PoleaA2")
    m_a4, b_a4 = pulley_mat("PoleaA4")

    m_skin, b_skin = principled("Piel", (0.80, 0.56, 0.45), rough=0.45, sss=0.6,
                                sss_radius=(1.0, 0.35, 0.2), sss_scale=0.25, sheen=0.15)
    add_noise_bump(m_skin, b_skin, scale=60, strength=0.12)
    op_skin = make_fadeable(m_skin, b_skin)
    m_nail, b_nail = principled("Una", (0.93, 0.75, 0.70), rough=0.15, sss=0.3,
                                sss_scale=0.05, coat=0.8)
    op_nail = make_fadeable(m_nail, b_nail, rim=0.2)

    # --- Huesos
    def phalanx(name, x0, x1, r_shaft, r_end0, r_end1, mat):
        L = x1 - x0
        g = 0.06  # pequeño espacio articular
        a, b = x0 + g, x1 - g

        def r(x):
            u0 = (x - a) / 0.7
            u1 = (b - x) / 0.7
            base = r_shaft + (r_end0 - r_shaft) * math.exp(-u0 * u0) \
                + (r_end1 - r_shaft) * math.exp(-u1 * u1)
            return base * cap(x, a, b, 0.28)

        xs = cos_space(a, b, 60) if L < 3 else sorted(set(
            cos_space(a, a + 1.0, 20) + [a + 1.0 + (L - 2.0 - 2 * g) * i / 20 for i in range(21)]
            + cos_space(b - 1.0, b, 20)))
        me = tube_mesh(name, xs, r, ry=1.12, rz=0.88, segs=40)
        ob = new_obj(name, me)
        ob.data.materials.append(mat)
        add_subsurf(ob, 1, 2)
        return ob

    bones = {
        "MC": phalanx("Metacarpiano", X_START - 2, MCP, 0.40, 0.42, 0.56, m_bone),
        "P1": phalanx("Falange_proximal", MCP, PIP, 0.34, 0.50, 0.44, m_bone),
        "P2": phalanx("Falange_media", PIP, DIP, 0.30, 0.42, 0.36, m_bone),
        "P3": phalanx("Falange_distal", DIP, TIP, 0.24, 0.36, 0.30, m_bone),
    }

    def parent_to_bone(ob, bone):
        world = ob.matrix_world.copy()
        ob.parent = arm
        ob.parent_type = "BONE"
        ob.parent_bone = bone
        bpy.context.view_layer.update()
        ob.matrix_world = world

    for bn, ob in bones.items():
        parent_to_bone(ob, bn)

    # Cartílago articular: pequeñas lentes brillantes en cada articulación
    for bn, x in (("P1", MCP), ("P2", PIP), ("P3", DIP)):
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.33, location=(x + 0.02, 0, 0),
                                             segments=32, ring_count=16)
        c = bpy.context.active_object
        c.scale = (0.16, 0.8, 0.7)
        c.data.materials.append(m_cart)
        shade_smooth(c.data)
        bpy.context.view_layer.update()
        parent_to_bone(c, bn)

    # --- Piel
    def skin_r(x):
        t = (x - X_START) / (TIP - X_START)
        r = 1.05 - 0.30 * t
        for j, h in ((MCP, 0.10), (PIP, 0.07), (DIP, 0.05)):
            r += h * math.exp(-((x - j) / 0.55) ** 2)
        return r * cap(x, None, TIP + 0.62, 0.95)

    xs = [X_START - 2 + (TIP + 0.62 - X_START + 2) * i / 220 for i in range(221)]
    xs = sorted(set(xs[:-12] + cos_space(xs[-12], TIP + 0.62, 24)))
    skin_me = tube_mesh("Piel", xs, skin_r, ry=1.0, rz=0.92,
                        zoff=lambda x: -0.12, segs=64, cap_start=False)
    skin = new_obj("Piel", skin_me)
    skin.data.materials.append(m_skin)
    # Pesos de deformación según la posición a lo largo del dedo
    groups = {n: skin.vertex_groups.new(name=n) for n in ("MC", "P1", "P2", "P3")}
    w = 0.45
    for v in skin.data.vertices:
        x = v.co.x
        s1 = smooth((x - (MCP - w)) / (2 * w))
        s2 = smooth((x - (PIP - w)) / (2 * w))
        s3 = smooth((x - (DIP - w)) / (2 * w))
        ws = {"MC": 1 - s1, "P1": s1 * (1 - s2), "P2": s2 * (1 - s3), "P3": s3}
        for n, val in ws.items():
            if val > 1e-4:
                groups[n].add([v.index], val, "REPLACE")
    mod = skin.modifiers.new("Armadura", "ARMATURE")
    mod.object = arm
    mod.use_deform_preserve_volume = True
    add_subsurf(skin, 1, 2)

    # Uña
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(TIP - 0.3, 0, 0.47),
                                         segments=48, ring_count=24)
    nail = bpy.context.active_object
    nail.scale = (0.8, 0.5, 0.06)
    nail.rotation_euler = (0, math.radians(6), 0)
    nail.data.materials.append(m_nail)
    shade_smooth(nail.data)
    bpy.context.view_layer.update()
    parent_to_bone(nail, "P3")

    # --- Tendón flexor (curva enganchada a empties que siguen a cada hueso)
    tz = -0.55
    pts = [
        ("MC", (X_START - 2, 0, tz)), ("MC", (-3.0, 0, tz)), ("MC", (-1.2, 0, tz - 0.03)),
        ("MC", (-0.25, 0, tz - 0.12)),
        ("P1", (0.55, 0, tz - 0.08)), ("P1", (1.4, 0, tz)), ("P1", (2.3, 0, tz)),
        ("P1", (3.2, 0, tz)), ("P1", (4.05, 0, tz - 0.1)),
        ("P2", (PIP + 0.45, 0, tz - 0.08)), ("P2", (PIP + 1.3, 0, tz + 0.02)),
        ("P2", (PIP + 2.1, 0, tz + 0.04)),
        ("P3", (DIP + 0.35, 0, tz + 0.1)), ("P3", (DIP + 0.7, 0, -0.38)),
    ]
    cu = bpy.data.curves.new("Tendon", "CURVE")
    cu.dimensions = "3D"
    cu.resolution_u = 32
    cu.render_resolution_u = 48
    cu.bevel_depth = 0.17
    cu.bevel_resolution = 8
    sp = cu.splines.new("NURBS")
    sp.points.add(len(pts) - 1)
    for p, (_, co) in zip(sp.points, pts):
        p.co = (*co, 1)
    sp.order_u = 4
    sp.use_endpoint_u = True
    tendon = new_obj("Tendon", cu)
    tendon.data.materials.append(m_tendon)
    hooks = []
    for i, (bn, co) in enumerate(pts):
        e = new_obj(f"T_{i:02d}", None)
        e.empty_display_size = 0.1
        e.location = co
        bpy.context.view_layer.update()
        e.parent = bones[bn]
        e.matrix_parent_inverse = bones[bn].matrix_world.inverted()
        h = tendon.modifiers.new(f"Hook{i}", "HOOK")
        h.object = e
        h.vertex_indices_set([i])
        hooks.append((bn, e))
    tendon.data.taper_radius_mode = "OVERRIDE"

    # --- Poleas
    def pulley_half(name, xc, width, zc, r, a0, a1, mat):
        """Medio arco que abraza el tendón; el origen queda en su anclaje al hueso."""
        pivot = Vector((xc, r * math.cos(math.radians(a0)), zc + r * math.sin(math.radians(a0))))
        bm = bmesh.new()
        nu, nx = 28, 10
        grid = []
        for ix in range(nx):
            x = -width / 2 + width * ix / (nx - 1)
            row = []
            for iu in range(nu):
                a = math.radians(a0 + (a1 - a0) * iu / (nu - 1))
                # el borde libre se abomba un poco, como una banda de fibras
                bulge = 1 + 0.06 * math.sin(math.pi * ix / (nx - 1))
                p = Vector((xc + x, r * bulge * math.cos(a), zc + r * bulge * math.sin(a)))
                row.append(bm.verts.new(p - pivot))
            grid.append(row)
        for ix in range(nx - 1):
            for iu in range(nu - 1):
                f = (grid[ix][iu], grid[ix][iu + 1], grid[ix + 1][iu + 1], grid[ix + 1][iu])
                bm.faces.new(f if a1 > a0 else f[::-1])
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        shade_smooth(me)
        ob = new_obj(name, me)
        ob.location = pivot
        sol = ob.modifiers.new("Grosor", "SOLIDIFY")
        sol.thickness = 0.09
        sol.offset = 1.0
        add_subsurf(ob, 1, 2)
        ob.data.materials.append(mat)
        return ob

    a2c, a2w = 2.3, 1.7
    a2L = pulley_half("A2_izq", a2c, a2w, tz, 0.27, 120, 270, m_a2)
    a2R = pulley_half("A2_der", a2c, a2w, tz, 0.27, 60, -90, m_a2)
    a4L = pulley_half("A4_izq", PIP + 1.3, 0.8, tz + 0.04, 0.25, 125, 270, m_a4)
    a4R = pulley_half("A4_der", PIP + 1.3, 0.8, tz + 0.04, 0.25, 55, -90, m_a4)
    for ob, bn in ((a2L, "P1"), (a2R, "P1"), (a4L, "P2"), (a4R, "P2")):
        bpy.context.view_layer.update()
        ob.parent = bones[bn]
        ob.matrix_parent_inverse = bones[bn].matrix_world.inverted()

    # ------------------------------------------------------------ animación
    def key_pose(frame, amount):
        for bn in ("P1", "P2", "P3"):
            pb = arm.pose.bones[bn]
            pb.rotation_euler = (flex_sign * math.radians(CRIMP[bn] * amount), 0, 0)
            pb.keyframe_insert("rotation_euler", frame=frame)

    key_pose(1, 0)
    key_pose(F_FLEX[0], 0)
    key_pose(F_FLEX[1], 1)
    # pequeño "tirón" justo en la rotura
    key_pose(F_SNAP, 1)
    for bn, extra in (("P1", 3), ("P2", 4)):
        pb = arm.pose.bones[bn]
        pb.rotation_euler = (flex_sign * math.radians(CRIMP[bn] + extra), 0, 0)
        pb.keyframe_insert("rotation_euler", frame=F_SNAP + 3)
    key_pose(F_SNAP + 12, 1)
    key_pose(FRAME_END, 1)

    # Piel y uña se vuelven translúcidas
    for node in (op_skin, op_nail):
        key_value(node, 1, 1.0)
        key_value(node, F_FADE[0], 1.0)
        key_value(node, F_FADE[1], 0.10)

    # Tensión en la A2 (brillo rojo creciente) y destello en la rotura
    em = b_a2.inputs["Emission Strength"]
    for f, v in ((F_TENSE[0], 0.0), (F_SNAP - 1, 1.5), (F_SNAP + 1, 6.0),
                 (F_SNAP + 18, 1.2), (FRAME_END, 0.8)):
        em.default_value = v
        em.keyframe_insert("default_value", frame=f)

    # Las dos mitades de la A2 se abren
    for ob, sgn in ((a2L, -1), (a2R, 1)):
        ob.rotation_euler = (0, 0, 0)
        ob.keyframe_insert("rotation_euler", frame=F_SNAP)
        ob.rotation_euler = (sgn * math.radians(78), 0, 0)
        ob.keyframe_insert("rotation_euler", frame=F_SNAP + 5)
        ob.rotation_euler = (sgn * math.radians(68), 0, 0)
        ob.keyframe_insert("rotation_euler", frame=F_SNAP + 14)

    # Efecto cuerda de arco: el tendón se separa de la falange proximal hacia
    # la palma (perfil máximo cerca de la articulación media) y abomba la piel
    lift = {0.55: 0.15, 1.4: 0.36, 2.3: 0.50, 3.2: 0.52, 4.05: 0.32}
    for bn, e in hooks:
        if bn != "P1":
            continue
        rest_loc = e.location.copy()
        d = lift[round(rest_loc.x, 2)]
        e.keyframe_insert("location", frame=F_BOW[0])
        e.location = rest_loc + Vector((0, 0, -d * 1.15))
        e.keyframe_insert("location", frame=F_BOW[1] - 3)
        e.location = rest_loc + Vector((0, 0, -d))
        e.keyframe_insert("location", frame=F_BOW[1] + 4)

    skin.shape_key_add(name="Basis")
    bulge = skin.shape_key_add(name="Cuerda_de_arco")
    for v, kv in zip(skin.data.vertices, bulge.data):
        x, y, z = v.co
        if z < -0.12:
            fx = math.exp(-((x - 2.9) / 1.25) ** 2)
            fz = max(0.0, (-0.12 - z) / 0.85) ** 2
            fy = math.exp(-(y / 0.55) ** 2)
            kv.co = v.co + Vector((0, 0, -0.42 * fx * fz * fy))
    for f, v in ((F_BOW[0], 0.0), (F_BOW[1] - 3, 1.15), (F_BOW[1] + 4, 1.0)):
        bulge.value = v
        bulge.keyframe_insert("value", frame=f)
    bulge.slider_max = 1.5

    # ------------------------------------------------------------ luces
    def area(name, loc, rot, size, power, color):
        ld = bpy.data.lights.new(name, "AREA")
        ld.shape = "DISK"
        ld.size = size
        ld.energy = power
        ld.color = color
        lo = new_obj(name, ld)
        lo.location = loc
        lo.rotation_euler = [math.radians(a) for a in rot]
        return lo

    area("Principal", (-2, -9, 7), (55, 0, -15), 7, 2600, (1.0, 0.95, 0.88))
    area("Relleno", (10, -8, -4), (115, 0, 40), 8, 700, (0.75, 0.85, 1.0))
    area("Contra", (4, 8, 5), (-55, 0, 180), 5, 2200, (0.55, 0.75, 1.0))
    area("Fondo", (3, 14, -2), (-90, 0, 0), 14, 900, (0.25, 0.4, 0.7))

    red = bpy.data.lights.new("Destello", "POINT")
    red.color = (1.0, 0.15, 0.08)
    red.shadow_soft_size = 0.4
    rl = new_obj("Destello", red)
    rl.location = (a2c, -1.2, -1.0)
    rl.parent = bones["P1"]
    rl.matrix_parent_inverse = bones["P1"].matrix_world.inverted()
    for f, v in ((F_TENSE[0], 0), (F_SNAP - 1, 15), (F_SNAP + 1, 140), (F_SNAP + 20, 20),
                 (FRAME_END, 12)):
        red.energy = v
        red.keyframe_insert("energy", frame=f)

    # ------------------------------------------------------------ cámara
    target = new_obj("Objetivo", None)
    target.location = (2.6, 0, -0.6)
    rig = new_obj("Rig", None)
    rig.location = target.location
    cam_d = bpy.data.cameras.new("Camara")
    cam_d.lens = 40
    cam_d.dof.use_dof = True
    cam_d.dof.focus_object = target
    cam_d.dof.aperture_fstop = 5.6
    cam = new_obj("Camara", cam_d)
    cam.parent = rig
    cam.location = (0, -15.5, 1.4)
    tc = cam.constraints.new("TRACK_TO")
    tc.target = target
    tc.track_axis = "TRACK_NEGATIVE_Z"
    tc.up_axis = "UP_Y"
    sc.camera = cam

    def key_cam(f, rz, rx, dist, tx, tz_):
        rig.rotation_euler = (math.radians(rx), 0, math.radians(rz))
        rig.keyframe_insert("rotation_euler", frame=f)
        cam.location = (0, -dist, 1.4)
        cam.keyframe_insert("location", frame=f)
        target.location = (tx, 0, tz_)
        target.keyframe_insert("location", frame=f)

    key_cam(1, -28, -4, 15.0, 2.6, -0.3)
    key_cam(F_FLEX[0], -15, -2, 17.0, 2.6, -1.0)
    key_cam(F_FLEX[1], -5, 10, 18.0, 1.0, -2.3)
    key_cam(F_SNAP - 6, 5, 25, 12.0, 1.8, -1.6)
    key_cam(F_SNAP + 30, 12, 32, 10.0, 1.6, -1.9)
    key_cam(FRAME_END, 20, 30, 11.5, 1.6, -2.1)

    # Interpolación suave en todas las animaciones
    for a in bpy.data.actions:
        for fc in getattr(a, "fcurves", []):
            for kp in fc.keyframe_points:
                kp.interpolation = "BEZIER"
                kp.easing = "AUTO"

    # ------------------------------------------------------------ render
    r = sc.render
    r.engine = "CYCLES"
    r.resolution_x, r.resolution_y = 1920, 1080
    r.use_motion_blur = True
    r.use_persistent_data = True
    r.motion_blur_shutter = 0.5
    r.image_settings.file_format = "PNG"
    r.film_transparent = False
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast"
    cy = sc.cycles
    cy.device = "CPU"
    cy.use_denoising = True
    cy.denoiser = "OPENIMAGEDENOISE"
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = 0.01
    cy.max_bounces = 12
    cy.transparent_max_bounces = 32
    cy.transmission_bounces = 12
    cy.caustics_reflective = False
    cy.caustics_refractive = False
    return sc


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="frames")
    ap.add_argument("--samples", type=int, default=128)
    ap.add_argument("--res", type=int, default=100)
    ap.add_argument("--frames", default=None, help="rango, p. ej. 1-240")
    ap.add_argument("--still", type=int, nargs="*", default=None)
    ap.add_argument("--save", default=None, help="guardar .blend")
    a = ap.parse_args(argv)

    sc = build()
    sc.cycles.samples = a.samples
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
