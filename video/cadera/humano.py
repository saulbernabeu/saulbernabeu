"""Humano realista a partir de los datos CC0 de MakeHuman (modelo/makehuman).

Se usan solo ficheros de datos: la malla base (base.obj), los morphs de
complexión (targets), el esqueleto (rig.default.json) y los pesos
(weights.default.json). Todo se construye aquí con bpy.

Coordenadas: MakeHuman usa Y arriba y decímetros; en Blender
(x, y, z) = (x, -z, y) * 0.1. El personaje mira hacia -Y y su lado
derecho está en -X.
"""
import gzip
import json
import math
import os

import bpy
import numpy as np
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
MH = os.path.join(HERE, "modelo", "makehuman")

# complexión: hombre de ~40 años, algo atlético
MACRO = {
    "universal-male-young-averagemuscle-averageweight": 0.70 * 0.65,
    "universal-male-young-maxmuscle-averageweight": 0.70 * 0.35,
    "universal-male-old-averagemuscle-averageweight": 0.30 * 0.65,
    "universal-male-old-maxmuscle-averageweight": 0.30 * 0.35,
    "caucasian-male-young": 0.70,
    "caucasian-male-old": 0.30,
}

# hueso de MakeHuman -> articulación de la cinemática del guion
def driver_of(bone):
    b = bone
    side = "R" if b.endswith(".R") else "L"
    if b in ("root", "spine05") or b.startswith("pelvis"):
        return "pelvis"
    if b in ("spine04", "spine03"):
        return "spine"
    if b in ("spine02", "spine01") or b.startswith(("clavicle", "breast", "shoulder01")):
        return "chest"
    if b.startswith("upperleg"):
        return "hip" + side
    if b.startswith("lowerleg"):
        return "knee" + side
    if b.startswith(("foot", "toe")):
        return "ankle" + side
    if b.startswith("upperarm"):
        return "sh" + side
    if b.startswith("lowerarm"):
        return "elb" + side
    if b.startswith(("wrist", "finger", "metacarpal")):
        return "wri" + side
    return "head"   # cuello, cabeza y cara


FAMILY = {"pelvis": "Tronco", "spine": "Tronco", "chest": "Tronco", "head": "Tronco",
          "hipR": "PiernaD", "kneeR": "PiernaD", "ankleR": "PiernaD",
          "hipL": "PiernaI", "kneeL": "PiernaI", "ankleL": "PiernaI",
          "shR": "BrazoD", "elbR": "BrazoD", "wriR": "BrazoD",
          "shL": "BrazoI", "elbL": "BrazoI", "wriL": "BrazoI"}


def _conv(x, y, z):
    return (x * 0.1, -z * 0.1, y * 0.1)


def load_obj(path):
    verts, uvs, faces = [], [], []
    group = None
    with open(path) as fh:
        for line in fh:
            if line.startswith("v "):
                _, x, y, z = line.split()
                verts.append(_conv(float(x), float(y), float(z)))
            elif line.startswith("vt "):
                _, u, v = line.split()[:3]
                uvs.append((float(u), float(v)))
            elif line.startswith("g "):
                group = line.split(None, 1)[1].strip()
            elif line.startswith("f "):
                vi, ti = [], []
                for tok in line.split()[1:]:
                    p = tok.split("/")
                    vi.append(int(p[0]) - 1)
                    ti.append(int(p[1]) - 1 if len(p) > 1 and p[1] else -1)
                faces.append((group, vi, ti))
    return np.array(verts, dtype=np.float64), uvs, faces


def apply_targets(co):
    for name, w in MACRO.items():
        with gzip.open(os.path.join(MH, "targets", name + ".target.gz"), "rt") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                i, x, y, z = line.split()
                co[int(i)] += np.array(_conv(float(x), float(y), float(z))) * w
    return co


def R(axis, deg):
    return Matrix.Rotation(math.radians(deg), 4, axis)


def T(x, y, z):
    return Matrix.Translation((x, y, z))


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


