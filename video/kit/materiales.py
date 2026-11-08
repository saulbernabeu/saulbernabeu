"""Materiales realistas a escala real (metros).

Todos son procedurales: no dependen de texturas externas. Los valores de
dispersión subsuperficial (SSS) están en milímetros reales, por eso
'Subsurface Scale' es 0.001.
"""
import bpy


def _nuevo(nombre):
    m = bpy.data.materials.new(nombre)
    m.use_nodes = True
    nt = m.node_tree
    return m, nt, nt.nodes["Principled BSDF"]


def _ruido(nt, escala, detalle=6.0, rugosidad=0.55, coords="Object", estirar=(1, 1, 1)):
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (escala * estirar[0], escala * estirar[1], escala * estirar[2])
    nt.links.new(tc.outputs[coords], mp.inputs["Vector"])
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.inputs["Detail"].default_value = detalle
    nz.inputs["Roughness"].default_value = rugosidad
    nt.links.new(mp.outputs["Vector"], nz.inputs["Vector"])
    return nz


def _rampa(nt, entrada, c0, c1, p0=0.35, p1=0.65):
    r = nt.nodes.new("ShaderNodeValToRGB")
    r.color_ramp.elements[0].position, r.color_ramp.elements[0].color = p0, (*c0, 1)
    r.color_ramp.elements[1].position, r.color_ramp.elements[1].color = p1, (*c1, 1)
    nt.links.new(entrada, r.inputs["Fac"])
    return r


