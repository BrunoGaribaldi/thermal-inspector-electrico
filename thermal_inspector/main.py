#!/usr/bin/env python3
"""
main.py — Thermal Inspection Reporting System
DJI Thermal SDK + Interactive ROI + PDF Report Generator

Usage:
  python3 main.py --images /path/to/images/ [opciones]

Opciones:
  --images PATH        Carpeta con imágenes DJI R-JPEG (requerido)
  --output PATH        Ruta del PDF de salida
  --emissivity FLOAT   Emisividad (default: 0.95)
  --distance FLOAT     Distancia al objetivo en metros (default: 5.0)
  --humidity FLOAT     Humedad relativa % (default: 70.0)
  --ambient FLOAT      Temperatura ambiente °C (default: 25.0)
  --empresa STR        Nombre de la empresa
  --inspector STR      Nombre del inspector
  --ubicacion STR      Ubicación general del relevamiento
"""

import argparse
import csv
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path

# Add this folder to path so imports work
sys.path.insert(0, str(Path(__file__).parent))

# Load .env file if present
_env_path = Path(__file__).parent / ".env"
if _env_path.is_file():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

from file_parser import find_image_pairs
from extractor import extract_temperature, extract_pseudocolor, get_cache_dir
from analyzer import LineROI, BoxROI, run_full_analysis
from roi_tool import ROITool
from reporter import ThermalReport

_LINE_COLORS_PIL = [
    (192, 57, 43), (39, 174, 96), (41, 128, 185),
    (230, 126, 34), (142, 68, 173),
]
_BOX_COLOR_PIL = (255, 220, 0)

_POLE_NUM_RE = re.compile(r"[Pp]oste\s*(\d+)")


def _load_pole_coords(csv_path: str) -> dict:
    """Load pole coordinates from CSV. Returns {pole_number_str: coord_string}."""
    coords = {}
    if not os.path.isfile(csv_path):
        return coords
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pole_num = row.get("Poste", "").strip()
            coord = row.get("Coord", "").strip()
            if pole_num and coord:
                coords[pole_num] = coord
    return coords


def _extract_pole_number(pole_name: str) -> str | None:
    """Extract numeric pole ID from a name like 'Poste1' or 'Poste 12'."""
    m = _POLE_NUM_RE.search(pole_name)
    return m.group(1) if m else None


def _make_google_maps_url(coord: str) -> str:
    """Build a Google Maps URL from a coordinate string like '-36.959, -69.419'."""
    parts = [p.strip() for p in coord.split(",")]
    if len(parts) == 2:
        return f"https://www.google.com/maps?q={parts[0]},{parts[1]}"
    return ""


def _annotate_image(color_rgb, lines, boxes):
    """Burn ROI markings onto a copy of the pseudocolor image for the PDF."""
    from PIL import Image as PILImage, ImageDraw, ImageFont
    import numpy as np

    img = PILImage.fromarray(color_rgb.astype(np.uint8)).copy()
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
    except Exception:
        try:
            font = ImageFont.load_default(size=14)
        except TypeError:
            font = ImageFont.load_default()

    for i, line in enumerate(lines):
        c = _LINE_COLORS_PIL[i % len(_LINE_COLORS_PIL)]
        draw.line([line.p1, line.p2], fill=c, width=2)
        r = 4
        for pt in [line.p1, line.p2]:
            draw.ellipse([pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r], fill=c)
        draw.text((line.p1[0] + 6, line.p1[1] - 16), line.label, fill=c, font=font)

    for box in boxes:
        draw.rectangle([box.x1, box.y1, box.x2, box.y2], outline=_BOX_COLOR_PIL, width=2)
        draw.text((box.x1 + 3, box.y1 + 3), box.label, fill=_BOX_COLOR_PIL, font=font)

    return np.array(img)


