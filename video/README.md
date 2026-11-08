# Vídeos 3D de anatomía para escaladores

Base para que cada vídeo nuevo salga realista sin empezar de cero.

| Archivo | Qué es |
|---|---|
| `plantilla_escena.py` | **Punto de partida de cada vídeo.** Mano anatómica real agarrando una regleta, con piel translúcida, poleas y rotura opcional de la A2. |
| `kit/` | Herramientas reutilizables (anatomía, materiales, cámara, animación, render). |
| `assets/mano_derecha.blend` | Mano derecha de Z-Anatomy: 29 huesos, flexores, vainas, cápsulas, ligamentos y piel. Ver `assets/ATRIBUCION.md`. |
| `extraer_mano.py` | Regenera el asset desde Z-Anatomy (solo si hace falta añadir piezas). |
| `escena_poleas.py` | Vídeo anterior (A2), hecho con formas generadas por código. Se deja como referencia. |

## Empezar un vídeo nuevo

```bash
pip install bpy            # Blender 5.2 como módulo de Python
cp plantilla_escena.py escena_mi_video.py
```

1. Edita el bloque `PLANO` de la copia: dedo protagonista, tipo de agarre, momentos clave.
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
- La piel de Z-Anatomy viene en parches; `cargar_mano` los funde en una sola
  superficie (remallado por vóxeles) para que no se vean costuras.
