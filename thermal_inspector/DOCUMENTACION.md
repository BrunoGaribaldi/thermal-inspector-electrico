# Inspector Termográfico — Documentación Completa

> Sistema de inspección termográfica basado en el DJI Thermal SDK v1.8.
> Genera informes PDF profesionales a partir de imágenes R-JPEG capturadas con cámaras infrarrojas DJI.

---

## Índice

1. [Visión general del sistema](#1-visión-general-del-sistema)
2. [Arquitectura y flujo de datos](#2-arquitectura-y-flujo-de-datos)
3. [Requisitos e instalación](#3-requisitos-e-instalación)
4. [Convención de nombres de archivos](#4-convención-de-nombres-de-archivos)
5. [Uso desde línea de comandos](#5-uso-desde-línea-de-comandos)
6. [Módulos Python — Referencia detallada](#6-módulos-python--referencia-detallada)
   - [6.1 main.py — Punto de entrada](#61-mainpy--punto-de-entrada)
   - [6.2 file_parser.py — Parser de nombres DJI](#62-file_parserpy--parser-de-nombres-dji)
   - [6.3 extractor.py — Wrapper del SDK](#63-extractorpy--wrapper-del-sdk)
   - [6.4 analyzer.py — Análisis térmico y ROIs](#64-analyzerpy--análisis-térmico-y-rois)
   - [6.5 roi_tool.py — Selector interactivo de ROI](#65-roi_toolpy--selector-interactivo-de-roi)
   - [6.6 reporter.py — Generador de PDF](#66-reporterpy--generador-de-pdf)
7. [Cómo funciona el SDK por debajo](#7-cómo-funciona-el-sdk-por-debajo)
8. [Estructura de directorios](#8-estructura-de-directorios)
9. [Guía de modificación](#9-guía-de-modificación)
10. [Referencia rápida de la API C del SDK](#10-referencia-rápida-de-la-api-c-del-sdk)
11. [Paletas de color disponibles](#11-paletas-de-color-disponibles)
12. [Clasificación de anomalías térmicas](#12-clasificación-de-anomalías-térmicas)
13. [Solución de problemas](#13-solución-de-problemas)

---

## 1. Visión general del sistema

El sistema tiene **dos capas**:

```
┌─────────────────────────────────────────────────────────┐
│                    thermal_inspector/                     │
│  (Python) CLI interactiva + ROI gráfico + informes PDF   │
├─────────────────────────────────────────────────────────┤
│              DJI Thermal SDK v1.8 (TSDK)                 │
│  (C/C++) Bibliotecas nativas precompiladas               │
│  Binario CLI: dji_irp (utility/bin/linux/release_x64/)   │
└─────────────────────────────────────────────────────────┘
```

**Capa inferior — TSDK:** Bibliotecas `.so` (Linux) / `.dll` (Windows) que decodifican
imágenes R-JPEG de cámaras térmicas DJI. Incluye el ejecutable `dji_irp` que expone
las funciones del SDK como comandos de terminal.

**Capa superior — thermal_inspector:** Aplicación Python que:
1. Encuentra y empareja imágenes térmicas/visuales por nombre de archivo.
2. Llama a `dji_irp` via `subprocess` para extraer datos de temperatura y pseudocolor.
3. Abre una interfaz gráfica (tkinter) para definir regiones de interés (ROIs).
4. Analiza temperaturas en las ROIs definidas.
5. Anota la imagen térmica con las marcas de ROI (líneas y cajas visibles en el PDF).
6. Genera un informe PDF profesional con logo, termogramas, gráficos y diagnósticos.

### Cámaras soportadas

| Cámara | Desde versión SDK |
|--------|-------------------|
| Zenmuse H20T | v1.0 |
| Zenmuse XT S | v1.0 |
| M2EA (Mavic 2 Enterprise Advanced) | v1.1 |
| Zenmuse H20N | v1.3 |
| M30T | v1.3 |
| M3TD | v1.5 |
| M4T | v1.7 |

---

## 2. Arquitectura y flujo de datos

```
Carpeta de imágenes DJI
  │
  ▼
file_parser.py ──── Busca *.jpeg/*.jpg, parsea nombres, empareja T+V
  │
  ▼
extractor.py ────── Llama a dji_irp (subprocess) para cada imagen térmica
  │                  ├── extract_temperature()  → array float32 H×W (°C)
  │                  └── extract_pseudocolor()  → array uint8 H×W×3 (RGB)
  ▼
roi_tool.py ─────── Ventana tkinter interactiva
  │                  ├── Dibuja líneas (LineROI) sobre cables
  │                  └── Dibuja cajas (BoxROI) sobre componentes
  ▼
analyzer.py ─────── Calcula estadísticas por ROI
  │                  ├── t_max, t_min, t_mean, t_start, t_end por línea
  │                  ├── t_max, t_min, t_mean por caja
  │                  ├── ΔT = t_max - t_mean (global)
  │                  └── Clasificación: Normal/Leve/Moderado/Serio/Crítico
  ▼
main.py ─────────── Anota la imagen con ROIs (líneas + cajas dibujadas)
  │                  Solicita datos textuales al usuario
  ▼
reporter.py ─────── Genera PDF con ReportLab
                     ├── Portada con logo QNT Drones + datos del informe
                     ├── Índice de termogramas
                     └── Una página por termograma:
                         ├── Imagen pseudocolor (con ROIs marcados) + imagen visual
                         ├── Tabla de datos + gráfico de perfil térmico
                         ├── Gráfico de temperaturas en puntos A/B
                         ├── Tabla de estadísticas por línea
                         └── Diagnóstico + recomendaciones
```

### Flujo de archivos intermedios

```
Imagen R-JPEG ──→ dji_irp ──→ cache/<stem>/measure_float32.raw  (temperatura)
                          └──→ cache/<stem>/process_hot_iron.raw (pseudocolor)
```

Los `.raw` se guardan en `thermal_inspector/cache/<nombre_imagen>/`.

---

## 3. Requisitos e instalación

### 3.1 Requisitos del sistema

- **OS:** Linux x64 (probado) o Windows x64
- **Python:** 3.10+
- **Display:** Se requiere un servidor X11/Wayland para la herramienta de ROI (tkinter)
- **SDK:** Las bibliotecas `.so` deben estar en `utility/bin/linux/release_x64/`

### 3.2 Dependencias Python

```
numpy>=1.24
Pillow>=9.0
reportlab>=4.0
matplotlib>=3.6
tkinter (incluido en python3-tk)
```

### 3.3 Instalación

```bash
# 1. Instalar dependencias de sistema (Ubuntu/Debian)
sudo apt install python3-tk

# 2. Instalar dependencias Python
cd thermal_inspector/
pip install -r requirements.txt

# 3. Verificar que el binario dji_irp existe y tiene permisos
ls -la ../utility/bin/linux/release_x64/dji_irp
chmod +x ../utility/bin/linux/release_x64/dji_irp

# 4. Verificar que las bibliotecas .so están presentes
ls ../utility/bin/linux/release_x64/*.so
```

Las bibliotecas `.so` necesarias (según `libv_list.ini`) son:
- `libv_dirp.so` — Biblioteca principal del DIRP
- `libv_girp.so` — Motor GIRP
- `libv_iirp.so` — Motor IIRP
- `libv_hirp.so` — Motor HIRP

---

## 4. Convención de nombres de archivos

El sistema espera nombres de archivo con el siguiente formato:

```
DJI_YYYYMMDDHHMMSS_NNNN_T_NOMBRE.jpeg   ← imagen térmica (R-JPEG)
DJI_YYYYMMDDHHMMSS_NNNN_V_NOMBRE.jpeg   ← imagen visual (RGB)
```

| Campo | Descripción | Ejemplo |
|-------|-------------|---------|
| `YYYYMMDDHHMMSS` | Fecha y hora de captura | `20260320105538` |
| `NNNN` | Número de secuencia (4 dígitos) | `0001` |
| `T` / `V` | Tipo: **T**érmica o **V**isual | `T` |
| `NOMBRE` | Identificador libre (ej: nombre del poste) | `Poste1` |

**Emparejamiento:** Se emparejan automáticamente las imágenes T y V que comparten
el mismo `NNNN` (secuencia) y `NOMBRE`. La imagen visual es opcional.

**Ejemplo de carpeta de imágenes:**
```
imagenes/
├── DJI_20260320105538_0001_T_Poste1.jpeg   ← térmica
├── DJI_20260320105538_0001_V_Poste1.jpeg   ← visual (par)
├── DJI_20260320110012_0002_T_Poste2.jpeg   ← térmica
└── DJI_20260320110012_0002_V_Poste2.jpeg   ← visual (par)
```

---

## 5. Uso desde línea de comandos

### 5.1 Uso básico

```bash
cd thermal_inspector/
python3 main.py --images /ruta/a/carpeta/imagenes/
```

### 5.2 Todas las opciones

```bash
python3 main.py \
  --images /ruta/imagenes/ \        # Carpeta con R-JPEGs (requerido)
  --output informe.pdf \            # Ruta del PDF de salida
  --emissivity 0.95 \               # Emisividad del material (0.10–1.00)
  --distance 5.0 \                  # Distancia al objetivo en metros
  --humidity 70.0 \                 # Humedad relativa (%)
  --ambient 25.0 \                  # Temperatura ambiente (°C)
  --empresa "Mi Empresa" \          # Nombre de la empresa
  --inspector "Juan Pérez" \        # Nombre del inspector
  --ubicacion "Planta Norte"        # Ubicación general
```

### 5.3 Flujo interactivo

Al ejecutar, el sistema:

1. **Busca imágenes** en la carpeta indicada y muestra un listado.
2. **Pide datos del informe** (empresa, inspector, ubicación, N° informe) si no se
   proporcionaron por CLI.
3. **Por cada imagen térmica:**
   - Extrae temperatura y pseudocolor via `dji_irp`.
   - Abre la ventana de **selección de ROI** (tkinter).
   - Anota la imagen térmica con las marcas de ROI.
   - Pide datos textuales (equipo, componente, diagnóstico, etc.).
4. **Genera el PDF** al finalizar todas las imágenes.

### 5.4 Controles de la herramienta ROI

| Tecla/Acción | Función |
|--------------|---------|
| Click izquierdo | Anclar punto / confirmar segundo punto |
| Mover mouse | Vista previa (rubber-band) |
| `l` | Cambiar a modo **línea** |
| `b` | Cambiar a modo **caja** |
| `n` | Nueva línea (resetea el ancla) |
| `Esc` | Cancelar ROI en progreso |
| `q` o cerrar ventana | Finalizar y continuar |

**Líneas** (`Li1`, `Li2`, ...): Se dibujan sobre cables o elementos lineales.
Generan un perfil térmico continuo y un gráfico de temperaturas en los extremos.

**Cajas** (`Bx1`, `Bx2`, ...): Se dibujan sobre componentes rectangulares.
Reportan temperatura máxima del área encerrada.

---

## 6. Módulos Python — Referencia detallada

### 6.1 `main.py` — Punto de entrada

Orquesta todo el flujo. Funciones principales:

| Función | Descripción |
|---------|-------------|
| `_annotate_image(color_rgb, lines, boxes)` | Dibuja las marcas de ROI sobre una copia de la imagen pseudocolor |
| `parse_args()` | Define y parsea argumentos CLI con `argparse` |
| `collect_meta(args)` | Pide datos del informe al usuario (interactivo) |
| `collect_entry_inputs(pole_name, ubicacion)` | Pide datos por imagen (ubicación, equipo, componente, diagnóstico, etc.) |
| `process_image(pair, args, cache_base)` | Pipeline completo para una imagen: extracción → ROI → análisis → anotación |
| `main()` | Flujo principal: buscar imágenes → procesar → generar PDF |

**`_annotate_image(color_rgb, lines, boxes) → ndarray`**

Dibuja sobre una copia de la imagen pseudocolor:
- **Líneas**: con los mismos colores que los gráficos (rojo, verde, azul, naranja, púrpura), incluyendo
  puntos en los extremos y etiquetas (`Li1`, `Li2`...).
- **Cajas**: en amarillo con etiquetas (`Bx1`, `Bx2`...).
- Usa fuente DejaVu Bold 14px (con fallback a fuente default).

La imagen anotada es la que aparece en el termograma del PDF.

**Logo:** `main.py` busca automáticamente `qntDrones.png` en la raíz del SDK
(un nivel arriba de `thermal_inspector/`). Si lo encuentra, lo pasa al reporte.

**Salida por defecto:** `thermal_inspector/output/Informe_Termografico_YYYYMMDD_HHMMSS.pdf`

**Manejo de errores:** Si una imagen falla, pregunta al usuario si desea continuar.
Si se interrumpe con Ctrl+C, genera un informe parcial con las imágenes ya procesadas.

---

### 6.2 `file_parser.py` — Parser de nombres DJI

Parsea nombres de archivos DJI y agrupa imágenes térmicas con sus pares visuales.

#### Clases

**`ImageInfo`** (dataclass):
| Campo | Tipo | Descripción |
|-------|------|-------------|
| `path` | `str` | Ruta completa al archivo |
| `stem` | `str` | Nombre sin extensión |
| `timestamp` | `datetime | None` | Fecha/hora de captura |
| `sequence` | `str` | Número de secuencia (`"0001"`) |
| `pole_name` | `str` | Nombre del poste/punto |
| `is_thermal` | `bool` | `True` si es imagen térmica |

#### Funciones

**`parse_filename(filepath) → ImageInfo | None`**
Parsea un nombre de archivo DJI. Retorna `None` si el nombre no coincide con el patrón.

```python
info = parse_filename("/ruta/DJI_20260320105538_0001_T_Poste1.jpeg")
# info.pole_name == "Poste1"
# info.is_thermal == True
# info.sequence == "0001"
```

**`find_image_pairs(folder) → list[dict]`**
Escanea una carpeta y retorna una lista de diccionarios:

```python
[
    {
        "sequence": "0001",
        "pole_name": "Poste1",
        "thermal": ImageInfo(...),  # siempre presente
        "rgb": ImageInfo(...),      # o None si no hay par visual
    },
    ...
]
```

**Regex del patrón:** `^DJI_(\d{14})_(\d{4})_(T|V)_(.+)\.jpe?g$`

> **Para modificar:** Si tus archivos usan otro formato de nombre, modificá la regex
> `_FILENAME_RE` en este módulo y ajustá los grupos de captura en `parse_filename()`.

---

### 6.3 `extractor.py` — Wrapper del SDK

Interfaz entre Python y el binario `dji_irp` del TSDK. Ejecuta el binario via `subprocess`.

#### Constantes

| Constante | Valor | Descripción |
|-----------|-------|-------------|
| `SDK_ROOT` | `..` (relativo a `thermal_inspector/`) | Raíz del SDK |
| `BIN_DIR` | `utility/bin/linux/release_x64/` | Directorio de binarios |
| `DJI_IRP` | `BIN_DIR/dji_irp` | Ruta al ejecutable |

#### Funciones

**`get_cache_dir(image_path, base_cache) → str`**
Crea y retorna un directorio de caché para una imagen (basado en su nombre sin extensión).

**`extract_temperature(image_path, cache_dir, emissivity, distance, humidity, ambient) → (array, w, h)`**

Extrae temperatura pixel a pixel. Ejecuta internamente:
```bash
dji_irp -s <imagen> -a measure -o <cache>/measure_float32.raw \
        --measurefmt float32 \
        --emissivity 0.95 --distance 5.0 --humidity 70.0 --ambient 25.0
```

Retorna:
- `array`: `numpy.ndarray` de forma `(H, W)`, `float32`, valores en °C
- `w`, `h`: ancho y alto de la imagen

**`extract_pseudocolor(image_path, cache_dir, palette) → (array, w, h)`**

Genera imagen RGB con paleta de color. Ejecuta internamente:
```bash
dji_irp -s <imagen> -a process -o <cache>/process_<palette>.raw -p <palette>
```

Retorna:
- `array`: `numpy.ndarray` de forma `(H, W, 3)`, `uint8`, RGB
- `w`, `h`: ancho y alto de la imagen

**Parámetros de medición y su efecto:**

| Parámetro | Default | Rango típico | Efecto |
|-----------|---------|-------------|--------|
| `emissivity` | 0.95 | 0.10–1.00 | Capacidad del material de emitir radiación térmica |
| `distance` | 5.0 m | 1–1000 m | Distancia cámara-objetivo (compensa absorción atmosférica) |
| `humidity` | 70.0% | 20–100% | Humedad relativa (afecta absorción atmosférica) |
| `ambient` | 25.0°C | -40–80°C | Temperatura ambiente (compensación de fondo) |

> **Para modificar:** Si usás Linux x86 o Windows, cambiá `BIN_DIR` para que apunte
> al directorio correcto (`linux/release_x86`, `windows/release_x64`, etc.).

---

### 6.4 `analyzer.py` — Análisis térmico y ROIs

Define las ROIs y ejecuta el análisis estadístico de temperaturas.

#### Clases ROI

**`LineROI`** (dataclass):
```python
LineROI(label="Li1", p1=(x1, y1), p2=(x2, y2))
```
Línea entre dos puntos en coordenadas de imagen (píxeles).

**`BoxROI`** (dataclass):
```python
BoxROI(label="Bx1", x1=100, y1=50, x2=200, y2=150)
```
Rectángulo definido por esquina superior-izquierda y esquina inferior-derecha.

#### Funciones internas

**`_sample_line(temp_array, p1, p2, n_samples=None) → ndarray`**
Muestrea temperaturas a lo largo de la línea. Por defecto (`n_samples=None`),
calcula automáticamente la cantidad de muestras según la longitud en píxeles de la
línea (`hypot(dx, dy)`), tomando un valor por cada píxel real. Si se pasa un valor
explícito, usa ese número fijo de muestras.

**`_sample_box(temp_array, roi) → ndarray`**
Extrae todos los valores de temperatura dentro del rectángulo.

**`_classify(delta_t) → (estado, urgencia)`**
Clasifica la anomalía térmica según ΔT (ver [sección 12](#12-clasificación-de-anomalías-térmicas)).

#### Función principal

**`run_full_analysis(temp_array, lines, boxes) → dict`**

Retorna:
```python
{
    "delta_t": float,       # t_max - t_mean (global de todas las ROIs)
    "estado": str,          # "Normal", "Leve", "Moderado", "Serio", "Crítico"
    "urgencia": str,        # "—", "Baja", "Media", "Alta", "Urgente"
    "t_max": float,         # Temperatura máxima global (°C)
    "t_min": float,         # Temperatura mínima global (°C)
    "t_mean": float,        # Temperatura promedio global (°C)
    "line_stats": [         # Estadísticas por línea
        {
            "label": "Li1",
            "t_max": float,
            "t_min": float,
            "t_mean": float,
            "t_start": float,   # Temperatura en el punto A (inicio de la línea)
            "t_end": float,     # Temperatura en el punto B (fin de la línea)
            "n": int,           # número de muestras
            "samples": list,    # valores individuales (para gráfico de perfil)
        }, ...
    ],
    "box_stats": [          # Estadísticas por caja
        {
            "label": "Bx1",
            "t_max": float,
            "t_min": float,
            "t_mean": float,
            "n": int,
        }, ...
    ],
}
```

Si no se definieron ROIs, las estadísticas globales se calculan sobre la imagen completa.

#### Clase auxiliar: `StatisticalAnalyzer`

Genera un gráfico de torta para distribución de categorías visuales de archivos.
Se usa con un `DataFrame` de pandas. No es parte del flujo principal de inspección;
es una utilidad auxiliar que quedó de una versión anterior. Requiere `pandas` instalado
solo si se invoca esta clase.

---

### 6.5 `roi_tool.py` — Selector interactivo de ROI

Ventana gráfica basada en tkinter para definir líneas y cajas sobre la imagen térmica.

#### Clase `ROITool`

```python
tool = ROITool(
    temp_array,         # ndarray float32 (H, W) — temperaturas
    pseudocolor_rgb,    # ndarray uint8 (H, W, 3) — imagen de fondo
    title="Poste1",     # título de la ventana
    max_w=900,          # ancho máximo de la ventana
    max_h=680,          # alto máximo de la ventana
)
lines, boxes = tool.run()   # bloquea hasta que el usuario cierre
```

- `lines`: `list[LineROI]`
- `boxes`: `list[BoxROI]`

#### Interfaz gráfica

La ventana se divide en:
- **Izquierda:** Canvas con la imagen pseudocolor. El usuario dibuja ROIs haciendo click.
- **Derecha:** Panel de información con:
  - Modo actual (LÍNEA / CAJA)
  - Controles disponibles
  - Temperatura bajo el cursor en tiempo real
  - Contador de ROIs definidos
  - Botones "Finalizar" y "Cancelar actual"

La imagen se escala automáticamente para ajustarse a `max_w × max_h` sin distorsión.
Las coordenadas se convierten de canvas a imagen real al confirmar cada ROI.

> **Para modificar:** Si necesitás ejecutar sin interfaz gráfica (modo headless),
> reemplazá la llamada a `ROITool` en `process_image()` (`main.py`) con ROIs
> predefinidos. Ejemplo:
> ```python
> lines = [LineROI("Li1", (0, 256), (639, 256))]
> boxes = [BoxROI("Bx1", 100, 100, 300, 300)]
> ```

---

### 6.6 `reporter.py` — Generador de PDF

Genera informes PDF profesionales usando ReportLab. El diseño imita un informe
de mantenimiento predictivo por termografía.

#### Clase `ThermalReport`

```python
report = ThermalReport(
    output_path="informe.pdf",
    meta={
        "empresa": "...",
        "inspector": "...",
        "ubicacion_general": "...",
        "id_informe": "INF-20260325-1430",
        "fecha": "25/03/2026",
    },
    logo_path="/ruta/a/logo.png",   # opcional, se muestra en la portada
)
```

**`add_entry(entry) → int`**
Agrega un termograma al informe. `entry` es un diccionario con:

| Clave | Tipo | Descripción |
|-------|------|-------------|
| `color_rgb` | `ndarray (H,W,3)` | Imagen pseudocolor con ROIs anotados |
| `rgb_path` | `str | None` | Ruta a la imagen visual |
| `ubicacion` | `str` | Ubicación del componente |
| `equipo` | `str` | Nombre del equipo |
| `componente` | `str` | Componente inspeccionado |
| `estado` | `str` | Diagnóstico (Normal, Leve, etc.) |
| `prioridad` | `str` | Prioridad de intervención |
| `precinto` | `str` | Número de precinto |
| `t_max` | `float` | Temperatura máxima |
| `line_stats` | `list` | Estadísticas de líneas (con `samples`, `t_start`, `t_end`) |
| `box_stats` | `list` | Estadísticas de cajas |
| `diagnostico_texto` | `str` | Texto libre de diagnóstico |
| `recomendaciones` | `str` | Recomendaciones |
| `reparaciones` | `str` | Reparaciones realizadas |

Retorna el número de página donde se ubicará el termograma.

**`build()`**
Genera el PDF. Estructura del documento:

```
Página 1: Portada
  - Logo QNT Drones (si existe qntDrones.png en la raíz del SDK)
  - Título "Mantenimiento Predictivo - Termografía"
  - Tabla con datos del informe

Página 2: Índice de termogramas
  - Tabla con todas las entradas: ubicación, equipo, componente,
    diagnóstico (coloreado), prioridad, precinto, página

Páginas 3+: Un termograma por página
  ┌────────────────────┬────────────────────┐
  │    TERMOGRAMA      │   IMAGEN VISUAL    │  ← encabezados azules
  ├────────────────────┼────────────────────┤
  │  (pseudocolor con  │  (foto RGB)        │  ← imágenes
  │   ROIs marcados)   │                    │
  ├────────────────────┼────────────────────┤
  │   TABLA DE DATOS   │  PERFIL TÉRMICO    │  ← encabezados azules
  ├────────────────────┼────────────────────┤
  │  Ubicación: ...    │  (gráfico perfil)  │
  │  Equipo: ...       │                    │
  │  Diagnóstico: ...  │  (gráfico puntos   │
  │  Measurements      │   A/B extremos)    │
  │  Bx1 Maximum: X°C  │                    │
  │  ...               │  ┌──────────────┐  │
  │                    │  │ Li1 min max  │  │
  │                    │  │ Li2 min max  │  │
  │                    │  └──────────────┘  │
  ├────────────────────┴────────────────────┤
  │  DIAGNÓSTICO: texto libre               │
  │  RECOMENDACIONES: texto libre            │
  │  REPARACIONES REALIZADAS: texto libre    │
  └─────────────────────────────────────────┘
```

#### Gráficos generados

**`_make_profile_chart()`** — Perfil térmico continuo. Grafica los valores de
temperatura muestreados pixel a pixel a lo largo de cada `LineROI`.
Eje X: posición a lo largo de la línea (en píxeles). Eje Y: temperatura (°C).

**`_make_endpoints_chart()`** — Temperaturas en puntos de referencia. Muestra las
temperaturas en los extremos (Punto A = inicio, Punto B = fin) de cada línea.
Usa marcadores: círculo para Punto A, cuadrado para Punto B. Incluye los valores
de temperatura anotados y una leyenda.

Cada línea se muestra en un color distinto (compartido entre ambos gráficos):

| Línea | Color |
|-------|-------|
| Li1 | Rojo (`#C0392B`) |
| Li2 | Verde (`#27AE60`) |
| Li3 | Azul (`#2980B9`) |
| Li4 | Naranja (`#E67E22`) |
| Li5 | Púrpura (`#8E44AD`) |

#### Colores corporativos

| Constante | Color | Uso |
|-----------|-------|-----|
| `BLUE_DARK` | `#16365C` | Encabezados, barras superiores |
| `BLUE_LIGHT` | `#DCE6F1` | Fondos de secciones |
| `GREEN_OK` | `#92D050` | Celda "Admisible" / "Normal" |
| `GREY_BG` | `#F2F2F2` | Fondo de celdas de la portada |

> **Para modificar colores:** Están en `_LINE_COLORS_MPL` (matplotlib) y
> `_LINE_COLORS_RL` (ReportLab). Modificá ambas listas para mantener consistencia.
> También actualizar `_LINE_COLORS_PIL` en `main.py` para la anotación de imagen.

---

## 7. Cómo funciona el SDK por debajo

El código Python **no usa la API C directamente** (no usa `ctypes` ni `cffi`).
En su lugar, llama al ejecutable precompilado `dji_irp` via `subprocess.run()`.

### Flujo interno de `dji_irp`

```
1. Lee el archivo R-JPEG completo en memoria
2. Llama a dirp_create_from_rjpeg() → obtiene un DIRP_HANDLE
3. Configura parámetros de medición (emissivity, distance, humidity, ambient)
   via dirp_set_measurement_params()
4. Según la acción (-a):
   - "extract" → dirp_get_original_raw()    → escribe RAW16 (uint16)
   - "measure" → dirp_measure_ex()          → escribe FLOAT32 (°C por píxel)
   - "process" → dirp_set_pseudo_color() + dirp_process() → escribe RGB888
5. Escribe el buffer resultante como archivo .raw binario
6. Imprime dimensiones (width × height) en stdout
7. Llama a dirp_destroy() para liberar recursos
```

### Formatos de salida de `dji_irp`

| Acción | Formato | Bytes por píxel | dtype numpy |
|--------|---------|-----------------|-------------|
| `extract` | RAW16 | 2 | `uint16` |
| `measure` (default) | INT16 (décimas de °C) | 2 | `int16` |
| `measure --measurefmt float32` | FLOAT32 (°C directos) | 4 | `float32` |
| `process` | RGB888 | 3 | `uint8` |

### Parseo de dimensiones

`extractor.py` parsea el stdout de `dji_irp` buscando:
```
image width : NNN
image height : NNN
```
con la regex: `image\s+width\s*:\s*(\d+).*?image height\s*:\s*(\d+)`

---

## 8. Estructura de directorios

```
dji_thermal_sdk_v1.8_20250829/
├── Readme.md                           # Documentación oficial del SDK
├── History.txt                         # Changelog (v1.0 → v1.8)
├── License.txt                         # Licencia MIT + EULA
├── qntDrones.png                       # Logo QNT Drones (portada del informe)
│
├── tsdk-core/                          # Núcleo del SDK
│   ├── api/
│   │   ├── dirp_api.h                  # API C principal (464 líneas)
│   │   └── dirp_wrapper.h              # Wrapper para plugins vendor
│   └── lib/
│       ├── linux/release_x64/          # Bibliotecas .so para Linux x64
│       ├── linux/release_x86/          # Bibliotecas .so para Linux x86
│       ├── windows/release_x64/        # DLLs para Windows x64
│       └── windows/release_x86/        # DLLs para Windows x86
│
├── utility/bin/                        # Binarios precompilados
│   ├── linux/release_x64/
│   │   ├── dji_irp                     # ← ESTE es el que llama Python
│   │   ├── dji_irp_omp                 # Variante con OpenMP (batch)
│   │   ├── dji_ircm                    # Color mapping para ortomosaicos
│   │   └── *.so                        # Bibliotecas compartidas
│   └── windows/release_x64/
│       └── *.exe, *.dll
│
├── sample/                             # Código fuente C++ de ejemplo
│   ├── dji_irp.cpp                     # Fuente de dji_irp
│   ├── dji_irp_omp.cpp                 # Fuente de dji_irp_omp
│   ├── dji_ircm.cpp                    # Fuente de dji_ircm
│   ├── CMakeLists.txt                  # Build con CMake
│   ├── build.sh / build.bat            # Scripts de compilación
│   └── argparse/argagg.hpp             # Librería de parseo de args
│
├── dataset/                            # Datos de ejemplo
│   ├── H20T/                           # Imágenes de ejemplo (si presentes)
│   └── orthomosaic/ir.raw              # Ortomosaico de ejemplo
│
├── doc/                                # Documentación API (Doxygen)
│   ├── index.html
│   └── html/, latex/, rtf/
│
└── thermal_inspector/                  # ★ APLICACIÓN PYTHON ★
    ├── main.py                         # Punto de entrada + anotación de imagen
    ├── file_parser.py                  # Parser de nombres DJI
    ├── extractor.py                    # Wrapper de dji_irp
    ├── analyzer.py                     # Análisis de ROIs
    ├── roi_tool.py                     # Selector gráfico de ROI
    ├── reporter.py                     # Generador de PDF (con logo + gráficos)
    ├── requirements.txt                # Dependencias Python
    ├── DOCUMENTACION.md                # ← Este archivo
    ├── cache/                          # Archivos .raw intermedios
    └── output/                         # PDFs generados
```

---

## 9. Guía de modificación

### 9.1 Agregar un nuevo tipo de ROI (ej: SpotROI — punto individual)

1. **`analyzer.py`**: Crear dataclass y función de muestreo:
   ```python
   @dataclass
   class SpotROI:
       label: str
       x: int
       y: int

   def _sample_spot(temp_array, roi):
       return temp_array[roi.y, roi.x]
   ```

2. **`analyzer.py`**: Agregar procesamiento en `run_full_analysis()`:
   ```python
   def run_full_analysis(temp_array, lines, boxes, spots=None):
       # ... código existente ...
       spot_stats = []
       for roi in (spots or []):
           t = _sample_spot(temp_array, roi)
           spot_stats.append({"label": roi.label, "temp": float(t)})
       # incluir en el return
   ```

3. **`roi_tool.py`**: Agregar modo SPOT con tecla `s`, commit con un solo click.

4. **`main.py`**: Agregar el nuevo tipo a `_annotate_image()`.

5. **`reporter.py`**: Incluir datos de spots en la tabla de mediciones.

### 9.2 Cambiar el formato de nombre de archivos

Modificar `_FILENAME_RE` en `file_parser.py`. Ejemplo para archivos con formato
`THERMAL_Poste1_001.jpg`:

```python
_FILENAME_RE = re.compile(
    r"^(THERMAL|VISUAL)_(.+)_(\d{3})\.jpe?g$",
    re.IGNORECASE,
)
```

Luego ajustar `parse_filename()` para extraer los campos correctos.

### 9.3 Ejecutar sin interfaz gráfica (headless / automatizado)

En `main.py`, función `process_image()`, reemplazar el bloque del ROITool:

```python
# En lugar de:
# tool = ROITool(temp_array, color_rgb, title=pole_name)
# lines, boxes = tool.run()

# Usar ROIs predefinidos:
h, w = temp_array.shape
lines = [
    LineROI("Li1", (0, h//2), (w-1, h//2)),       # línea horizontal central
]
boxes = [
    BoxROI("Bx1", w//4, h//4, 3*w//4, 3*h//4),   # caja central
]
```

### 9.4 Cambiar la paleta de pseudocolor

En `process_image()` (`main.py`), cambiar el argumento de `extract_pseudocolor()`:

```python
color_rgb, _, _ = extract_pseudocolor(thermal_path, cache_dir, palette="iron_red")
```

Ver [sección 11](#11-paletas-de-color-disponibles) para las paletas disponibles.

### 9.5 Modificar umbrales de clasificación

En `analyzer.py`, función `_classify()`:

```python
def _classify(delta_t):
    if delta_t < 1.0:    return "Normal", "—"
    elif delta_t < 3.0:  return "Leve", "Baja"
    elif delta_t < 10.0: return "Moderado", "Media"
    elif delta_t < 40.0: return "Serio", "Alta"
    else:                return "Crítico", "Urgente"
```

Ajustá los umbrales `1.0`, `3.0`, `10.0`, `40.0` según la norma que uses
(ej: NETA MTS-2017, ISO 18434-1, etc.).

### 9.6 Agregar campos al PDF

En `reporter.py`, método `_entry_pages()`, agregar filas a `data_rows`:

```python
data_rows.append([
    Paragraph("Mi Campo", self._styles["DataKey"]),
    Paragraph(entry.get("mi_campo", "N/A"), self._styles["DataValue"]),
])
```

Y en `main.py`, `collect_entry_inputs()`, agregar el prompt correspondiente.

### 9.7 Cambiar el logo de la portada

Reemplazar `qntDrones.png` en la raíz del SDK, o pasar una ruta diferente al
constructor de `ThermalReport`:

```python
report = ThermalReport(pdf_path, meta, logo_path="/ruta/a/mi_logo.png")
```

El logo se escala automáticamente a un máximo de 5.5 cm manteniendo proporción.

### 9.8 Usar la API C directamente con ctypes (alternativa a subprocess)

Si querés evitar el overhead de `subprocess` y el parseo de stdout:

```python
import ctypes
import numpy as np

lib = ctypes.CDLL("ruta/a/libdirp.so")

# Leer R-JPEG en memoria
with open("imagen.jpeg", "rb") as f:
    data = f.read()

buf = ctypes.create_string_buffer(data)
handle = ctypes.c_void_p()

# Crear handle
ret = lib.dirp_create_from_rjpeg(buf, len(data), ctypes.byref(handle))

# Obtener resolución
class Resolution(ctypes.Structure):
    _fields_ = [("width", ctypes.c_int32), ("height", ctypes.c_int32)]

res = Resolution()
lib.dirp_get_rjpeg_resolution(handle, ctypes.byref(res))

# Medir temperatura (float32)
size = res.width * res.height * 4
temp_buf = (ctypes.c_float * (res.width * res.height))()
lib.dirp_measure_ex(handle, temp_buf, size)

temp_array = np.ctypeslib.as_array(temp_buf).reshape(res.height, res.width)

# Liberar
lib.dirp_destroy(handle)
```

> **Nota:** El buffer R-JPEG (`buf`) debe permanecer en memoria hasta llamar a
> `dirp_destroy()`. No dejar que el garbage collector lo libere antes.

---

## 10. Referencia rápida de la API C del SDK

| Función | Propósito |
|---------|-----------|
| `dirp_create_from_rjpeg(data, size, &handle)` | Crear handle desde buffer R-JPEG |
| `dirp_destroy(handle)` | Liberar handle y recursos |
| `dirp_get_rjpeg_resolution(handle, &res)` | Obtener ancho × alto |
| `dirp_get_original_raw(handle, buf, size)` | Extraer RAW16 original |
| `dirp_measure(handle, buf, size)` | Temperatura en INT16 (décimas °C) |
| `dirp_measure_ex(handle, buf, size)` | Temperatura en FLOAT32 (°C) |
| `dirp_process(handle, buf, size)` | Imagen pseudocolor RGB888 |
| `dirp_process_strech(handle, buf, size)` | Imagen "stretch" FLOAT32 |
| `dirp_set_measurement_params(handle, &params)` | Configurar emisividad, distancia, etc. |
| `dirp_get_measurement_params(handle, &params)` | Leer parámetros de medición |
| `dirp_set_pseudo_color(handle, color_enum)` | Seleccionar paleta de color |
| `dirp_set_isotherm(handle, &isotherm)` | Configurar isoterma |
| `dirp_set_color_bar(handle, &color_bar)` | Configurar barra de color |

**Códigos de error comunes:**

| Código | Nombre | Causa típica |
|--------|--------|-------------|
| 0 | `DIRP_SUCCESS` | OK |
| -2 | `DIRP_ERROR_POINTER_NULL` | Puntero nulo |
| -3 | `DIRP_ERROR_INVALID_PARAMS` | Parámetros fuera de rango |
| -7 | `DIRP_ERROR_RJPEG_PARSE` | Archivo no es R-JPEG válido |
| -15 | `DIRP_ERROR_INVALID_INI` | Falta `libv_list.ini` |
| -16 | `DIRP_ERROR_INVALID_SUB_DLL` | Falta una biblioteca `.so`/`.dll` |

---

## 11. Paletas de color disponibles

Paletas soportadas por `dji_irp -p <nombre>` y `dirp_set_pseudo_color()`:

| Nombre CLI | Enum C | Vista |
|------------|--------|-------|
| `whitehot` | `DIRP_PSEUDO_COLOR_WHITEHOT` | Blanco = caliente |
| `fulgurite` | `DIRP_PSEUDO_COLOR_FULGURITE` | Tonos volcánicos |
| `iron_red` | `DIRP_PSEUDO_COLOR_IRONRED` | Rojo hierro |
| `hot_iron` | `DIRP_PSEUDO_COLOR_HOTIRON` | Hierro caliente (**default del sistema**) |
| `medical` | `DIRP_PSEUDO_COLOR_MEDICAL` | Escala médica |
| `arctic` | `DIRP_PSEUDO_COLOR_ARCTIC` | Tonos fríos |
| `rainbow1` | `DIRP_PSEUDO_COLOR_RAINBOW1` | Arcoíris v1 |
| `rainbow2` | `DIRP_PSEUDO_COLOR_RAINBOW2` | Arcoíris v2 |
| `tint` | `DIRP_PSEUDO_COLOR_TINT` | Tinte |
| `blackhot` | `DIRP_PSEUDO_COLOR_BLACKHOT` | Negro = caliente |

---

## 12. Clasificación de anomalías térmicas

La función `_classify()` en `analyzer.py` clasifica según el **ΔT** (diferencia
entre la temperatura máxima y la temperatura promedio de las ROIs):

| ΔT (°C) | Estado | Urgencia | Acción sugerida |
|----------|--------|----------|-----------------|
| < 1.0 | Normal | — | Sin acción |
| 1.0 – 3.0 | Leve | Baja | Monitorear |
| 3.0 – 10.0 | Moderado | Media | Programar mantenimiento |
| 10.0 – 40.0 | Serio | Alta | Intervención prioritaria |
| > 40.0 | Crítico | Urgente | Intervención inmediata |

> Estos umbrales son orientativos. Ajustalos según la normativa aplicable a tu
> industria y tipo de equipamiento.

---

## 13. Solución de problemas

### `dji_irp` no se encuentra o no tiene permisos

```bash
chmod +x ../utility/bin/linux/release_x64/dji_irp
```

### Error "Could not parse dimensions from dji_irp output"

El SDK no reconoce la imagen. Verificar que:
- El archivo es un R-JPEG genuino (capturado con cámara DJI soportada)
- Las bibliotecas `.so` están en el mismo directorio que `dji_irp`
- `libv_list.ini` existe y lista las bibliotecas correctas

### Error "Cannot open display" en la herramienta ROI

Se necesita un servidor de display (X11/Wayland). Si estás en un servidor remoto:
```bash
# Opción 1: X forwarding
ssh -X usuario@servidor

# Opción 2: VNC/escritorio remoto

# Opción 3: Modo headless (ver sección 9.3)
```

### El PDF se genera pero las imágenes se ven cortadas

Ajustar `img_h` en `reporter.py`, método `_entry_pages()`:
```python
img_h = 7.0 * cm  # Valor actual; aumentar si las imágenes son muy altas
```

### Imágenes no se emparejan (thermal + visual)

Verificar que los nombres siguen la convención exacta:
```
DJI_YYYYMMDDHHMMSS_NNNN_T_NOMBRE.jpeg   ← térmica
DJI_YYYYMMDDHHMMSS_NNNN_V_NOMBRE.jpeg   ← visual
```
El `NNNN` (secuencia) y `NOMBRE` deben coincidir exactamente entre el par T/V.

### El logo no aparece en la portada

Verificar que `qntDrones.png` existe en la raíz del SDK (un nivel arriba de
`thermal_inspector/`). El sistema lo busca automáticamente en esa ubicación.

### Las ROIs no aparecen en la imagen del PDF

Las marcas de ROI se dibujan con `_annotate_image()` en `main.py`. Verificar que:
- Se definieron líneas o cajas en la herramienta de ROI
- La función no arrojó errores (revisar la salida de consola)

### Error de memoria con imágenes muy grandes

Las imágenes térmicas DJI suelen ser 640×512 (VGA) o similares. Si procesás
ortomosaicos grandes, considerá:
- Pasar un valor fijo a `n_samples` en `_sample_line()` para limitar las muestras
- Procesar por lotes más pequeños
