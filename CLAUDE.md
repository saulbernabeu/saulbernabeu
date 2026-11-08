# Proyecto: vídeos divulgativos de lesiones deportivas (escalada, carrera...)

Guiones en `guiones/`, escenas 3D y renders en `video/`. Todo en castellano.

> **Los reels nuevos se hacen en el repositorio `saulbernabeu/videos-reels`**, que tiene
> la plantilla de estilo y la versión actualizada de este kit (`plantilla/anatomia/`).
> Si el usuario pide un reel aquí, avísale y trabaja en ese repositorio.

## Vídeos 3D: usar siempre el kit

Para cualquier vídeo o escena 3D nueva, **parte de una plantilla** (cópiala a
`video/escena_<tema>.py`) y usa el kit de `video/kit/`:
- mano / dedos → `video/plantilla_escena.py`
- rodilla / pierna / carrera → `video/plantilla_rodilla.py`

No generes la anatomía con formas de código como en `video/escena_poleas.py`
(vídeo antiguo).

- `kit/anatomia.py`: mano y pierna reales de Z-Anatomy (`video/assets/`), rigs
  automáticos, poleas A1–A5, epicóndilo, zonas resaltadas.
- `kit/materiales.py` (`aplicar_auto` sirve para cualquier región), `kit/escena.py`
  (luces, `Camara` con seguimiento, render, postproducción), `kit/animacion.py`
  (poses con desfase, ciclo de carrera, muelles, temblor, rotura, ralentí).
- Guía completa y lista de comprobación de realismo: `video/README.md`.
- Unidades en metros reales. Dedos: pulgar, indice, corazon, anular, menique.

Si hacen falta otras partes del cuerpo, añade la región a `REGIONES` en
`video/extraer_region.py` (clona
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
