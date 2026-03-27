"""
extractor.py — DJI Thermal SDK wrapper.
Calls dji_irp via subprocess to extract temperature arrays and pseudocolor images.
Also extracts EXIF/XMP metadata from DJI R-JPEG files.
"""

import os
import re
import subprocess
import numpy as np
from pathlib import Path
from PIL import Image as PILImage

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


# ── EXIF / XMP metadata extraction ──────────────────────────────────────────

def _parse_gps_coord(gps_data: tuple, ref: str) -> float | None:
    """Convert EXIF GPS tuple ((deg, min, sec), ref) to decimal degrees."""
    try:
        d = float(gps_data[0])
        m = float(gps_data[1])
        s = float(gps_data[2])
        val = d + m / 60.0 + s / 3600.0
        if ref in ("S", "W"):
            val = -val
        return val
    except Exception:
        return None


def _extract_xmp_fields(image_path: str) -> dict:
    """Extract DJI-specific fields from XMP metadata embedded in the JPEG."""
    xmp = {}
    try:
        with open(image_path, "rb") as f:
            data = f.read()
        start = data.find(b"<x:xmpmeta")
        end = data.find(b"</x:xmpmeta>")
        if start < 0 or end < 0:
            return xmp
        xmp_str = data[start:end + len(b"</x:xmpmeta>")].decode("utf-8", errors="ignore")

        patterns = {
            "drone_model": r'drone-dji:Model(?:Name)?="([^"]*)"',
            "serial_number": r'drone-dji:(?:Drone)?SerialNumber="([^"]*)"',
            "camera_serial": r'drone-dji:CameraSN="([^"]*)"',
            "gimbal_yaw": r'drone-dji:GimbalYawDegree="([^"]*)"',
            "gimbal_pitch": r'drone-dji:GimbalPitchDegree="([^"]*)"',
            "flight_yaw": r'drone-dji:FlightYawDegree="([^"]*)"',
            "relative_altitude": r'drone-dji:RelativeAltitude="([^"]*)"',
            "absolute_altitude": r'drone-dji:AbsoluteAltitude="([^"]*)"',
        }
        for key, pattern in patterns.items():
            m = re.search(pattern, xmp_str)
            if m:
                xmp[key] = m.group(1)
    except Exception:
        pass
    return xmp


def extract_image_metadata(image_path: str) -> dict:
    """Extract EXIF and XMP metadata from a DJI R-JPEG image.

    Returns a dict with available fields (missing fields are omitted):
        model, serial_number, focal_length, fnumber, width, height,
        datetime_original, datetime_modified, coordinates, drone_model,
        relative_altitude, absolute_altitude, ...
    """
    meta: dict = {}

    try:
        img = PILImage.open(image_path)
        meta["width"] = img.width
        meta["height"] = img.height

        exif = img.getexif()
        if exif:
            if 271 in exif:
                meta["make"] = str(exif[271])
            if 272 in exif:
                meta["model"] = str(exif[272])
            if 306 in exif:
                meta["datetime_modified"] = str(exif[306])

            exif_ifd = exif.get_ifd(0x8769)
            if exif_ifd:
                if 33437 in exif_ifd:
                    meta["fnumber"] = float(exif_ifd[33437])
                if 37386 in exif_ifd:
                    meta["focal_length"] = float(exif_ifd[37386])
                if 36867 in exif_ifd:
                    meta["datetime_original"] = str(exif_ifd[36867])
                if 36868 in exif_ifd:
                    meta["datetime_digitized"] = str(exif_ifd[36868])

            gps_ifd = exif.get_ifd(0x8825)
            if gps_ifd:
                lat = gps_ifd.get(2)
                lat_ref = gps_ifd.get(1, "N")
                lon = gps_ifd.get(4)
                lon_ref = gps_ifd.get(3, "E")
                if lat and lon:
                    lat_val = _parse_gps_coord(lat, lat_ref)
                    lon_val = _parse_gps_coord(lon, lon_ref)
                    if lat_val is not None and lon_val is not None:
                        meta["coordinates"] = f"{lat_val:.6f}, {lon_val:.6f}"

        img.close()
    except Exception as e:
        print(f"  ADVERTENCIA: Error leyendo EXIF: {e}")

    xmp = _extract_xmp_fields(image_path)
    if xmp.get("drone_model"):
        meta["drone_model"] = xmp["drone_model"]
    if xmp.get("serial_number"):
        meta["serial_number"] = xmp["serial_number"]
    if xmp.get("camera_serial"):
        meta["camera_serial"] = xmp["camera_serial"]
    if xmp.get("relative_altitude"):
        meta["relative_altitude"] = xmp["relative_altitude"]
    if xmp.get("absolute_altitude"):
        meta["absolute_altitude"] = xmp["absolute_altitude"]

    return meta