class Humano:
    """Personaje con malla de MakeHuman posado con la misma cinemática que el maniquí.

    La pose se describe con el diccionario del guion (root, rot, spine, hipR...).
    `solve` calcula los marcos de cada articulación; `apply` mueve el esqueleto.
    """

    def __init__(self, skin_mat, shorts_mat, shirt_mat, eye_mat, hair_mat):
        co, uvs, faces = load_obj(os.path.join(MH, "base.obj"))
        co = apply_targets(co)
        groups = json.load(open(os.path.join(MH, "basemesh_vertex_groups.json")))
        self.groups = groups
        # de pie: pies en el suelo
        body_hi = groups["body"][0][1]
        co[:, 2] -= co[: body_hi + 1, 2].min()
        self.co = co
        self.n_body = body_hi + 1
        self._build_rig()
        self._build_body(faces, uvs, skin_mat, eye_mat, hair_mat)
        self._build_clothes(faces, shorts_mat, shirt_mat)
        self._fit_kinematics()
        self.merge = False
        self.frames = {}

    # ------------------------------------------------------------ construcción
    def _group_mean(self, name):
        idx = []
        for a, b in self.groups[name]:
            idx.extend(range(a, b + 1))
        return Vector(self.co[idx].mean(axis=0))

    def _joint(self, spec):
        s = spec["strategy"]
        if s == "CUBE":
            return self._group_mean(spec["cube_name"])
        if s == "VERTEX":
            return Vector(self.co[spec["vertex_index"]])
        return Vector(self.co[spec["vertex_indices"]].mean(axis=0))

    def _build_rig(self):
        rig = json.load(open(os.path.join(MH, "rig.default.json")))
        arm = bpy.data.armatures.new("Esqueleto")
        ob = bpy.data.objects.new("Esqueleto", arm)
        bpy.context.scene.collection.objects.link(ob)
        bpy.context.view_layer.objects.active = ob
        bpy.ops.object.mode_set(mode="EDIT")
        for name, b in rig.items():
            eb = arm.edit_bones.new(name)
            eb.head = self._joint(b["head"])
            eb.tail = self._joint(b["tail"])
            if (eb.tail - eb.head).length < 1e-4:
                eb.tail = eb.head + Vector((0, 0, 0.01))
            eb.roll = b.get("roll", 0.0)
        for name, b in rig.items():
            if b.get("parent"):
                arm.edit_bones[name].parent = arm.edit_bones[b["parent"]]
            arm.edit_bones[name].use_connect = False
        bpy.ops.object.mode_set(mode="OBJECT")
        self.arm = ob
        self.rest = {b.name: b.matrix_local.copy() for b in arm.bones}
        self.order = []
        def walk(b):
            self.order.append(b.name)
            for c in b.children:
                walk(c)
        for b in arm.bones:
            if b.parent is None:
                walk(b)
        self.parent = {b.name: (b.parent.name if b.parent else None) for b in arm.bones}

    def _weights(self, ob, index_map):
        w = json.load(open(os.path.join(MH, "weights.default.json")))["weights"]
        for bone, pairs in w.items():
            vg = ob.vertex_groups.new(name=bone)
            by = {}
            for vi, wt in pairs:
                j = index_map.get(vi)
                if j is not None:
                    by.setdefault(round(wt, 4), []).append(j)
            for wt, js in by.items():
                vg.add(js, wt, "REPLACE")
        mod = ob.modifiers.new("Esqueleto", "ARMATURE")
        mod.object = self.arm
        mod.use_deform_preserve_volume = True
        ob.parent = self.arm

    def _make_mesh(self, name, faces, uvs, keep, offset=None):
        """Malla con las caras dadas; devuelve objeto y mapa índice original->nuevo."""
        used = sorted({v for _, vi, _ in faces for v in vi} | set(keep))
        index_map = {v: i for i, v in enumerate(used)}
        co = self.co[used].copy()
        if offset is not None:
            co += offset[used]
        me = bpy.data.meshes.new(name)
        me.from_pydata([tuple(c) for c in co], [], [[index_map[v] for v in vi] for _, vi, _ in faces])
        if uvs:
            uv = me.uv_layers.new(name="UV")
            k = 0
            for (_, vi, ti) in faces:
                for t in ti:
                    uv.data[k].uv = uvs[t] if t >= 0 else (0, 0)
                    k += 1
        for p in me.polygons:
            p.use_smooth = True
        ob = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(ob)
        return ob, index_map, used

    def _build_body(self, faces, uvs, skin_mat, eye_mat, hair_mat):
        body_f = [f for f in faces if f[0] == "body"]
        eye_f = [f for f in faces if f[0] in ("helper-l-eye", "helper-r-eye")]
        ob, imap, used = self._make_mesh("Cuerpo", body_f + eye_f, uvs, [])
        me = ob.data
        me.materials.append(skin_mat)
        me.materials.append(eye_mat)
        n_body = len(body_f)
        for i, p in enumerate(me.polygons):
            p.material_index = 0 if i < n_body else 1
        # ojos: dirección desde el centro del globo (para dibujar iris y pupila)
        attr = me.attributes.new("iris", "FLOAT", "POINT")
        vals = np.zeros(len(used))
        for g in ("helper-l-eye", "helper-r-eye"):
            idx = [i for a, b in self.groups[g] for i in range(a, b + 1)]
            c = self.co[idx].mean(axis=0)
            for i in idx:
                d = self.co[i] - c
                vals[imap[i]] = -d[1] / (np.linalg.norm(d) + 1e-9)
        attr.data.foreach_set("value", vals)
        # regiones de la cabeza en reposo (cuero cabelludo, cejas, barba)
        self._head_regions(ob, imap, used)
        self._weights(ob, imap)
        self.body = ob
        self.body_map = imap
        sub = ob.modifiers.new("Suavizado", "SUBSURF")
        sub.levels = 0
        sub.render_levels = 1
        self._hair(ob, hair_mat)

    def _head_regions(self, ob, imap, used):
        co = self.co
        eL = self._group_mean("helper-l-eye")
        eR = self._group_mean("helper-r-eye")
        ec = (eL + eR) / 2
        top = co[: self.n_body, 2].max()
        P = co[used]
        rel = P - np.array(ec)
        x, y, z = rel[:, 0], rel[:, 1], rel[:, 2]
        head = (P[:, 2] > ec.z - 0.16)
        # cuero cabelludo: por encima de la frente y por detrás, sin cara ni orejas
        r = np.sqrt(x * x + (y - 0.03) ** 2)
        front_line = 0.045 + 0.045 * smoothstep(0.0, 0.07, np.abs(x))   # entradas
        scalp = smoothstep(front_line - 0.004, front_line + 0.012, z + 0.55 * np.clip(y, 0, None))
        nape = smoothstep(-0.075, -0.045, z) * smoothstep(0.02, 0.05, y)
        ears = smoothstep(0.055, 0.07, np.abs(x)) * smoothstep(0.03, -0.01, z) * smoothstep(-0.02, 0.03, y + 0.03)
        hair = np.clip(np.maximum(scalp, nape) * (1 - ears), 0, 1) * head * (z > -0.09)
        hair *= smoothstep(-0.10, -0.075, z)
        brow = (smoothstep(0.012, 0.004, np.abs(z - 0.022 - 0.004 * (np.abs(x) - 0.03) / 0.03)) *
                smoothstep(0.016, 0.022, np.abs(x)) * smoothstep(0.058, 0.045, np.abs(x)) *
                (y < -0.02) * head)
        beard = (smoothstep(-0.03, -0.05, z) * smoothstep(-0.13, -0.11, z) *
                 (y < 0.02) * smoothstep(0.075, 0.06, np.abs(x)) * head)
        me = ob.data
        for name, vals in (("pelo", hair), ("cejas", brow), ("barba", beard)):
            a = me.attributes.new(name, "FLOAT", "POINT")
            a.data.foreach_set("value", np.asarray(vals, dtype=np.float64))
            vg = ob.vertex_groups.new(name="zona_" + name)
            for i, v in enumerate(vals):
                if v > 0.01:
                    vg.add([i], float(v), "REPLACE")

    def _hair(self, ob, hair_mat):
        ob.data.materials.append(hair_mat)
        hair_slot = len(ob.data.materials)
        mod = ob.modifiers.new("Pelo", "PARTICLE_SYSTEM")
        ps = mod.particle_system
        st = ps.settings
        st.type = "HAIR"
        st.count = 9000
        st.emit_from = "FACE"
        st.use_even_distribution = True
        st.material = hair_slot
        st.child_type = "INTERPOLATED"
        st.child_percent = 6
        st.rendered_child_count = 14
        st.child_length = 1.0
        st.clump_factor = 0.15
        st.roughness_1 = 0.004
        st.roughness_2 = 0.002
        st.normal_factor = 0.0034   # longitud del pelo: ~1.5 cm
        st.tangent_factor = 0.0
        st.factor_random = 0.0006
        st.root_radius = 0.6
        st.tip_radius = 0.15
        st.radius_scale = 0.0006
        ps.vertex_group_density = "zona_pelo"
        ps.vertex_group_length = "zona_pelo"
        st.display_step = 3
        st.render_step = 3
        # el pelo debe ir detrás del esqueleto: mover el modificador al final
        while ob.modifiers.find("Pelo") < len(ob.modifiers) - 1:
            bpy.context.view_layer.objects.active = ob
            bpy.ops.object.modifier_move_down(modifier="Pelo")

    def _build_clothes(self, faces, shorts_mat, shirt_mat):
        co = self.co
        z_knee = self._joint({"strategy": "CUBE", "cube_name": "joint-r-knee"}).z
        z_hip = self._joint({"strategy": "CUBE", "cube_name": "joint-r-upper-leg"}).z
        z_neck = self._joint({"strategy": "CUBE", "cube_name": "joint-neck"}).z
        sh = self._joint({"strategy": "CUBE", "cube_name": "joint-r-shoulder"})
        el = self._joint({"strategy": "CUBE", "cube_name": "joint-r-elbow"})
        body_f = [f for f in faces if f[0] == "body"]
        normals = self._rest_normals(body_f)
        drv = self._vertex_drivers()
        nk = self._joint({"strategy": "CUBE", "cube_name": "joint-neck"})
        # pantalón corto: piel entre la cintura y medio muslo
        z_waist = z_hip + 0.11
        z_hem = z_knee + 0.55 * (z_hip - z_knee)
        legs = {"pelvis", "spine", "hipR", "hipL"}

        def short_face(vi):
            z = co[vi, 2].mean()
            return z_hem < z < z_waist and all(drv[v] in legs for v in vi)

        upper = {"pelvis", "spine", "chest", "shR", "shL", "head"}
        sleeve = 0.42 * (el - sh).length

        def shirt_face(vi):
            if not all(drv[v] in upper for v in vi):
                return False
            p = co[vi].mean(axis=0)
            if p[2] < z_waist - 0.06:
                return False
            # cuello redondo: más bajo por delante
            front = p[1] < nk.y
            if p[2] > nk.z - (0.04 if front else 0.015):
                return False
            if any(drv[v] == "head" for v in vi):
                return False
            # manga corta
            if any(drv[v] in ("shR", "shL") for v in vi):
                s_ = sh if p[0] < 0 else Vector((-sh.x, sh.y, sh.z))
                e_ = el if p[0] < 0 else Vector((-el.x, el.y, el.z))
                ax = (e_ - s_).normalized()
                if (Vector(p) - s_).dot(ax) > sleeve:
                    return False
            return True

        shorts_f = [f for f in body_f if short_face(f[1])]
        shirt_f = [f for f in body_f if shirt_face(f[1])]
        self.cloth = []
        for name, fs, mat, off in (("Pantalon", shorts_f, shorts_mat, 0.007),
                                   ("Camiseta", shirt_f, shirt_mat, 0.011)):
            # el borde (bajo, mangas, cuello) se ciñe a la piel
            ring = self._ring_distance(fs)
            k = np.ones(len(co))
            for v, r in ring.items():
                k[v] = min(1.0, 0.3 + 0.7 * r / 3.0)
            offset = normals * (off * k)[:, None]
            ob, imap, used = self._make_mesh(name, fs, None, [], offset)
            ob.data.materials.append(mat)
            sol = ob.modifiers.new("Grosor", "SOLIDIFY")
            sol.thickness = 0.003
            sol.offset = 1.0
            self._weights(ob, imap)
            sub = ob.modifiers.new("Suavizado", "SUBSURF")
            sub.levels = 0
            sub.render_levels = 1
            self.cloth.append(ob)
        # ocultar la piel que queda bajo la ropa (evita que asome al doblar)
        covered = set()
        for fs in (shorts_f, shirt_f):
            vs = {}
            for _, vi, _ in fs:
                for v in vi:
                    vs[v] = vs.get(v, 0) + 1
            covered |= {v for v, n in vs.items() if n >= 4}
        hide = self.body.vertex_groups.new(name="visible")
        vis = [self.body_map[v] for v in range(self.n_body) if v not in covered]
        vis += [self.body_map[v] for v in self.body_map if v >= self.n_body]
        hide.add(vis, 1.0, "REPLACE")
        mask = self.body.modifiers.new("BajoRopa", "MASK")
        mask.vertex_group = "visible"
        bpy.context.view_layer.objects.active = self.body
        while self.body.modifiers.find("BajoRopa") > 1:
            bpy.ops.object.modifier_move_up(modifier="BajoRopa")

    def _vertex_drivers(self):
        """Articulación que más pesa en cada vértice."""
        w = json.load(open(os.path.join(MH, "weights.default.json")))["weights"]
        best = np.zeros(len(self.co))
        drv = ["head"] * len(self.co)
        for bone, pairs in w.items():
            d = driver_of(bone)
            for vi, wt in pairs:
                if wt > best[vi]:
                    best[vi] = wt
                    drv[vi] = d
        return drv

    @staticmethod
    def _ring_distance(faces):
        """Distancia en anillos de cada vértice al borde del conjunto de caras."""
        edges = {}
        nb = {}
        for _, vi, _ in faces:
            n = len(vi)
            for i in range(n):
                a, b = vi[i], vi[(i + 1) % n]
                e = (min(a, b), max(a, b))
                edges[e] = edges.get(e, 0) + 1
                nb.setdefault(a, set()).add(b)
                nb.setdefault(b, set()).add(a)
        dist = {}
        front = [v for e, c in edges.items() if c == 1 for v in e]
        for v in front:
            dist[v] = 0
        while front:
            nxt = []
            for v in front:
                for u in nb[v]:
                    if u not in dist:
                        dist[u] = dist[v] + 1
                        nxt.append(u)
            front = nxt
        return dist

    def _rest_normals(self, faces):
        n = np.zeros_like(self.co)
        for _, vi, _ in faces:
            p = self.co[vi]
            fn = np.cross(p[2] - p[0], p[3 % len(vi)] - p[1]) if len(vi) == 4 else np.cross(p[1] - p[0], p[2] - p[0])
            for v in vi:
                n[v] += fn
        l = np.linalg.norm(n, axis=1)
        l[l == 0] = 1
        return n / l[:, None]

    # ------------------------------------------------------------ cinemática
    def _fit_kinematics(self):
        """Mide las articulaciones del personaje para la cinemática directa."""
        H = {k: self.rest[k].translation.copy() for k in self.rest}
        hipR, hipL = H["upperleg01.R"], H["upperleg01.L"]
        pel = (hipR + hipL) / 2
        self.hip = (hipL.x - hipR.x) / 2
        self.pel0 = pel
        self.off = {
            "spine": H["spine04"] - pel,
            "chest": H["spine02"] - H["spine04"],
            "head": H["neck01"] - H["spine02"],
            "shR": H["upperarm01.R"] - H["spine02"],
            "shL": H["upperarm01.L"] - H["spine02"],
        }
        self.THIGH = (H["lowerleg01.R"] - hipR).length
        self.SHIN = (H["foot.R"] - H["lowerleg01.R"]).length
        self.UPPER = (H["lowerarm01.R"] - H["upperarm01.R"]).length
        self.FORE = (H["wrist.R"] - H["lowerarm01.R"]).length
        # pose de reposo de MakeHuman en términos de la cinemática
        def angles_leg(side, sx):
            d = (H["lowerleg01." + side] - H["upperleg01." + side]).normalized()
            fl = math.degrees(math.atan2(-d.y, -d.z))
            ab = math.degrees(math.asin(max(-1, min(1, sx * d.x))))
            return (fl, ab, 0.0)

        def angles_arm(side, sx):
            d = (H["lowerarm01." + side] - H["upperarm01." + side]).normalized()
            sf = math.degrees(math.atan2(-d.y, -d.z))
            sa = math.degrees(math.asin(max(-1, min(1, sx * d.x))))
            return (sf, sa)

        def bend(a, b, c):
            u, v = (b - a).normalized(), (c - b).normalized()
            return math.degrees(math.acos(max(-1, min(1, u.dot(v)))))

        p = dict(root=tuple(pel), rot=Matrix.Identity(4), spine=(0, 0, 0), chest=(0, 0, 0),
                 neck=(0, 0, 0), ankleR=0.0, ankleL=0.0)
        for side, sx in (("R", -1), ("L", 1)):
            p["hip" + side] = angles_leg(side, sx)
            p["knee" + side] = bend(H["upperleg01." + side], H["lowerleg01." + side], H["foot." + side])
            p["sh" + side] = angles_arm(side, sx)
            p["elb" + side] = bend(H["upperarm01." + side], H["lowerarm01." + side], H["wrist." + side])
        self.p_rest = p
        self.F_rest = {k: v.copy() for k, v in self.solve(p).items()}

    def solve(self, p):
        F = {}
        P = T(*p["root"]) @ p["rot"]
        F["pelvis"] = P
        o = self.off
        S = P @ T(*o["spine"]) @ R("X", p["spine"][0]) @ R("Y", p["spine"][1]) @ R("Z", p["spine"][2])
        C = S @ T(*o["chest"]) @ R("X", p["chest"][0]) @ R("Y", p["chest"][1]) @ R("Z", p["chest"][2])
        Hd = C @ T(*o["head"]) @ R("X", p["neck"][0]) @ R("Y", p["neck"][1]) @ R("Z", p["neck"][2])
        F.update(spine=S, chest=C, head=Hd)
        for side, sx in (("R", -1), ("L", 1)):
            fl, ab, ro = p["hip" + side]
            Hp = P @ T(sx * self.hip, 0, 0) @ R("X", -fl) @ R("Y", -sx * ab) @ R("Z", -sx * ro)
            K = Hp @ T(0, 0, -self.THIGH) @ R("X", p["knee" + side])
            A = K @ T(0, 0, -self.SHIN) @ R("X", -p["ankle" + side])
            F["hip" + side], F["knee" + side], F["ankle" + side] = Hp, K, A
            sf, sa = p["sh" + side]
            Sh = C @ T(*o["sh" + side]) @ R("X", -sf) @ R("Y", -sx * sa)
            E = Sh @ T(0, 0, -self.UPPER) @ R("X", -p["elb" + side])
            W = E @ T(0, 0, -self.FORE)
            F["sh" + side], F["elb" + side], F["wri" + side] = Sh, E, W
        self.frames = F
        return F

    @staticmethod
    def pt(M, x=0.0, y=0.0, z=0.0):
        return M @ Vector((x, y, z))

    def elements(self):
        return None

    def apply(self, E=None):
        F, F0 = self.frames, self.F_rest
        delta = {k: F[k] @ F0[k].inverted() for k in F}
        pose = {}
        pb = self.arm.pose.bones
        for name in self.order:
            M = delta[driver_of(name)] @ self.rest[name]
            pose[name] = M
            par = self.parent[name]
            if par is None:
                basis = self.rest[name].inverted() @ M
            else:
                basis = (self.rest[par].inverted() @ self.rest[name]).inverted() @ pose[par].inverted() @ M
            if name.startswith("finger"):
                basis = basis @ self.curl(name)
            pb[name].matrix_basis = basis

    CURL = 22.0   # flexión relajada de los dedos (grados por falange)

    def curl(self, name):
        k = 0.45 if name.startswith("finger1") else 1.0
        if name.split("-")[1].startswith("1"):
            k *= 0.6
        return Matrix.Rotation(math.radians(self.CURL * k), 4, "X")

    def _eval_coords(self):
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        ev = self.body.evaluated_get(dg)
        me = ev.to_mesh()
        n = len(me.vertices)
        c = np.empty(n * 3)
        me.vertices.foreach_get("co", c)
        ev.to_mesh_clear()
        c = c.reshape(-1, 3)
        Mw = np.array(self.body.matrix_world)
        return c @ Mw[:3, :3].T + Mw[:3, 3]

    def lowest(self, E=None, fams=None):
        self.apply()
        # el modificador de máscara cambia el número de vértices: medir sin él
        mods = [m for m in self.body.modifiers if m.type in ("MASK", "PARTICLE_SYSTEM")]
        for m in mods:
            m.show_viewport = False
        c = self._eval_coords()
        for m in mods:
            m.show_viewport = True
        c = c[: len(self._fam)]
        if fams:
            c = c[np.isin(self._fam, fams)]
        lo = c[:, 2].min()
        for ob in self.cloth:   # la ropa también apoya
            pass
        return float(lo)

    @property
    def _fam(self):
        if not hasattr(self, "_fam_cache"):
            ob = self.body
            names = [g.name for g in ob.vertex_groups]
            n = len(ob.data.vertices)
            best = np.zeros(n)
            fam = np.array(["Tronco"] * n, dtype=object)
            for v in ob.data.vertices:
                for g in v.groups:
                    nm = names[g.group]
                    if nm in self.rest and g.weight > best[v.index]:
                        best[v.index] = g.weight
                        fam[v.index] = FAMILY[driver_of(nm)]
            self._fam_cache = fam
        return self._fam_cache

    def set_visible(self, v):
        for ob in [self.body] + self.cloth:
            ob.hide_render = not v