def _relieve(nt, b, entrada, fuerza, distancia=0.0004):
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = fuerza
    bump.inputs["Distance"].default_value = distancia
    nt.links.new(entrada, bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return bump


def _sss(b, peso, radio, ior=1.4):
    b.inputs["Subsurface Weight"].default_value = peso
    b.inputs["Subsurface Radius"].default_value = radio
    b.inputs["Subsurface Scale"].default_value = 0.001
    b.subsurface_method = "RANDOM_WALK_SKIN"
    if "Subsurface IOR" in b.inputs:     # solo existe con el método Random Walk (Skin)
        b.inputs["Subsurface IOR"].default_value = ior


# ---------------------------------------------------------------- tejidos

def hueso(nombre="Hueso"):
    """Hueso fresco: marfil con zonas amarillentas, poroso y mate."""
    m, nt, b = _nuevo(nombre)
    n = _ruido(nt, 60, detalle=4)
    _rampa(nt, n.outputs["Fac"], (0.70, 0.60, 0.44), (0.86, 0.80, 0.66))
    nt.links.new(nt.nodes["Color Ramp"].outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.55
    _sss(b, 0.2, (4.0, 2.5, 1.5))
    poros = nt.nodes.new("ShaderNodeTexVoronoi")
    poros.inputs["Scale"].default_value = 1800
    _relieve(nt, b, poros.outputs["Distance"], 0.08, 0.0002)
    return m


def cartilago(nombre="Cartilago"):
    """Cartílago y cápsulas: blanco azulado, translúcido y húmedo."""
    m, nt, b = _nuevo(nombre)
    b.inputs["Base Color"].default_value = (0.80, 0.83, 0.86, 1)
    b.inputs["Roughness"].default_value = 0.3
    _sss(b, 0.6, (2.0, 2.2, 2.6))
    b.inputs["Coat Weight"].default_value = 0.7
    b.inputs["Coat Roughness"].default_value = 0.08
    return m


def tendon(nombre="Tendon"):
    """Tendón: blanco nacarado con fibras longitudinales y aspecto húmedo.

    Usa coordenadas 'Generated' (de la malla sin deformar) para que las fibras
    se queden pegadas al tendón cuando el dedo se dobla.
    """
    m, nt, b = _nuevo(nombre)
    fib = _ruido(nt, 3, detalle=10, coords="Generated", estirar=(60, 60, 1))
    _rampa(nt, fib.outputs["Fac"], (0.80, 0.74, 0.62), (0.94, 0.90, 0.82))
    nt.links.new(nt.nodes["Color Ramp"].outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.35
    b.inputs["Sheen Weight"].default_value = 0.4
    b.inputs["Sheen Tint"].default_value = (0.95, 0.95, 1.0, 1)
    b.inputs["Coat Weight"].default_value = 0.5
    b.inputs["Coat Roughness"].default_value = 0.1
    _sss(b, 0.4, (3.0, 2.2, 1.6))
    _relieve(nt, b, fib.outputs["Fac"], 0.25)
    return m


def ligamento(nombre="Ligamento", resalte=(1.0, 0.25, 0.12)):
    """Ligamento o polea: banda fibrosa nacarada.

    Devuelve (material, nodo_bsdf). Para resaltarla de forma didáctica anima
    b.inputs["Emission Strength"] (el color de emisión ya es 'resalte').
    """
    m, nt, b = _nuevo(nombre)
    fib = _ruido(nt, 2, detalle=8, coords="Generated", estirar=(1, 40, 1))
    _rampa(nt, fib.outputs["Fac"], (0.78, 0.76, 0.72), (0.95, 0.94, 0.90))
    nt.links.new(nt.nodes["Color Ramp"].outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.3
    b.inputs["Coat Weight"].default_value = 0.6
    b.inputs["Coat Roughness"].default_value = 0.08
    b.inputs["Sheen Weight"].default_value = 0.5
    _sss(b, 0.5, (2.0, 1.8, 1.5))
    _relieve(nt, b, fib.outputs["Fac"], 0.3)
    b.inputs["Emission Color"].default_value = (*resalte, 1)
    b.inputs["Emission Strength"].default_value = 0.0
    return m, b


def musculo(nombre="Musculo"):
    """Músculo: rojo profundo con estrías y brillo húmedo."""
    m, nt, b = _nuevo(nombre)
    fib = _ruido(nt, 3, detalle=8, coords="Generated", estirar=(50, 50, 1))
    _rampa(nt, fib.outputs["Fac"], (0.22, 0.03, 0.03), (0.45, 0.08, 0.06))
    nt.links.new(nt.nodes["Color Ramp"].outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.4
    b.inputs["Coat Weight"].default_value = 0.4
    b.inputs["Coat Roughness"].default_value = 0.15
    _sss(b, 0.5, (4.0, 1.0, 0.6))
    _relieve(nt, b, fib.outputs["Fac"], 0.3)
    return m


def fascia(nombre="Fascia"):
    """Fascias y aponeurosis: velo blanquecino semitransparente."""
    m, nt, b = _nuevo(nombre)
    b.inputs["Base Color"].default_value = (0.85, 0.82, 0.78, 1)
    b.inputs["Roughness"].default_value = 0.35
    b.inputs["Alpha"].default_value = 0.35
    b.inputs["Coat Weight"].default_value = 0.5
    return m


def piel(nombre="Piel", tono=(0.72, 0.47, 0.37)):
    """Piel con SSS real (radios de piel humana en mm), variación de color y poros.

    Devuelve (material, nodo_opacidad). Anima nodo_opacidad.outputs[0]
    ('default_value') de 1 a ~0.1 para volver la piel translúcida y ver dentro;
    los bordes de la silueta se mantienen algo más opacos.
    """
    m, nt, b = _nuevo(nombre)
    manchas = _ruido(nt, 90, detalle=3)
    rojo = tuple(min(1, c * f) for c, f in zip(tono, (1.08, 0.85, 0.85)))
    _rampa(nt, manchas.outputs["Fac"], tono, rojo, 0.4, 0.7)
    nt.links.new(nt.nodes["Color Ramp"].outputs["Color"], b.inputs["Base Color"])
    rug = _ruido(nt, 400, detalle=2)
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["To Min"].default_value, mr.inputs["To Max"].default_value = 0.38, 0.55
    nt.links.new(rug.outputs["Fac"], mr.inputs["Value"])
    nt.links.new(mr.outputs["Result"], b.inputs["Roughness"])
    _sss(b, 1.0, (3.67, 1.37, 0.68))
    b.inputs["Sheen Weight"].default_value = 0.1
    poros = _ruido(nt, 3000, detalle=2)
    _relieve(nt, b, poros.outputs["Fac"], 0.06, 0.0001)
    return m, hacer_translucido(m, b)


def hacer_translucido(m, b, borde=0.35):
    """Mezcla el material con transparencia según un valor animable.

    Devuelve el nodo 'opacidad' (1 = opaco).
    """
    nt = m.node_tree
    out = nt.nodes["Material Output"]
    op = nt.nodes.new("ShaderNodeValue")
    op.name = "opacidad"
    op.outputs[0].default_value = 1.0
    lw = nt.nodes.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.45
    inv = nt.nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    nt.links.new(op.outputs[0], inv.inputs[1])
    rim = nt.nodes.new("ShaderNodeMath")
    rim.operation = "MULTIPLY"
    nt.links.new(lw.outputs["Facing"], rim.inputs[0])
    nt.links.new(inv.outputs[0], rim.inputs[1])
    rimk = nt.nodes.new("ShaderNodeMath")
    rimk.operation = "MULTIPLY"
    rimk.inputs[1].default_value = borde
    nt.links.new(rim.outputs[0], rimk.inputs[0])
    fac = nt.nodes.new("ShaderNodeMath")
    fac.operation = "ADD"
    fac.use_clamp = True
    nt.links.new(op.outputs[0], fac.inputs[0])
    nt.links.new(rimk.outputs[0], fac.inputs[1])
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(fac.outputs[0], mix.inputs[0])
    nt.links.new(tr.outputs[0], mix.inputs[1])
    nt.links.new(b.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    return op


def grasa(nombre="Grasa"):
    """Tejido adiposo (p. ej. grasa de Hoffa): amarillo, blando y húmedo."""
    m, nt, b = _nuevo(nombre)
    n = _ruido(nt, 150, detalle=4)
    _rampa(nt, n.outputs["Fac"], (0.80, 0.62, 0.25), (0.95, 0.82, 0.45))
    nt.links.new(nt.nodes["Color Ramp"].outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.3
    b.inputs["Coat Weight"].default_value = 0.6
    _sss(b, 0.8, (4.0, 3.0, 1.5))
    vor = nt.nodes.new("ShaderNodeTexVoronoi")      # lobulillos
    vor.inputs["Scale"].default_value = 300
    _relieve(nt, b, vor.outputs["Distance"], 0.2)
    return m


def bursa(nombre="Bursa"):
    """Bursa sinovial: saquito translúcido con líquido."""
    m, nt, b = _nuevo(nombre)
    b.inputs["Base Color"].default_value = (0.92, 0.85, 0.70, 1)
    b.inputs["Roughness"].default_value = 0.08
    b.inputs["Transmission Weight"].default_value = 0.7
    b.inputs["Coat Weight"].default_value = 1.0
    b.inputs["Alpha"].default_value = 0.7
    return m


def resalte(nombre="Resalte", color=(1.0, 0.18, 0.08)):
    """Volumen semitransparente que brilla (zona inflamada, punto de dolor).

    Devuelve (material, nodo_bsdf); anima b.inputs["Emission Strength"].
    """
    m, nt, b = _nuevo(nombre)
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Emission Color"].default_value = (*color, 1)
    b.inputs["Emission Strength"].default_value = 0.0
    b.inputs["Roughness"].default_value = 0.4
    b.inputs["Alpha"].default_value = 0.45
    return m, b


# ---------------------------------------------------------------- entorno

def madera(nombre="Madera", tiza=0.35):
    """Madera de presa de entrenamiento (haya/fresno) con restos de magnesio."""
    m, nt, b = _nuevo(nombre)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (8, 120, 8)
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    ondas = nt.nodes.new("ShaderNodeTexWave")
    ondas.wave_type = "RINGS"
    ondas.inputs["Scale"].default_value = 2.0
    ondas.inputs["Distortion"].default_value = 6.0
    ondas.inputs["Detail"].default_value = 4.0
    nt.links.new(mp.outputs["Vector"], ondas.inputs["Vector"])
    col = _rampa(nt, ondas.outputs["Fac"], (0.42, 0.25, 0.12), (0.70, 0.50, 0.30), 0.2, 0.8)
    polvo = _ruido(nt, 250, detalle=6)
    mt = nt.nodes.new("ShaderNodeMapRange")
    mt.inputs["From Min"].default_value = 0.55 - tiza * 0.3
    mt.inputs["From Max"].default_value = 0.75
    nt.links.new(polvo.outputs["Fac"], mt.inputs["Value"])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs["B"].default_value = (0.92, 0.92, 0.90, 1)
    nt.links.new(mt.outputs["Result"], mix.inputs["Factor"])
    nt.links.new(col.outputs["Color"], mix.inputs["A"])
    nt.links.new(mix.outputs["Result"], b.inputs["Base Color"])
    rr = nt.nodes.new("ShaderNodeMapRange")
    rr.inputs["To Min"].default_value, rr.inputs["To Max"].default_value = 0.45, 0.9
    nt.links.new(mt.outputs["Result"], rr.inputs["Value"])
    nt.links.new(rr.outputs["Result"], b.inputs["Roughness"])
    _relieve(nt, b, ondas.outputs["Fac"], 0.1)
    return m


def mate(nombre, color, rugosidad=0.8):
    m, nt, b = _nuevo(nombre)
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rugosidad
    return m


# ---------------------------------------------------------------- asignación

def aplicar_mano(mano, poleas=None):
    """Asigna un material adecuado a cada pieza de la mano.

    Devuelve un dict con los materiales y los nodos animables:
    {'piel_opacidad': nodo, 'polea': (material, bsdf), ...}
    """
    mats = {
        "hueso": hueso(), "cartilago": cartilago(), "tendon": tendon(),
        "musculo": musculo(), "fascia": fascia(),
    }
    mats["polea"] = ligamento("Polea")
    mats["polea_resaltada"] = ligamento("Polea resaltada")
    mats["piel"], mats["piel_opacidad"] = piel()
    flexores_tendon = {"Flexor digitorum profundus",
                       "Humero-ulnar head of flexor digitorum superficialis",
                       "Radial head of flexor digitorum superficialis", "Extensor digitorum"}
    for nombre, ob in mano.obj.items():
        cols = {c.name for c in ob.users_collection}
        if "Huesos" in cols:
            m = mats["hueso"]
        elif "Articulaciones" in cols:
            m = mats["cartilago"]
        elif "Piel" in cols or nombre == "Piel":
            m = mats["piel"]
        elif nombre in flexores_tendon:
            m = mats["tendon"]
        elif "sheath" in nombre.lower():
            m = mats["cartilago"]
        elif "fascia" in nombre.lower() or "aponeurosis" in nombre.lower():
            m = mats["fascia"]
        else:
            m = mats["musculo"]
        ob.data.materials.clear()
        ob.data.materials.append(m)
    for v in (poleas or {}).values():
        for ob in (v if isinstance(v, tuple) else (v,)):
            ob.data.materials.clear()
            ob.data.materials.append(mats["polea"][0])
    return mats


def aplicar_auto(region, translucidos=()):
    """Asigna materiales a cualquier región según el nombre de cada pieza.

    translucidos: textos de nombres de piezas que también se podrán volver
    translúcidas (con la piel). Devuelve un dict con los materiales y
    'piel_opacidad' (y 'opacidad_<texto>' para cada translúcido).
    """
    mats = {
        "hueso": hueso(), "cartilago": cartilago(), "tendon": tendon(), "musculo": musculo(),
        "fascia": fascia(), "grasa": grasa(), "bursa": bursa(),
        "ligamento": ligamento()[0],
    }
    mats["piel"], mats["piel_opacidad"] = piel()

    def elegir(nombre, cols):
        n = nombre.lower()
        if "Huesos" in cols:
            return "hueso"
        if "Piel" in cols or nombre == "Piel":
            return "piel"
        if "bursa" in n:
            return "bursa"
        if "fat pad" in n or "fat body" in n:
            return "grasa"
        if "meniscus" in n or "capsule" in n or "cartilage" in n or "sheath" in n:
            return "cartilago"
        if "fascia" in n or "aponeurosis" in n or "septum" in n:
            return "fascia"
        if "tendon" in n and "sheath" not in n:
            return "tendon"
        if "ligament" in n or "retinacul" in n or "tract" in n:
            return "ligamento"
        return "musculo"

    for nombre, ob in region.obj.items():
        clave = elegir(nombre, {c.name for c in ob.users_collection})
        ob.data.materials.clear()
        ob.data.materials.append(mats[clave])

    # cada grupo de translúcidos comparte un material (copia del de su primera
    # pieza) para que un solo valor de opacidad los controle a todos
    for texto in translucidos:
        piezas = region.buscar(texto)
        if not piezas:
            continue
        m = piezas[0].data.materials[0].copy()
        m.name = f"{m.name} translúcido ({texto})"
        mats[f"opacidad_{texto}"] = hacer_translucido(m, m.node_tree.nodes["Principled BSDF"],
                                                      borde=0.2)
        for ob in piezas:
            ob.data.materials[0] = m
    return mats
