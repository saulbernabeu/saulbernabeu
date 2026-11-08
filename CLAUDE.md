# Proyecto: vídeos divulgativos para escaladores

Guiones en `guiones/`, escenas 3D y renders en `video/`. Todo en castellano.

## Vídeos 3D: usar siempre el kit

Para cualquier vídeo o escena 3D nueva, **parte de `video/plantilla_escena.py`**
(cópiala a `video/escena_<tema>.py`) y usa el kit de `video/kit/`. No generes la
anatomía con formas de código como en `video/escena_poleas.py` (vídeo antiguo).

- `kit/anatomia.py`: mano real de Z-Anatomy (`video/assets/mano_derecha.blend`),
  rig automático y poleas A1–A5.
- `kit/materiales.py`, `kit/escena.py` (luces, `Camara`, render, postproducción),
  `kit/animacion.py` (poses con desfase, muelles, temblor, rotura, ralentí).
- Guía completa y lista de comprobación de realismo: `video/README.md`.
- Unidades en metros reales. Dedos: pulgar, indice, corazon, anular, menique.

Si hacen falta otras partes del cuerpo, adapta `video/extraer_mano.py` (clona
`https://github.com/LluisV/Z-Anatomy` con `GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1`;
los FBX están en `Resources/Models/FBX/`).

## Entorno

- Blender 5.2.3 como módulo (`import bpy`), sin GUI. El script de configuración
  del entorno lo instala junto con libEGL (necesaria para el compositor).
  Si falta: `pip install bpy==5.2.3` y `apt-get install -y libegl1 libegl-mesa0 libgl1-mesa-dri`.
- Render con Cycles en CPU (4 núcleos): para pruebas usa `--still N` en calidad
  borrador y resolución baja (`--res 30 --samples 16`); un fotograma final tarda minutos.
- Comprueba los renders mirando las imágenes antes de dar algo por bueno.

## Licencia de los modelos

Z-Anatomy es CC BY-SA 4.0: cada vídeo publicado debe llevar el crédito que hay en
`video/assets/ATRIBUCION.md`. Recuérdaselo al usuario al entregar un vídeo.
