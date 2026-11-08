# Vídeos 3D de anatomía para escaladores

Base para que cada vídeo nuevo salga realista sin empezar de cero.

| Archivo | Qué es |
|---|---|
| `plantilla_escena.py` | **Plantilla de mano.** Mano anatómica real agarrando una regleta, con piel translúcida, poleas y rotura opcional de la A2. |
| `plantilla_rodilla.py` | **Plantilla de rodilla.** Pierna corriendo a cámara lenta, con la cintilla iliotibial rozando el epicóndilo lateral en cada apoyo (rodilla del corredor). |
| `kit/` | Herramientas reutilizables (anatomía, materiales, cámara, animación, render). |
| `assets/mano_derecha.blend` | Mano derecha de Z-Anatomy: 29 huesos, flexores, vainas, cápsulas, ligamentos y piel. |
| `assets/pierna_derecha.blend` | Pierna derecha de Z-Anatomy (cadera a tobillo): fémur, tibia, peroné, rótula, cintilla iliotibial, cuádriceps, isquiotibiales, gemelos, meniscos, ligamentos, bursas y piel. |
| `extraer_region.py` | Extrae regiones de Z-Anatomy a `assets/` (`--region mano` o `rodilla`; se añaden más en `REGIONES`). Atribución: `assets/ATRIBUCION.md`. |
| `escena_poleas.py` | Vídeo anterior (A2), hecho con formas generadas por código. Se deja como referencia. |

## Empezar un vídeo nuevo

```bash
pip install bpy            # Blender 5.2 como módulo de Python
cp plantilla_escena.py escena_mi_video.py
```

   (o `plantilla_rodilla.py` si el vídeo es de rodilla o pierna)
1. Edita el bloque `PLANO` de la copia: estructura protagonista, gesto, momentos clave.
2. Prueba con fotogramas sueltos en borrador (rápido):
   ```bash
   python escena_mi_video.py --still 1 110 140 --out pruebas/
   ```
3. Si quieres retocar a mano, guarda el `.blend` y ábrelo en Blender:
   ```bash
   python escena_mi_video.py --save escena.blend
   ```
4. Render final, directo o por tramos de 20 fotogramas (clips en `tramos/`):
   ```bash
   python escena_mi_video.py --frames 1-120 --calidad final --out frames/
   ESCENA=escena_mi_video.py bash render_tramo.sh 1 20 256
   ```
   Para unir tramos y poner rótulos, copia `ensamblar.sh` y cambia los textos.

> **Ojo con el ralentí:** `RALENTI` estira el tiempo *después* de animar. Con
> `(124, 152, 3)`, la rotura del fotograma 130 pasa a estar en el 142 y el vídeo
> dura más de 240 fotogramas.

## El kit en dos minutos

```python
from kit import anatomia, animacion, escena, materiales

sc = escena.nueva_escena(fps=24, frames=240)
mano = anatomia.cargar_mano()                     # modelos reales, en metros
rig = anatomia.crear_rig(mano)                    # esqueleto calculado de los huesos
poleas = anatomia.crear_poleas(mano, rig, "anular")   # A1–A5 ajustadas al hueso
mats = materiales.aplicar_mano(mano, poleas)

animacion.pose_dedo(rig, "anular", animacion.AGARRES["arqueo"], 80, desfase=2)
animacion.temblor(rig, ["anular.P1", "anular.P2"], 90, 130)
animacion.romper_polea(poleas["A2"], 130)
animacion.desplazar(anatomia.objetos_flexores(mano), rig, "anular.P1", (0, 0, -1), 130, 0.0035)

cam = escena.Camara(objetivo, distancia=0.3, lente=85, fstop=16)
cam.clave(1, giro=40, inclinacion=10)
cam.en_mano()                 # deriva y micro-temblor de cámara al hombro
cam.sacudir(130)              # golpe en la rotura
animacion.ralenti(124, 152, 3)
escena.postproduccion(sc)     # viñeteado, grano, aberración cromática
```

