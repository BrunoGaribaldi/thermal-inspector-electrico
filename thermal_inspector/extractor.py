"""
extractor.py — DJI Thermal SDK wrapper.
Calls dji_irp via subprocess to extract temperature arrays and pseudocolor images.
"""

import os
import re
import subprocess
import numpy as np
from pathlib import Path

# SDK binary directory (one level up from this file → sdk root → utility/bin)
_THIS_DIR = Path(__file__).parent
SDK_ROOT = _THIS_DIR.parent
BIN_DIR = str(SDK_ROOT / "utility" / "bin" / "linux" / "release_x64")
DJI_IRP = os.path.join(BIN_DIR, "dji_irp")

_DIM_RE = re.compile(r"image\s+width\s*:\s*(\d+).*?image height\s*:\s*(\d+)", re.S)


def get_cache_dir(image_path: str, base_cache: str) -> str:
    stem = Path(image_path).stem
    cache = os.path.join(base_cache, stem)
    os.makedirs(cache, exist_ok=True)
    return cache


def _run_irp(args: list) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = BIN_DIR
    result = subprocess.run(
        [DJI_IRP] + args,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"dji_irp failed (code {result.returncode}):\n{result.stderr}"
        )
    return result


def _parse_dimensions(stdout: str) -> tuple:
    m = _DIM_RE.search(stdout)
    if not m:
        raise ValueError(f"Could not parse dimensions from dji_irp output:\n{stdout}")
    return int(m.group(1)), int(m.group(2))


def extract_temperature(
    image_path: str,
    cache_dir: str,
    emissivity: float = 0.95,
    distance: float = 5.0,
    humidity: float = 70.0,
    ambient: float = 25.0,
) -> tuple:
    """
    Extract per-pixel temperature (float32, °C) from an R-JPEG.
    Returns: (temp_array H×W float32, width, height)
    Uses cached .raw file if it already exists.
    """
    raw_path = os.path.join(cache_dir, "measure_float32.raw")

    result = _run_irp([
        "-s", image_path,
        "-a", "measure",
        "-o", raw_path,
        "--measurefmt", "float32",
        "--emissivity", str(emissivity),
        "--distance", str(distance),
        "--humidity", str(humidity),
        "--ambient", str(ambient),
    ])
    w, h = _parse_dimensions(result.stdout)

    expected = w * h * 4
    actual = os.path.getsize(raw_path)
    if actual != expected:
        raise RuntimeError(
            f"Unexpected .raw size: got {actual} bytes, expected {expected} ({w}×{h}×4)"
        )

    arr = np.fromfile(raw_path, dtype=np.float32).reshape(h, w)
    return arr, w, h


def extract_pseudocolor(
    image_path: str,
    cache_dir: str,
    palette: str = "hot_iron",
) -> tuple:
    """
    Extract pseudocolor RGB image from an R-JPEG.
    Returns: (rgb_array H×W×3 uint8, width, height)
    """
    raw_path = os.path.join(cache_dir, f"process_{palette}.raw")

    result = _run_irp([
        "-s", image_path,
        "-a", "process",
        "-o", raw_path,
        "-p", palette,
    ])
    w, h = _parse_dimensions(result.stdout)

    expected = w * h * 3
    actual = os.path.getsize(raw_path)
    if actual != expected:
        raise RuntimeError(
            f"Unexpected pseudocolor .raw size: got {actual}, expected {expected}"
        )

    arr = np.fromfile(raw_path, dtype=np.uint8).reshape(h, w, 3)
    return arr, w, h