def parse_args():
    p = argparse.ArgumentParser(
        description="Inspector Termográfico — Genera informes PDF desde imágenes DJI R-JPEG",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument("--images", required=True,
                   help="Carpeta con las imágenes DJI térmicas (R-JPEG)")
    p.add_argument("--output", default=None,
                   help="Ruta de salida del PDF (por defecto: output/Informe_TIMESTAMP.pdf)")
    p.add_argument("--emissivity", type=float, default=0.95,
                   help="Emisividad del material (0.10-1.00, default: 0.95)")
    p.add_argument("--distance", type=float, default=5.0,
                   help="Distancia al objetivo en metros (default: 5.0)")
    p.add_argument("--humidity", type=float, default=70.0,
                   help="Humedad relativa %% (default: 70.0)")
    p.add_argument("--ambient", type=float, default=25.0,
                   help="Temperatura ambiente °C (default: 25.0)")
    p.add_argument("--empresa", default="",
                   help="Nombre de la empresa")
    p.add_argument("--inspector", default="",
                   help="Nombre del inspector")
    p.add_argument("--ubicacion", default="",
                   help="Ubicación general del relevamiento")
    p.add_argument("--gemini-key", default="",
                   help="API key de Google Gemini para diagnóstico IA (o env GEMINI_API_KEY)")
    return p.parse_args()


def prompt(text: str, default: str = "") -> str:
    """CLI prompt with optional default."""
    if default:
        val = input(f"  {text} [{default}]: ").strip()
        return val if val else default
    else:
        return input(f"  {text}: ").strip()


def collect_meta(args) -> dict:
    """Collect report metadata interactively if not provided via CLI."""
    print("\n" + "=" * 55)
    print("  DATOS DEL INFORME")
    print("=" * 55)

    empresa = args.empresa or prompt("Empresa")
    inspector = args.inspector or prompt("Inspector")
    ubicacion = args.ubicacion or prompt("Ubicación general")
    id_informe = prompt("N° Informe", default=datetime.now().strftime("INF-%Y%m%d-%H%M"))
    fecha = datetime.now().strftime("%d/%m/%Y")

    return {
        "empresa": empresa,
        "inspector": inspector,
        "ubicacion_general": ubicacion,
        "id_informe": id_informe,
        "fecha": fecha,
    }


def collect_entry_inputs(pole_name: str, ubicacion_general: str) -> dict:
    """Collect per-image data interactively."""
    print(f"\n  --- {pole_name} ---")
    ubicacion = prompt("  Ubicación", default=ubicacion_general)
    equipo = prompt("  Equipo", default=pole_name)
    componente = prompt("  Componente", default="Seccionador")
    prioridad = prompt("  Prioridad", default="N/A")
    precinto = prompt("  Precinto", default="N/A")
    diagnostico_texto = prompt("  Texto diagnóstico",
                                default="No se observan puntos calientes ni perfil térmico anormal.")

    return {
        "ubicacion": ubicacion,
        "equipo": equipo,
        "componente": componente,
        "prioridad": prioridad,
        "precinto": precinto,
        "diagnostico_texto": diagnostico_texto,
    }


def process_image(pair: dict, args, cache_base: str,
                   pole_coords: dict | None = None,
                   gemini_key: str = "") -> dict:
    """Full pipeline for one thermal/RGB pair."""
    pole_name = pair["pole_name"]
    thermal_path = pair["thermal"].path
    rgb_path = pair["rgb"].path if pair["rgb"] else None

    print(f"\n{'='*55}")
    print(f"  Procesando: {pole_name}")
    print(f"  Imagen térmica: {os.path.basename(thermal_path)}")
    if rgb_path:
        print(f"  Imagen visual:  {os.path.basename(rgb_path)}")
    else:
        print("  Imagen visual:  (no encontrada)")
    print(f"{'='*55}")

    # 1. Extract temperature array
    print("  [1/4] Extrayendo datos de temperatura...")
    cache_dir = get_cache_dir(thermal_path, cache_base)
    temp_array, w, h = extract_temperature(
        thermal_path, cache_dir,
        emissivity=args.emissivity,
        distance=args.distance,
        humidity=args.humidity,
        ambient=args.ambient,
    )
    print(f"        Resolución: {w}×{h}  |  "
          f"Rango: {temp_array.min():.2f}°C — {temp_array.max():.2f}°C")

    # 2. Extract pseudocolor
    print("  [2/4] Generando imagen pseudocolor (hot_iron)...")
    color_rgb, _, _ = extract_pseudocolor(thermal_path, cache_dir, palette="hot_iron")

    # 3. Interactive ROI selection
    print("  [3/4] Abriendo herramienta de selección de ROI...")
    print("        (Dibuja líneas sobre los cables y cajas sobre componentes)")
    try:
        tool = ROITool(temp_array, color_rgb, title=pole_name)
        lines, boxes = tool.run()
    except RuntimeError as e:
        print(f"  ADVERTENCIA: No se pudo abrir herramienta ROI: {e}")
        lines, boxes = [], []

    print(f"        ROIs definidos: {len(lines)} línea(s), {len(boxes)} caja(s)")

    # 4. Analysis
    print("  [4/4] Analizando temperaturas...")
    analysis = run_full_analysis(temp_array, lines, boxes)
    delta_t = analysis["delta_t"]
    estado = analysis["estado"]
    urgencia = analysis["urgencia"]

    print(f"        ΔT = {delta_t:.2f}°C  →  {estado} {urgencia}")

    # 5. Annotate thermal image with ROI markings
    if lines or boxes:
        color_rgb_annotated = _annotate_image(color_rgb, lines, boxes)
        print(f"        Imagen térmica anotada con {len(lines)} línea(s) y {len(boxes)} caja(s)")
    else:
        color_rgb_annotated = color_rgb

    # 6. AI diagnosis via Gemini
    diagnostico_ia = ""
    if gemini_key:
        print("  [IA] Enviando imágenes a Gemini para diagnóstico...")
        try:
            from gemini_inspector import analyze_pole
            diagnostico_ia = analyze_pole(
                api_key=gemini_key,
                pole_name=pole_name,
                thermal_rgb=color_rgb,
                visual_path=rgb_path,
                t_min=float(temp_array.min()),
                t_max=float(temp_array.max()),
            )
            if diagnostico_ia:
                print(f"        Diagnóstico IA recibido ({len(diagnostico_ia)} caracteres)")
            else:
                print("        Diagnóstico IA: sin respuesta")
        except Exception as e:
            print(f"        ERROR en diagnóstico IA: {e}")

    # 7. Collect user text inputs
    user_data = collect_entry_inputs(pole_name, args.ubicacion)

    # 8. Look up GPS coordinates for this pole
    gps_coord = ""
    gps_url = ""
    pole_num = _extract_pole_number(pole_name)
    if pole_num and pole_coords and pole_num in pole_coords:
        gps_coord = pole_coords[pole_num]
        gps_url = _make_google_maps_url(gps_coord)
        print(f"        Coordenadas GPS: {gps_coord}")
    elif pole_num:
        print(f"        Coordenadas GPS: no encontradas para poste {pole_num}")

    entry = {
        **user_data,
        **analysis,
        "pole_name": pole_name,
        "thermal_path": thermal_path,
        "rgb_path": rgb_path,
        "color_rgb": color_rgb_annotated,
        "temp_array": temp_array,
        "timestamp": pair["thermal"].timestamp,
        "gps_coord": gps_coord,
        "gps_url": gps_url,
        "diagnostico_ia": diagnostico_ia,
    }

    return entry


def main():
    args = parse_args()

    # Setup output dirs
    script_dir = Path(__file__).parent
    output_dir = script_dir / "output"
    cache_dir = script_dir / "cache"
    output_dir.mkdir(exist_ok=True)
    cache_dir.mkdir(exist_ok=True)

    # Output PDF path
    if args.output:
        pdf_path = args.output
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_path = str(output_dir / f"Informe_Termografico_{ts}.pdf")

    print("\n" + "=" * 55)
    print("  INSPECTOR TERMOGRÁFICO — DJI Thermal SDK")
    print("=" * 55)

    # Find image pairs
    try:
        pairs = find_image_pairs(args.images)
    except FileNotFoundError as e:
        print(f"\nERROR: {e}")
        sys.exit(1)

    print(f"\nImágenes encontradas: {len(pairs)}")
    for i, p in enumerate(pairs, 1):
        rgb_status = "✓ RGB" if p["rgb"] else "✗ sin RGB"
        print(f"  [{i}] {p['pole_name']} — {os.path.basename(p['thermal'].path)}  ({rgb_status})")

    # Load pole coordinates from CSV
    csv_path = str(script_dir / "pos_postes.csv")
    pole_coords = _load_pole_coords(csv_path)
    if pole_coords:
        print(f"\nCoordenadas de postes cargadas: {len(pole_coords)} entradas")
    else:
        print(f"\nADVERTENCIA: No se encontraron coordenadas en {csv_path}")

    # Collect report metadata
    meta = collect_meta(args)

    # Logo
    logo_path = str(Path(__file__).parent.parent / "qntDrones.png")
    if not os.path.isfile(logo_path):
        logo_path = None

    # Gemini API key
    gemini_key = args.gemini_key or os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        print("\nDiagnóstico IA habilitado (Gemini)")
    else:
        print("\nDiagnóstico IA deshabilitado (usar --gemini-key o env GEMINI_API_KEY)")

    # Process each image
    report = ThermalReport(pdf_path, meta, logo_path=logo_path)
    processed = 0

    for i, pair in enumerate(pairs, 1):
        print(f"\n[ Imagen {i}/{len(pairs)} ]")
        try:
            entry = process_image(pair, args, str(cache_dir), pole_coords,
                                  gemini_key=gemini_key)
            page = report.add_entry(entry)
            print(f"  Entrada agregada al informe (pág. {page})")
            processed += 1
        except KeyboardInterrupt:
            print("\n\n  Interrumpido por el usuario.")
            if processed == 0:
                print("  No se generó ningún informe.")
                sys.exit(0)
            print(f"  Se procesaron {processed} imágenes. Generando informe parcial...")
            break
        except Exception as e:
            print(f"\n  ERROR procesando {pair['pole_name']}: {e}")
            traceback.print_exc()
            cont = input("  ¿Continuar con la siguiente imagen? [s/n]: ").strip().lower()
            if cont != "s":
                break

    # Generate PDF
    if processed > 0:
        print(f"\n{'='*55}")
        print(f"  Generando PDF con {processed} termograma(s)...")
        try:
            report.build()
            print(f"\n  ✓ Informe generado exitosamente:")
            print(f"    {pdf_path}")
        except Exception as e:
            print(f"\n  ERROR generando PDF: {e}")
            traceback.print_exc()
    else:
        print("\n  No se generó ningún informe.")


if __name__ == "__main__":
    main()
