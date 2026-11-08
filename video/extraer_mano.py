"""Extrae la mano derecha de los modelos de Z-Anatomy a video/assets/mano_derecha.blend.

Z-Anatomy (CC BY-SA 4.0): https://github.com/LluisV/Z-Anatomy
Uso:
    git clone --depth 1 https://github.com/LluisV/Z-Anatomy /ruta/z-anatomy
    python extraer_mano.py --za /ruta/z-anatomy

Solo hace falta ejecutarlo una vez (o si se quieren añadir más piezas).
"""
import argparse
import os
import re
import sys

import bpy

AQUI = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(AQUI, "assets", "mano_derecha.blend")

# Archivo FBX -> (colección, expresión de las piezas que se conservan)
PIEZAS = {
    "SkeletalSystem100.fbx": ("Huesos", r"phalanx of .* finger of hand|metacarpal bone|"
                              r"^(Trapezium|Trapezoid|Capitate|Hamate|Lunate|Pisiform|"
                              r"Scaphoid|Triquetrum) bone|^Radius|^Ulna"),
    "Joints100.fbx": ("Articulaciones", r"interphalangeal|metacarpophalangeal|"
                      r"transverse metacarpal|carpometacarpal|metacarpal ligaments"),
    "MuscularSystem100.fbx": ("Musculos_tendones",
                              r"flexor digitorum (profundus|superficialis)|"
                              r"head of flexor digitorum superficialis|"
                              r"fibrous sheath of digit of hand|synovial sheaths of digits|"
                              r"common flexor tendon sheath|lumbrical|interossei|"
                              r"palmar aponeurosis|extensor digitorum\.|"
                              r"transverse metacarpal ligament|dorsal fascia of hand"),
    "Regions of human body100.fbx": ("Piel", r"surfaces of digits of hand|^palm\.|dorsum of hand"),
}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--za", required=True, help="carpeta del repositorio Z-Anatomy")
    a = ap.parse_args(argv)
    carpeta = os.path.join(a.za, "Resources", "Models", "FBX")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    destino = bpy.context.scene
    for fbx, (nombre_col, expr) in PIEZAS.items():
        antes = set(bpy.data.objects)
        bpy.ops.import_scene.fbx(filepath=os.path.join(carpeta, fbx))
        nuevos = set(bpy.data.objects) - antes
        patron = re.compile(expr, re.I)
        col = bpy.data.collections.new(nombre_col)
        destino.collection.children.link(col)
        for ob in nuevos:
            if (ob.type == "MESH" and ob.name.endswith(".r") and patron.search(ob.name)
                    and not re.search(r"foot|toe|plantar", ob.name, re.I)):
                mundo = ob.matrix_world.copy()
                ob.parent = None
                ob.matrix_world = mundo
                for c in list(ob.users_collection):
                    c.objects.unlink(ob)
                col.objects.link(ob)
                ob.name = ob.name[:-2]
        for ob in nuevos:
            if not ob.users_collection or ob.users_collection[0].name != nombre_col:
                bpy.data.objects.remove(ob, do_unlink=True)

    # Aplicar transformaciones y quitar materiales de Z-Anatomy (el kit pone los suyos)
    for ob in destino.objects:
        ob.data.materials.clear()
        bpy.context.view_layer.objects.active = ob
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    for col in list(bpy.data.collections):
        if col.name not in {v[0] for v in PIEZAS.values()}:
            bpy.data.collections.remove(col)
    bpy.ops.outliner.orphans_purge(do_recursive=True)

    for col in destino.collection.children:
        print(col.name, len(col.objects))
        for ob in sorted(col.objects, key=lambda o: o.name):
            print("   ", ob.name, len(ob.data.vertices))
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=SALIDA, compress=True)
    print("Guardado en", SALIDA)


if __name__ == "__main__":
    main()
