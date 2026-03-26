"""
analyzer.py — ROI definitions and thermal analysis logic.
"""

from dataclasses import dataclass
from typing import List
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from io import BytesIO
from matplotlib import colors as mcolors


# ─────────────────────────────────────────────────────────────────────────────
#  ROI data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LineROI:
    """A two-point line region of interest."""
    label: str
    p1: tuple   # (x, y) in image pixels
    p2: tuple   # (x, y) in image pixels


@dataclass
class BoxROI:
    """A rectangular region of interest."""
    label: str
    x1: int
    y1: int
    x2: int
    y2: int


# ─────────────────────────────────────────────────────────────────────────────
#  Sampling helpers
# ─────────────────────────────────────────────────────────────────────────────

def _sample_line(temp_array: np.ndarray, p1: tuple, p2: tuple,
                 n_samples: int = 200) -> np.ndarray:
    """Return temperature values sampled along a line segment."""
    h, w = temp_array.shape
    xs = np.linspace(p1[0], p2[0], n_samples).astype(int).clip(0, w - 1)
    ys = np.linspace(p1[1], p2[1], n_samples).astype(int).clip(0, h - 1)
    return temp_array[ys, xs]


def _sample_box(temp_array: np.ndarray, roi: BoxROI) -> np.ndarray:
    """Return all temperature values inside a BoxROI."""
    h, w = temp_array.shape
    x1, y1 = max(0, roi.x1), max(0, roi.y1)
    x2, y2 = min(w, roi.x2), min(h, roi.y2)
    if x2 <= x1 or y2 <= y1:
        return np.array([])
    return temp_array[y1:y2, x1:x2].ravel()


# ─────────────────────────────────────────────────────────────────────────────
#  Classification
# ─────────────────────────────────────────────────────────────────────────────

def _classify(delta_t: float) -> tuple:
    """
    Classify thermal anomaly severity based on ΔT (max - mean).
    Returns (estado, urgencia).
    """
    if delta_t < 1.0:
        return "Normal", "—"
    elif delta_t < 3.0:
        return "Leve", "Baja"
    elif delta_t < 10.0:
        return "Moderado", "Media"
    elif delta_t < 40.0:
        return "Serio", "Alta"
    else:
        return "Crítico", "Urgente"


# ─────────────────────────────────────────────────────────────────────────────
#  Main analysis entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_full_analysis(temp_array: np.ndarray,
                      lines: List[LineROI],
                      boxes: List[BoxROI]) -> dict:
    """
    Analyse temperature data from line and box ROIs.

    Returns dict with keys:
        delta_t, estado, urgencia,
        t_max, t_min, t_mean,
        line_stats, box_stats
    """
    all_samples = []
    line_stats = []
    box_stats = []

    for roi in lines:
        samples = _sample_line(temp_array, roi.p1, roi.p2)
        if samples.size == 0:
            continue
        line_stats.append({
            "label": roi.label,
            "t_max": float(samples.max()),
            "t_min": float(samples.min()),
            "t_mean": float(samples.mean()),
            "n": int(samples.size),
            "samples": samples.tolist(),
        })
        all_samples.append(samples)

    for roi in boxes:
        samples = _sample_box(temp_array, roi)
        if samples.size == 0:
            continue
        box_stats.append({
            "label": roi.label,
            "t_max": float(samples.max()),
            "t_min": float(samples.min()),
            "t_mean": float(samples.mean()),
            "n": int(samples.size),
        })
        all_samples.append(samples)

    if all_samples:
        combined = np.concatenate(all_samples)
        t_max = float(combined.max())
        t_min = float(combined.min())
        t_mean = float(combined.mean())
    else:
        t_max = float(temp_array.max())
        t_min = float(temp_array.min())
        t_mean = float(temp_array.mean())

    delta_t = t_max - t_mean
    estado, urgencia = _classify(delta_t)

    return {
        "delta_t": delta_t,
        "estado": estado,
        "urgencia": urgencia,
        "t_max": t_max,
        "t_min": t_min,
        "t_mean": t_mean,
        "line_stats": line_stats,
        "box_stats": box_stats,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  StatisticalAnalyzer (pie chart helper, kept from previous version)
# ─────────────────────────────────────────────────────────────────────────────

class StatisticalAnalyzer:
    def __init__(self, data_frame):
        self.df = data_frame

    def generate_pie_chart(self, results_data=None):
        """Generates a clean pie chart and returns raw BytesIO image."""
        category_counts = self.df['visual_category'].value_counts()
        labels = category_counts.index.tolist()
        sizes = category_counts.values.tolist()

        if not labels:
            return None

        fig, ax = plt.subplots(figsize=(12, 12))
        explode = [0.06] * len(labels)

        patches, texts, autotexts = ax.pie(
            sizes,
            explode=explode,
            colors=plt.cm.Set3.colors,
            labels=labels,
            autopct='%1.1f%%',
            pctdistance=0.75,
            labeldistance=1.05,
            startangle=140,
            shadow=True,
        )

        plt.setp(texts, size=12, weight="normal", color="black")
        plt.setp(autotexts, size=12, weight="bold", color="black")
        for autotext in autotexts:
            autotext.set_path_effects([
                plt.patheffects.withStroke(linewidth=1.5, foreground="white")
            ])

        plt.title("Distribución de Archivos por Categoría Visual",
                  fontsize=18, fontweight='bold', pad=35)
        ax.axis('equal')
        plt.legend(patches, labels, title="Categorías",
                   loc="upper center", bbox_to_anchor=(0.5, -0.06),
                   fancybox=True, shadow=True, ncol=3,
                   fontsize=11, title_fontsize=12)
        plt.tight_layout()

        buf = BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', dpi=150)
        plt.close(fig)
        buf.seek(0)
        return buf