Dedos: `pulgar`, `indice`, `corazon`, `anular`, `menique`. Huesos del rig:
`antebrazo`, `mano` y `<dedo>.MC/P1/P2/P3` (el pulgar no tiene P2).

### Pierna y rodilla

```python
pierna = anatomia.cargar_pierna()
rig = anatomia.crear_rig_pierna(pierna)      # huesos: pelvis, muslo, pierna, rotula
mats = materiales.aplicar_auto(pierna, translucidos=("Vastus lateralis",))
rig.flexion("pierna", 30, frame=50)          # rodilla a 30° (la rótula la sigue sola)
apoyos = animacion.ciclo_carrera(rig, 100, ciclos=4, frames_por_ciclo=48)
tramos = animacion.tramos_en_rango(rig, 100, 300, 20, 30)   # rodilla entre 20 y 30°
animacion.pulsos(bsdf.inputs["Emission Strength"], tramos)  # brillo en esos tramos
cam.seguir(rig.arm, "pierna", influencia=0.7)               # la cámara acompaña a la rodilla
```

Útiles: `pierna.epicondilo_lateral()`, `pierna.centro_rodilla()`,
`anatomia.zona()` (marcar una zona inflamada), `pierna.ocultar("Fascia lata")`.
Orientación: lateral = −X, anterior = −Y, arriba = +Z; en `Camara.clave`,
`giro=-90` mira desde el lado externo de la pierna derecha.

### Otra región del cuerpo

1. Añade la región a `REGIONES` en `extraer_region.py` (expresiones con los
   nombres en inglés de Z-Anatomy) y ejecútalo.
2. Cárgala con `anatomia.cargar("assets/<archivo>.blend")` y
   `materiales.aplicar_auto(...)`; para animarla, toma `crear_rig_pierna` como modelo.

## Lista de comprobación de realismo

Antes de renderizar el vídeo final, repasa:

**Modelos**
- [ ] Huesos y tendones de `assets/`, no formas generadas por código.
- [ ] Escala real (metros). No reescalar la mano.
- [ ] Contexto: presa, pared y mano completa, no una pieza flotando.

**Materiales**
- [ ] Colores naturales; para resaltar algo, emisión suave y temporal (como la A2 de la plantilla), no un color plano.
- [ ] Tejidos húmedos (tendones, poleas, cartílago) con brillo; hueso mate.

**Movimiento**
- [ ] Desfase entre articulaciones y entre dedos (`pose_dedo`/`pose_mano` lo hacen).
- [ ] Nada se detiene en seco: golpes y roturas con `muelle()`.
- [ ] Temblor bajo carga máxima.
- [ ] Biomecánica: tras una rotura el dedo pierde fuerza y se **abre**.

**Cámara**
- [ ] Cámara en mano suave y sacudida en los impactos.
- [ ] Objetivo largo (85–100 mm) y diafragma cerrado en macro (f/11–f/16).
- [ ] Cambios de foco (`cam.enfocar`) para guiar la mirada.
- [ ] Ralentí en el momento clave.

**Acabado**
- [ ] Desenfoque de movimiento activo (viene por defecto).
- [ ] Postproducción: viñeteado, grano, aberración.
- [ ] Crédito de Z-Anatomy en la descripción del vídeo.

## Notas técnicas

- El compositor de Blender 5 necesita OpenGL/EGL. En un servidor sin pantalla:
  `apt-get install libegl1 libgl1-mesa-dri` (en un ordenador normal no hace falta).
- Las poleas anulares no vienen en Z-Anatomy: `crear_poleas` las genera a partir
  del hueso y los flexores reales. Su posición se ajusta en `anatomia.POLEAS`.
- La piel de Z-Anatomy viene en parches; `cargar_mano`/`cargar_pierna` los funden
  en una sola superficie (remallado por vóxeles) para que no se vean costuras.
- La piel de la pierna tiene un hueco en la cadera (Z-Anatomy no trae esa zona):
  encuadra de muslo para abajo.
- La pierna no incluye el pie; los tendones que bajan hacia él se recortan en el tobillo.
