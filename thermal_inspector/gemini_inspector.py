"""
gemini_inspector.py — AI-powered pole inspection using Google Gemini vision.

Sends visual + thermal images to Gemini and returns a concise diagnostic.
Uses a fallback chain of models: if one fails, tries the next automatically.
"""

import time
import numpy as np
from PIL import Image as PILImage

_MODELS = [
    "gemini-3.1-pro-preview",
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash-preview-04-17",
    "gemini-2.5-pro-preview-03-25",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]

_MAX_RETRIES = 2
_RETRY_DELAY = 3

_PROMPT_TEMPLATE = """Sos un inspector profesional de líneas eléctricas de media y baja tensión. \
Analizá las siguientes imágenes del {pole_name}.

{image_description}

INSTRUCCIONES ESTRICTAS:
- Reportá ÚNICAMENTE hallazgos EVIDENTES y CONCRETOS visibles en las imágenes.
- NO inventes ni supongas problemas que no se vean claramente.
- Sé BREVE y PRECISO (máximo 5-6 líneas en total).
- Si no hay anomalías evidentes, indicalo en una línea.

ASPECTOS A EVALUAR en la imagen visual (si disponible):
- Aisladores: roturas, grietas, flashover (manchas de quemadura), contaminación excesiva
- Conductores: hebras rotas, daños visibles, holgura anormal
- Crucetas y herrajes: corrosión significativa, conexiones sueltas, pernos flojos
- Poste: grietas, inclinación, daño estructural, armadura expuesta
- Vegetación peligrosamente cercana a las líneas

ASPECTOS A EVALUAR en la imagen térmica:
- Puntos calientes anómalos en conexiones o aisladores
- Diferencias de temperatura significativas entre componentes similares (fases)
- Calentamiento excesivo localizado que indique alta resistencia
{temp_context}

Combiná ambas imágenes para confirmar hallazgos. Respondé en español.
"""


def _try_model(client, model_name: str, contents: list) -> str | None:
    """Attempt a single model call with retries for transient errors (503)."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
            )
            return response.text.strip()
        except Exception as e:
            err = str(e)
            is_transient = "503" in err or "UNAVAILABLE" in err or "overloaded" in err.lower()
            if is_transient and attempt < _MAX_RETRIES:
                print(f"          {model_name}: reintentando ({attempt}/{_MAX_RETRIES})...")
                time.sleep(_RETRY_DELAY)
                continue
            raise
    return None


def analyze_pole(
    api_key: str,
    pole_name: str,
    thermal_rgb: np.ndarray | None = None,
    visual_path: str | None = None,
    t_min: float | None = None,
    t_max: float | None = None,
) -> str:
    """
    Send pole images to Gemini for AI inspection.

    Tries multiple models in order. If one fails, falls back to the next.

    Args:
        api_key: Google Gemini API key
        pole_name: Name of the pole (e.g. "Poste1")
        thermal_rgb: Pseudocolor thermal image as numpy array (H, W, 3) uint8
        visual_path: Path to the visual RGB image file (optional)
        t_min: Minimum temperature detected (°C)
        t_max: Maximum temperature detected (°C)

    Returns:
        Diagnostic text string, or empty string if all models fail.
    """
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
    except Exception as e:
        print(f"        ERROR configurando Gemini: {e}")
        return ""

    contents = []
    desc_parts = []

    if visual_path:
        try:
            vis_img = PILImage.open(visual_path)
            contents.append(vis_img)
            desc_parts.append("Imagen 1: Fotografía visual (RGB) del poste")
        except Exception as e:
            print(f"        ADVERTENCIA: No se pudo cargar imagen visual: {e}")

    if thermal_rgb is not None:
        try:
            therm_img = PILImage.fromarray(thermal_rgb.astype(np.uint8))
            contents.append(therm_img)
            n = len(desc_parts) + 1
            desc_parts.append(
                f"Imagen {n}: Termografía infrarroja (pseudocolor) del mismo poste")
        except Exception as e:
            print(f"        ADVERTENCIA: No se pudo preparar imagen térmica: {e}")

    if not contents:
        return ""

    image_description = "\n".join(desc_parts)

    temp_context = ""
    if t_min is not None and t_max is not None:
        temp_context = (
            f"\nRango de temperatura detectado en la termografía: "
            f"{t_min:.1f}°C a {t_max:.1f}°C"
        )

    prompt_text = _PROMPT_TEMPLATE.format(
        pole_name=pole_name,
        image_description=image_description,
        temp_context=temp_context,
    )

    contents.insert(0, prompt_text)

    for model_name in _MODELS:
        try:
            result = _try_model(client, model_name, contents)
            if result:
                print(f"          Modelo usado: {model_name}")
                return result
        except Exception as e:
            print(f"          {model_name}: falló ({e})")
            continue

    print("        TODOS los modelos fallaron.")
    return ""
