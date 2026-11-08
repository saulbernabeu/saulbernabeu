"""Escena: mundo, luces, cámara con comportamiento real, render y postproducción."""
import math
import random

import bpy
from mathutils import Vector

from . import animacion


def nueva_escena(fps=24, frames=240):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.fps = fps
    sc.frame_start, sc.frame_end = 1, frames
    sc.unit_settings.system = "METRIC"
    sc.unit_settings.length_unit = "CENTIMETERS"
    return sc


# ---------------------------------------------------------------- mundo y luces

def mundo_estudio(sc, color_arriba=(0.05, 0.07, 0.10), color_abajo=(0.006, 0.007, 0.01), fuerza=1.0):
    """Fondo de estudio con degradado vertical (da reflejos suaves y creíbles)."""
    w = bpy.data.worlds.new("Estudio")
    sc.world = w
    w.use_nodes = True
    nt = w.node_tree
    bg = nt.nodes["Background"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position, ramp.color_ramp.elements[0].color = 0.35, (*color_abajo, 1)
    ramp.color_ramp.elements[1].position, ramp.color_ramp.elements[1].color = 0.75, (*color_arriba, 1)
    nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = fuerza
    return w


def _area(nombre, pos, mirar, tam, potencia, color):
    ld = bpy.data.lights.new(nombre, "AREA")
    ld.shape = "DISK"
    ld.size = tam
    ld.energy = potencia
    ld.color = color
    ob = bpy.data.objects.new(nombre, ld)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = pos
    ob.rotation_euler = (Vector(mirar) - Vector(pos)).to_track_quat("-Z", "Y").to_euler()
    return ob


def luces_estudio(centro, distancia=0.6, intensidad=1.0, calida=(1.0, 0.93, 0.85),
                  fria=(0.70, 0.82, 1.0)):
    """Esquema de tres luces más un contraluz, escalado a la distancia dada.

    Principal grande y cálida (luz suave tipo ventana), relleno frío tenue y
    dos contraluces que recortan la silueta. Potencias en vatios reales.
    """
    c = Vector(centro)
    d = distancia
    k = intensidad * (d / 0.6) ** 2
    return {
        "principal": _area("Principal", c + Vector((-0.6, -0.9, 0.7)) * d, c, 0.9 * d, 60 * k, calida),
        "relleno": _area("Relleno", c + Vector((1.0, -0.6, -0.2)) * d, c, 1.2 * d, 12 * k, fria),
        "contra": _area("Contra", c + Vector((0.5, 1.0, 0.6)) * d, c, 0.5 * d, 70 * k, fria),
        "recorte": _area("Recorte", c + Vector((-0.9, 0.7, -0.3)) * d, c, 0.4 * d, 35 * k, calida),
    }


# ---------------------------------------------------------------- cámara

class Camara:
    """Cámara con jerarquía:  órbita -> sacudida -> cámara (apunta a 'objetivo').

    - La órbita (empty en el objetivo) se anima con clave(): giro, inclinación y distancia.
    - La sacudida lleva el movimiento de cámara en mano y los golpes, sin
      interferir con las claves de la órbita.
    - El foco es un empty independiente: enfocar() hace cambios de foco.
    """

    def __init__(self, objetivo, distancia=0.3, lente=85, fstop=2.8, sensor=36):
        sc = bpy.context.scene
        self.objetivo = self._empty("Objetivo", objetivo)
        self.orbita = self._empty("Orbita", objetivo)
        self.sacudida = self._empty("Sacudida", (0, 0, 0))
        self.sacudida.parent = self.orbita
        self.foco = self._empty("Foco", objetivo)
        cd = bpy.data.cameras.new("Camara")
        cd.lens = lente
        cd.sensor_width = sensor
        cd.clip_start = 0.005
        cd.dof.use_dof = True
        cd.dof.focus_object = self.foco
        cd.dof.aperture_fstop = fstop
        cd.dof.aperture_blades = 7          # bokeh poligonal como en un objetivo real
        cd.dof.aperture_ratio = 1.0
        self.cam = bpy.data.objects.new("Camara", cd)
        sc.collection.objects.link(self.cam)
        self.cam.parent = self.sacudida
        self.cam.location = (0, -distancia, 0)
        tc = self.cam.constraints.new("TRACK_TO")
        tc.target = self.objetivo
        tc.track_axis = "TRACK_NEGATIVE_Z"
        tc.up_axis = "UP_Y"
        sc.camera = self.cam

    @staticmethod
    def _empty(nombre, loc):
        e = bpy.data.objects.new(nombre, None)
        e.empty_display_size = 0.01
        e.location = loc
        bpy.context.scene.collection.objects.link(e)
        return e

    def clave(self, frame, giro=0.0, inclinacion=0.0, distancia=None, objetivo=None, foco=True):
        """Posición de cámara en un fotograma (ángulos en grados).

        giro: vuelta alrededor del objetivo (eje vertical). inclinacion: + = desde
        arriba, - = desde abajo. Si foco=True el foco sigue al objetivo; ponlo a
        False si usas enfocar().
        """
        self.orbita.rotation_euler = (-math.radians(inclinacion), 0, math.radians(giro))
        self.orbita.keyframe_insert("rotation_euler", frame=frame)
        if distancia is not None:
            self.cam.location = (0, -distancia, 0)
            self.cam.keyframe_insert("location", frame=frame)
        if objetivo is not None:
            self.objetivo.location = objetivo
            self.orbita.location = objetivo
            self.objetivo.keyframe_insert("location", frame=frame)
            self.orbita.keyframe_insert("location", frame=frame)
            if foco:
                self.foco.location = objetivo
                self.foco.keyframe_insert("location", frame=frame)

    def enfocar(self, frame, punto, duracion=12):
        """Cambio de foco hacia 'punto', terminando en 'frame' (como un foquista)."""
        self.foco.keyframe_insert("location", frame=frame - duracion)
        self.foco.location = punto
        self.foco.keyframe_insert("location", frame=frame)

    def apertura(self, frame, fstop):
        self.cam.data.dof.aperture_fstop = fstop
        self.cam.data.dof.keyframe_insert("aperture_fstop", frame=frame)

    def en_mano(self, intensidad=1.0, desde=None, hasta=None):
        """Movimiento sutil de cámara al hombro: deriva lenta y micro-temblor."""
        s = self.sacudida
        s.keyframe_insert("rotation_euler", frame=bpy.context.scene.frame_start)
        s.keyframe_insert("location", frame=bpy.context.scene.frame_start)
        for i in range(3):
            animacion.ruido(s, "rotation_euler", i, amplitud=0.004 * intensidad, periodo=70,
                            desde=desde, hasta=hasta, semilla=11 + i)
            animacion.ruido(s, "rotation_euler", i, amplitud=0.0012 * intensidad, periodo=9,
                            desde=desde, hasta=hasta, semilla=23 + i)
            animacion.ruido(s, "location", i, amplitud=0.0004 * intensidad, periodo=55,
                            desde=desde, hasta=hasta, semilla=37 + i)

    def sacudir(self, frame, fuerza=1.0, duracion=14, semilla=0):
        """Golpe de cámara (impacto, rotura...) que se amortigua como un muelle."""
        rnd = random.Random(semilla)
        s = self.sacudida
        for i in range(3):
            amp = 0.012 * fuerza * rnd.uniform(0.5, 1.0) * rnd.choice((-1, 1))
            animacion.muelle(s, "rotation_euler", i, frame, amp, 0.0,
                             frecuencia=rnd.uniform(5, 8), amortiguacion=0.25, duracion=duracion)


# ---------------------------------------------------------------- render

def configurar_render(sc, calidad="borrador", resolucion=(1920, 1080), desenfoque_mov=0.5):
    """Ajustes de Cycles. calidad: 'borrador' (pruebas rápidas) o 'final'."""
    r = sc.render
    r.engine = "CYCLES"
    r.resolution_x, r.resolution_y = resolucion
    r.use_motion_blur = desenfoque_mov > 0
    r.motion_blur_shutter = desenfoque_mov
    r.use_persistent_data = True
    r.image_settings.file_format = "PNG"
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast"
    cy = sc.cycles
    cy.device = "CPU"
    cy.use_denoising = True
    cy.denoiser = "OPENIMAGEDENOISE"
    cy.use_adaptive_sampling = True
    final = calidad == "final"
    cy.samples = 256 if final else 48
    cy.adaptive_threshold = 0.01 if final else 0.05
    cy.max_bounces = 12 if final else 6
    cy.diffuse_bounces = 4 if final else 2
    cy.transparent_max_bounces = 32 if final else 16
    cy.transmission_bounces = 12 if final else 6
    cy.caustics_reflective = False
    cy.caustics_refractive = False
    r.resolution_percentage = 100 if final else 50


def postproduccion(sc, vineteado=0.3, grano=0.025, aberracion=0.006, distorsion=-0.01):
    """Acabado de cámara real en el compositor: viñeteado, grano, aberración
    cromática y una ligera distorsión de lente. Pon un valor a 0 para quitarlo.
    """
    ng = bpy.data.node_groups.new("Postproduccion", "CompositorNodeTree")
    ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    N = ng.nodes.new
    L = ng.links.new
    rl = N("CompositorNodeRLayers")
    out = N("NodeGroupOutput")
    img = rl.outputs["Image"]

    if aberracion or distorsion:
        lens = N("CompositorNodeLensdist")
        lens.inputs["Distortion"].default_value = distorsion
        lens.inputs["Dispersion"].default_value = aberracion
        L(img, lens.inputs["Image"])
        img = lens.outputs["Image"]

    if vineteado:
        coords = N("CompositorNodeImageCoordinates")
        L(img, coords.inputs["Image"])
        vm = N("ShaderNodeVectorMath")
        vm.operation = "LENGTH"
        L(coords.outputs["Normalized"], vm.inputs[0])
        sm = N("ShaderNodeMapRange")
        sm.interpolation_type = "SMOOTHSTEP"
        sm.inputs["From Min"].default_value = 0.55
        sm.inputs["From Max"].default_value = 1.45
        sm.inputs["To Min"].default_value = 1.0
        sm.inputs["To Max"].default_value = 1.0 - vineteado
        L(vm.outputs["Value"], sm.inputs["Value"])
        mul = N("ShaderNodeMix")
        mul.data_type = "RGBA"
        mul.blend_type = "MULTIPLY"
        mul.inputs["Factor"].default_value = 1.0
        L(img, mul.inputs["A"])
        L(sm.outputs["Result"], mul.inputs["B"])
        img = mul.outputs["Result"]

    if grano:
        coords = N("CompositorNodeImageCoordinates")
        L(img, coords.inputs["Image"])
        t = N("CompositorNodeSceneTime")
        nz = N("ShaderNodeTexNoise")
        nz.noise_dimensions = "4D"
        nz.inputs["Scale"].default_value = 0.9
        nz.inputs["Detail"].default_value = 0.0
        L(coords.outputs["Pixel"], nz.inputs["Vector"])
        L(t.outputs["Frame"], nz.inputs["W"])
        c = N("ShaderNodeMath")
        c.operation = "SUBTRACT"
        c.inputs[1].default_value = 0.5
        L(nz.outputs["Factor"], c.inputs[0])
        k = N("ShaderNodeMath")
        k.operation = "MULTIPLY"
        k.inputs[1].default_value = grano * 2
        L(c.outputs[0], k.inputs[0])
        add = N("ShaderNodeMix")
        add.data_type = "RGBA"
        add.blend_type = "ADD"
        add.inputs["Factor"].default_value = 1.0
        L(img, add.inputs["A"])
        L(k.outputs[0], add.inputs["B"])
        img = add.outputs["Result"]

    L(img, out.inputs[0])
    sc.compositing_node_group = ng
    sc.render.use_compositing = True
    return ng
