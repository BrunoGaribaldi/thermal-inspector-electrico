"""
file_parser.py — Parse DJI thermal image filenames and find thermal/RGB pairs.

Naming convention:
  Thermal: DJI_YYYYMMDDHHMMSS_NNNN_T_POSTENAME.jpeg
  Visual:  DJI_YYYYMMDDHHMMSS_NNNN_V_POSTENAME.jpeg
"""

import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# DJI_20260320105538_0001_T_Poste1.jpeg  (thermal)
# DJI_20260320105538_0001_V_Poste1.jpeg  (visual)
_FILENAME_RE = re.compile(
    r"^DJI_(\d{14})_(\d{4})_(T|V)_(.+)\.jpe?g$",
    re.IGNORECASE,
)


@dataclass
class ImageInfo:
    path: str
    stem: str
    timestamp: Optional[datetime]
    sequence: str
    pole_name: str
    is_thermal: bool


def parse_filename(filepath: str) -> Optional[ImageInfo]:
    """Parse a DJI filename. Returns None if pattern does not match."""
    basename = os.path.basename(filepath)
    stem = os.path.splitext(basename)[0]
    m = _FILENAME_RE.match(basename)
    if not m:
        return None

    ts_str = m.group(1)
    sequence = m.group(2)
    img_type = m.group(3).upper()   # 'T' or 'V'
    is_thermal = img_type == "T"
    pole_name = m.group(4) or "Unknown"

    try:
        timestamp = datetime.strptime(ts_str, "%Y%m%d%H%M%S")
    except ValueError:
        timestamp = None

    return ImageInfo(
        path=filepath,
        stem=stem,
        timestamp=timestamp,
        sequence=sequence,
        pole_name=pole_name,
        is_thermal=is_thermal,
    )


def find_image_pairs(folder: str) -> list:
    """
    Scans folder for .jpeg/.jpg files, parses filenames, groups into
    thermal+RGB pairs by (sequence, pole_name).

    Returns list of dicts:
      {'sequence': str, 'pole_name': str,
       'thermal': ImageInfo, 'rgb': ImageInfo|None}
    Sorted by sequence number.
    """
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"Image folder not found: {folder}")

    extensions = {".jpeg", ".jpg"}
    thermal_map = {}
    rgb_map = {}

    for fname in sorted(os.listdir(folder)):
        if os.path.splitext(fname)[1].lower() not in extensions:
            continue
        full_path = os.path.join(folder, fname)
        info = parse_filename(full_path)
        if info is None:
            continue
        key = (info.sequence, info.pole_name)
        if info.is_thermal:
            thermal_map[key] = info
        else:
            rgb_map[key] = info

    if not thermal_map:
        raise FileNotFoundError(
            f"No DJI thermal images found in: {folder}\n"
            "Expected filenames like: DJI_YYYYMMDDHHMMSS_NNNN_T_POSTENAME.jpeg"
        )

    pairs = []
    for key, thermal in sorted(thermal_map.items(), key=lambda x: x[0][0]):
        pairs.append({
            "sequence": key[0],
            "pole_name": key[1],
            "thermal": thermal,
            "rgb": rgb_map.get(key),
        })

    return pairs
