#!/usr/bin/env python3
"""
gui.py — Professional GUI for the Thermal Inspection System.
Replaces the CLI workflow with a modern graphical interface.
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import os
import sys
import traceback
from pathlib import Path
from datetime import datetime
from PIL import Image as PILImage, ImageTk
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

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
from analyzer import run_full_analysis
from roi_tool import ROITool
from reporter import ThermalReport
from gemini_inspector import analyze_pole
from main import (_annotate_image, _load_pole_coords,
                  _extract_pole_number, _make_google_maps_url)

# ─── Theme constants ────────────────────────────────────────────────────────
HEADER_BG = "#16365C"
ACCENT = "#2471A3"
SUCCESS = "#27AE60"
WARNING = "#E67E22"
DANGER = "#C0392B"
SIDEBAR_BG = "#1B2838"
CARD_SELECTED = "#1E4A7A"
CARD_HOVER = "#253D50"
TEXT_DIM = "#8899AA"

SCRIPT_DIR = Path(__file__).parent
CACHE_DIR = SCRIPT_DIR / "cache"
OUTPUT_DIR = SCRIPT_DIR / "output"
CACHE_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


def _np_to_ctk(arr, size):
    """Convert numpy RGB array to CTkImage at given (w, h)."""
    pil = PILImage.fromarray(arr.astype(np.uint8))
    return ctk.CTkImage(light_image=pil, dark_image=pil, size=size)


def _pil_to_ctk(path, size):
    """Load an image file as CTkImage at given (w, h)."""
    try:
        pil = PILImage.open(path)
        return ctk.CTkImage(light_image=pil, dark_image=pil, size=size)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════
#  Main Application
# ═══════════════════════════════════════════════════════════════════════════

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Inspector Termográfico — QNT Drones")
        self.geometry("1320x820")
        self.minsize(1100, 700)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # ── State ───────────────────────────────────────────────────────
        self._pairs: list[dict] = []
        self._extracted: dict = {}       # idx → (temp_array, color_rgb, w, h)
        self._rois: dict = {}            # idx → (lines, boxes)
        self._analysis: dict = {}        # idx → analysis dict
        self._ai_diag: dict = {}         # idx → str
        self._entry_fields: dict = {}    # idx → dict of field values
        self._current_idx: int | None = None
        self._pdf_path: str = ""
        self._processing = False

        self._pole_coords = _load_pole_coords(str(SCRIPT_DIR / "pos_postes.csv"))
        self._gemini_key = os.environ.get("GEMINI_API_KEY", "")

        logo_path = str(SCRIPT_DIR.parent / "qntDrones.png")
        self._logo_path = logo_path if os.path.isfile(logo_path) else None

        # ── Build UI ────────────────────────────────────────────────────
        self._build_header()
        self._build_tabs()
        self._build_status_bar()

    # ═══════════════════════════════════════════════════════════════════
    #  Layout
    # ═══════════════════════════════════════════════════════════════════

    def _build_header(self):
        header = ctk.CTkFrame(self, height=56, fg_color=HEADER_BG, corner_radius=0)
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(header, text="  Inspector Termográfico",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color="white").pack(side="left", padx=10)
        ctk.CTkLabel(header, text="QNT Drones — Mantenimiento Predictivo",
                     font=ctk.CTkFont(size=12),
                     text_color="#8CB4D8").pack(side="left", padx=8)

    def _build_tabs(self):
        self._tabs = ctk.CTkTabview(self, anchor="nw",
                                     segmented_button_fg_color=HEADER_BG,
                                     segmented_button_selected_color=ACCENT)
        self._tabs.pack(fill="both", expand=True, padx=8, pady=(4, 0))

        tab1 = self._tabs.add("  Configuración  ")
        tab2 = self._tabs.add("  Imágenes  ")
        tab3 = self._tabs.add("  Informe  ")

        self._build_config_tab(tab1)
        self._build_images_tab(tab2)
        self._build_report_tab(tab3)

    def _build_status_bar(self):
        bar = ctk.CTkFrame(self, height=28, fg_color="#111720", corner_radius=0)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self._status_lbl = ctk.CTkLabel(bar, text="Listo",
                                         font=ctk.CTkFont(size=11),
                                         text_color=TEXT_DIM)
        self._status_lbl.pack(side="left", padx=12)

    def _status(self, msg: str, color: str = TEXT_DIM):
        self._status_lbl.configure(text=msg, text_color=color)
        self.update_idletasks()

    # ═══════════════════════════════════════════════════════════════════
    #  Tab 1 — Configuración
    # ═══════════════════════════════════════════════════════════════════

    def _build_config_tab(self, parent):
        wrapper = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        wrapper.pack(fill="both", expand=True, padx=10, pady=5)

        # ── Image folder ────────────────────────────────────────────
        self._section(wrapper, "Carpeta de Imágenes")

        row_folder = ctk.CTkFrame(wrapper, fg_color="transparent")
        row_folder.pack(fill="x", pady=4)

        self._var_folder = ctk.StringVar()
        ctk.CTkEntry(row_folder, textvariable=self._var_folder,
                     placeholder_text="Ruta a la carpeta con imágenes DJI...",
                     height=36, font=ctk.CTkFont(size=13)
                     ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(row_folder, text="Examinar…", width=120, height=36,
                      command=self._browse_folder).pack(side="left")

        self._lbl_images_found = ctk.CTkLabel(wrapper, text="",
                                               font=ctk.CTkFont(size=12),
                                               text_color=TEXT_DIM)
        self._lbl_images_found.pack(anchor="w", pady=(2, 8))

        # ── Report metadata ────────────────────────────────────────
        self._section(wrapper, "Datos del Informe")

        grid_meta = ctk.CTkFrame(wrapper, fg_color="transparent")
        grid_meta.pack(fill="x", pady=4)
        grid_meta.columnconfigure(1, weight=1)
        grid_meta.columnconfigure(3, weight=1)

        self._var_empresa = self._form_field(grid_meta, "Empresa", 0, 0)
        self._var_inspector = self._form_field(grid_meta, "Inspector", 0, 2)
        self._var_ubicacion = self._form_field(grid_meta, "Ubicación", 1, 0)
        self._var_informe = self._form_field(grid_meta, "N° Informe", 1, 2,
                                              default=datetime.now().strftime("INF-%Y%m%d-%H%M"))

        # ── Measurement params ─────────────────────────────────────
        self._section(wrapper, "Parámetros de Medición")

        grid_meas = ctk.CTkFrame(wrapper, fg_color="transparent")
        grid_meas.pack(fill="x", pady=4)
        grid_meas.columnconfigure(1, weight=1)
        grid_meas.columnconfigure(3, weight=1)

        self._var_emissivity = self._form_field(grid_meas, "Emisividad", 0, 0, default="0.95")
        self._var_distance = self._form_field(grid_meas, "Distancia (m)", 0, 2, default="5.0")
        self._var_humidity = self._form_field(grid_meas, "Humedad (%)", 1, 0, default="70.0")
        self._var_ambient = self._form_field(grid_meas, "Temp. Ambiente (°C)", 1, 2, default="25.0")

        # ── Gemini key ─────────────────────────────────────────────
        self._section(wrapper, "Diagnóstico IA (Gemini)")

        row_key = ctk.CTkFrame(wrapper, fg_color="transparent")
        row_key.pack(fill="x", pady=4)

        self._var_gemini = ctk.StringVar(value=self._gemini_key)
        ctk.CTkEntry(row_key, textvariable=self._var_gemini,
                     placeholder_text="API Key de Google Gemini…",
                     show="•", height=36, font=ctk.CTkFont(size=13)
                     ).pack(side="left", fill="x", expand=True, padx=(0, 8))

        gemini_status = "Configurada" if self._gemini_key else "No configurada"
        gemini_color = SUCCESS if self._gemini_key else WARNING
        self._lbl_gemini = ctk.CTkLabel(row_key, text=gemini_status,
                                         font=ctk.CTkFont(size=12),
                                         text_color=gemini_color)
        self._lbl_gemini.pack(side="left", padx=8)

        # ── Scan button ───────────────────────────────────────────
        ctk.CTkButton(wrapper, text="Buscar Imágenes", height=42,
                      font=ctk.CTkFont(size=14, weight="bold"),
                      fg_color=ACCENT, hover_color=CARD_SELECTED,
                      command=self._scan_images).pack(pady=20)

    # ═══════════════════════════════════════════════════════════════════
    #  Tab 2 — Imágenes
    # ═══════════════════════════════════════════════════════════════════

    def _build_images_tab(self, parent):
        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.pack(fill="both", expand=True)

        # ── Left sidebar: image list ──────────────────────────────
        left = ctk.CTkFrame(container, width=240, fg_color=SIDEBAR_BG, corner_radius=8)
        left.pack(side="left", fill="y", padx=(0, 6), pady=2)
        left.pack_propagate(False)

        ctk.CTkLabel(left, text="Imágenes", font=ctk.CTkFont(size=14, weight="bold"),
                     text_color="white").pack(pady=(10, 4), padx=10, anchor="w")

        self._img_list_frame = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self._img_list_frame.pack(fill="both", expand=True, padx=4, pady=4)

        self._img_cards: list[ctk.CTkFrame] = []

        btn_frame = ctk.CTkFrame(left, fg_color="transparent")
        btn_frame.pack(fill="x", padx=8, pady=8)
        ctk.CTkButton(btn_frame, text="Procesar Todos", height=36,
                      font=ctk.CTkFont(size=12, weight="bold"),
                      fg_color=SUCCESS, hover_color="#229954",
                      command=self._process_all).pack(fill="x")

        # ── Right: detail panel ──────────────────────────────────
        self._detail_frame = ctk.CTkScrollableFrame(container, fg_color="transparent")
        self._detail_frame.pack(side="left", fill="both", expand=True, pady=2)

        self._detail_placeholder = ctk.CTkLabel(
            self._detail_frame,
            text="Seleccioná una imagen de la lista\no hacé clic en \"Procesar Todos\"",
            font=ctk.CTkFont(size=16), text_color=TEXT_DIM)
        self._detail_placeholder.pack(expand=True, pady=100)

        self._detail_content = None

    # ═══════════════════════════════════════════════════════════════════
    #  Tab 3 — Informe
    # ═══════════════════════════════════════════════════════════════════

    def _build_report_tab(self, parent):
        wrapper = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        wrapper.pack(fill="both", expand=True, padx=10, pady=5)

        self._section(wrapper, "Resumen de Entradas")

        self._report_table_frame = ctk.CTkFrame(wrapper, fg_color="transparent")
        self._report_table_frame.pack(fill="x", pady=4)

        self._lbl_no_entries = ctk.CTkLabel(
            self._report_table_frame, text="No hay imágenes procesadas aún.",
            font=ctk.CTkFont(size=13), text_color=TEXT_DIM)
        self._lbl_no_entries.pack(pady=20)

        self._section(wrapper, "Generar PDF")

        row_out = ctk.CTkFrame(wrapper, fg_color="transparent")
        row_out.pack(fill="x", pady=4)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._var_output = ctk.StringVar(
            value=str(OUTPUT_DIR / f"Informe_Termografico_{ts}.pdf"))
        ctk.CTkEntry(row_out, textvariable=self._var_output,
                     height=36, font=ctk.CTkFont(size=13)
                     ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(row_out, text="Examinar…", width=120, height=36,
                      command=self._browse_output).pack(side="left")

        self._progress = ctk.CTkProgressBar(wrapper, height=14)
        self._progress.pack(fill="x", pady=12)
        self._progress.set(0)

        btn_row = ctk.CTkFrame(wrapper, fg_color="transparent")
        btn_row.pack(pady=10)

        self._btn_generate = ctk.CTkButton(
            btn_row, text="  Generar PDF  ", height=46,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=ACCENT, hover_color=CARD_SELECTED,
            command=self._generate_pdf)
        self._btn_generate.pack(side="left", padx=8)

        self._btn_open_pdf = ctk.CTkButton(
            btn_row, text="  Abrir PDF  ", height=46,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#555555", hover_color="#666666", state="disabled",
            command=self._open_pdf)
        self._btn_open_pdf.pack(side="left", padx=8)

    # ═══════════════════════════════════════════════════════════════════
    #  Image list management
    # ═══════════════════════════════════════════════════════════════════

    def _rebuild_image_list(self):
        for card in self._img_cards:
            card.destroy()
        self._img_cards.clear()

        for idx, pair in enumerate(self._pairs):
            card = self._make_image_card(idx, pair)
            card.pack(fill="x", pady=2, padx=2)
            self._img_cards.append(card)

    def _make_image_card(self, idx, pair):
        done = idx in self._analysis
        has_roi = idx in self._rois
        extracted = idx in self._extracted

        if done:
            indicator = "●"
            ind_color = SUCCESS
        elif extracted:
            indicator = "◐"
            ind_color = WARNING
        else:
            indicator = "○"
            ind_color = TEXT_DIM

        card = ctk.CTkFrame(self._img_list_frame, fg_color="#1E2D3D",
                            corner_radius=6, height=44, cursor="hand2")
        card.pack_propagate(False)

        ind = ctk.CTkLabel(card, text=indicator, font=ctk.CTkFont(size=14),
                           text_color=ind_color, width=20)
        ind.pack(side="left", padx=(8, 4))

        name = ctk.CTkLabel(card, text=pair["pole_name"],
                            font=ctk.CTkFont(size=12, weight="bold"),
                            text_color="white")
        name.pack(side="left", padx=4)

        rgb_txt = "V" if pair["rgb"] else ""
        if rgb_txt:
            ctk.CTkLabel(card, text=rgb_txt, font=ctk.CTkFont(size=10),
                         text_color=SUCCESS, width=16).pack(side="right", padx=6)

        for widget in [card, ind, name]:
            widget.bind("<Button-1>", lambda e, i=idx: self._select_image(i))

        return card

    def _highlight_card(self, idx):
        for i, card in enumerate(self._img_cards):
            color = CARD_SELECTED if i == idx else "#1E2D3D"
            card.configure(fg_color=color)

    # ═══════════════════════════════════════════════════════════════════
    #  Detail panel for selected image
    # ═══════════════════════════════════════════════════════════════════

    def _select_image(self, idx):
        self._save_current_fields()
        self._current_idx = idx
        self._highlight_card(idx)
        self._show_detail(idx)

    def _show_detail(self, idx):
        if self._detail_content:
            self._detail_content.destroy()
        self._detail_placeholder.pack_forget()

        pair = self._pairs[idx]
        pole_name = pair["pole_name"]

        frame = ctk.CTkFrame(self._detail_frame, fg_color="transparent")
        frame.pack(fill="both", expand=True)
        self._detail_content = frame

        # ── Title ───────────────────────────────────────────────────
        ctk.CTkLabel(frame, text=pole_name,
                     font=ctk.CTkFont(size=18, weight="bold")
                     ).pack(anchor="w", pady=(4, 8))

        # ── Image previews ──────────────────────────────────────────
        img_row = ctk.CTkFrame(frame, fg_color="transparent")
        img_row.pack(fill="x", pady=4)

        prev_size = (380, 280)

        # Thermal preview
        therm_frame = ctk.CTkFrame(img_row, fg_color="#0D1B2A", corner_radius=8)
        therm_frame.pack(side="left", padx=(0, 6), fill="x", expand=True)
        ctk.CTkLabel(therm_frame, text="TERMOGRAMA",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=ACCENT).pack(pady=(6, 2))

        if idx in self._extracted:
            _, color_rgb, _, _ = self._extracted[idx]
            rgb_display = color_rgb
            if idx in self._rois:
                lines, boxes = self._rois[idx]
                if lines or boxes:
                    rgb_display = _annotate_image(color_rgb, lines, boxes)
            therm_img = _np_to_ctk(rgb_display, prev_size)
            ctk.CTkLabel(therm_frame, text="", image=therm_img).pack(padx=6, pady=(0, 6))
        else:
            ctk.CTkLabel(therm_frame, text="Sin extraer",
                         text_color=TEXT_DIM, height=prev_size[1]
                         ).pack(padx=6, pady=(0, 6))

        # Visual preview
        vis_frame = ctk.CTkFrame(img_row, fg_color="#0D1B2A", corner_radius=8)
        vis_frame.pack(side="left", padx=(6, 0), fill="x", expand=True)
        ctk.CTkLabel(vis_frame, text="IMAGEN VISUAL",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=ACCENT).pack(pady=(6, 2))

        if pair["rgb"]:
            vis_img = _pil_to_ctk(pair["rgb"].path, prev_size)
            if vis_img:
                ctk.CTkLabel(vis_frame, text="", image=vis_img).pack(padx=6, pady=(0, 6))
            else:
                ctk.CTkLabel(vis_frame, text="Error cargando imagen",
                             text_color=DANGER, height=prev_size[1]
                             ).pack(padx=6, pady=(0, 6))
        else:
            ctk.CTkLabel(vis_frame, text="No disponible",
                         text_color=TEXT_DIM, height=prev_size[1]
                         ).pack(padx=6, pady=(0, 6))

        # ── Analysis summary ────────────────────────────────────────
        if idx in self._analysis:
            a = self._analysis[idx]
            summary_frame = ctk.CTkFrame(frame, fg_color="#0D1B2A", corner_radius=8)
            summary_frame.pack(fill="x", pady=6)

            cols = ctk.CTkFrame(summary_frame, fg_color="transparent")
            cols.pack(fill="x", padx=12, pady=8)

            self._stat_chip(cols, "T. Máxima", f"{a['t_max']:.1f} °C")
            self._stat_chip(cols, "T. Mínima", f"{a['t_min']:.1f} °C")
            self._stat_chip(cols, "T. Media", f"{a['t_mean']:.1f} °C")
            self._stat_chip(cols, "ΔT", f"{a['delta_t']:.2f} °C")
            estado_color = SUCCESS if a['estado'] == 'Normal' else WARNING if a['estado'] == 'Leve' else DANGER
            self._stat_chip(cols, "Estado", a['estado'], color=estado_color)

        # ── GPS info ────────────────────────────────────────────────
        pole_num = _extract_pole_number(pole_name)
        if pole_num and pole_num in self._pole_coords:
            coord = self._pole_coords[pole_num]
            gps_frame = ctk.CTkFrame(frame, fg_color="#0A2E1A", corner_radius=8)
            gps_frame.pack(fill="x", pady=4)
            ctk.CTkLabel(gps_frame, text=f"  GPS: {coord}",
                         font=ctk.CTkFont(size=12),
                         text_color=SUCCESS).pack(side="left", padx=8, pady=6)

        # ── Form fields ────────────────────────────────────────────
        self._section(frame, "Datos del Termograma")

        grid_f = ctk.CTkFrame(frame, fg_color="transparent")
        grid_f.pack(fill="x", pady=4)
        grid_f.columnconfigure(1, weight=1)
        grid_f.columnconfigure(3, weight=1)

        saved = self._entry_fields.get(idx, {})
        ubicacion_default = self._var_ubicacion.get() or ""

        self._detail_vars = {}
        self._detail_vars["ubicacion"] = self._form_field(
            grid_f, "Ubicación", 0, 0, default=saved.get("ubicacion", ubicacion_default))
        self._detail_vars["equipo"] = self._form_field(
            grid_f, "Equipo", 0, 2, default=saved.get("equipo", pole_name))
        self._detail_vars["componente"] = self._form_field(
            grid_f, "Componente", 1, 0, default=saved.get("componente", "Seccionador"))
        self._detail_vars["prioridad"] = self._form_field(
            grid_f, "Prioridad", 1, 2, default=saved.get("prioridad", "N/A"))
        self._detail_vars["precinto"] = self._form_field(
            grid_f, "Precinto", 2, 0, default=saved.get("precinto", "N/A"))
        self._detail_vars["diagnostico_texto"] = self._form_field(
            grid_f, "Diagnóstico", 2, 2, default=saved.get(
                "diagnostico_texto",
                "No se observan puntos calientes ni perfil térmico anormal."))

        # ── AI diagnosis display ────────────────────────────────────
        if idx in self._ai_diag and self._ai_diag[idx]:
            self._section(frame, "Diagnóstico IA")
            ia_box = ctk.CTkFrame(frame, fg_color="#2C2200", corner_radius=8)
            ia_box.pack(fill="x", pady=4)
            ctk.CTkLabel(ia_box, text=self._ai_diag[idx], wraplength=700,
                         font=ctk.CTkFont(size=12), text_color="#F0D080",
                         justify="left").pack(padx=12, pady=10, anchor="w")

        # ── Action buttons ──────────────────────────────────────────
        btn_row = ctk.CTkFrame(frame, fg_color="transparent")
        btn_row.pack(fill="x", pady=12)

        extracted = idx in self._extracted
        has_roi = idx in self._rois

        if not extracted:
            ctk.CTkButton(btn_row, text="Extraer Datos", height=38,
                          fg_color=ACCENT, hover_color=CARD_SELECTED,
                          command=lambda: self._extract_image(idx)
                          ).pack(side="left", padx=4)
        else:
            ctk.CTkButton(btn_row, text="Seleccionar ROIs", height=38,
                          fg_color=WARNING, hover_color="#D68910",
                          command=lambda: self._open_roi(idx)
                          ).pack(side="left", padx=4)

        if extracted:
            ctk.CTkButton(btn_row, text="Diagnóstico IA", height=38,
                          fg_color="#6C3483", hover_color="#5B2C6F",
                          command=lambda: self._run_ai(idx)
                          ).pack(side="left", padx=4)

        if idx in self._analysis:
            ctk.CTkLabel(btn_row, text="  ✓ Analizado",
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=SUCCESS).pack(side="right", padx=8)

    # ═══════════════════════════════════════════════════════════════════
    #  Processing logic
    # ═══════════════════════════════════════════════════════════════════

    def _scan_images(self):
        folder = self._var_folder.get().strip()
        if not folder:
            messagebox.showwarning("Carpeta requerida", "Seleccioná una carpeta de imágenes.")
            return

        self._status("Buscando imágenes…")
        try:
            self._pairs = find_image_pairs(folder)
        except FileNotFoundError as e:
            messagebox.showerror("Error", str(e))
            self._status("Error buscando imágenes", DANGER)
            return

        self._extracted.clear()
        self._rois.clear()
        self._analysis.clear()
        self._ai_diag.clear()
        self._entry_fields.clear()
        self._current_idx = None

        self._lbl_images_found.configure(
            text=f"✓ {len(self._pairs)} par(es) de imágenes encontrados",
            text_color=SUCCESS)
        self._rebuild_image_list()
        self._status(f"{len(self._pairs)} imágenes encontradas", SUCCESS)

    def _extract_image(self, idx):
        pair = self._pairs[idx]
        self._status(f"Extrayendo datos de {pair['pole_name']}…")

        def work():
            thermal_path = pair["thermal"].path
            cache_dir = get_cache_dir(thermal_path, str(CACHE_DIR))
            temp_array, w, h = extract_temperature(
                thermal_path, cache_dir,
                emissivity=float(self._var_emissivity.get() or 0.95),
                distance=float(self._var_distance.get() or 5.0),
                humidity=float(self._var_humidity.get() or 70.0),
                ambient=float(self._var_ambient.get() or 25.0))
            color_rgb, _, _ = extract_pseudocolor(thermal_path, cache_dir, palette="hot_iron")
            return temp_array, color_rgb, w, h

        def done(result):
            self._extracted[idx] = result
            self._rebuild_image_list()
            self._show_detail(idx)
            self._status(f"{pair['pole_name']}: datos extraídos", SUCCESS)

        self._threaded(work, done)

    def _open_roi(self, idx):
        if idx not in self._extracted:
            return
        temp_array, color_rgb, _, _ = self._extracted[idx]
        pole_name = self._pairs[idx]["pole_name"]

        self._status(f"Seleccionando ROIs para {pole_name}…")
        try:
            tool = ROITool(temp_array, color_rgb, title=pole_name)
            lines, boxes = tool.run()
        except RuntimeError as e:
            messagebox.showerror("Error ROI", str(e))
            lines, boxes = [], []

        self._rois[idx] = (lines, boxes)

        analysis = run_full_analysis(temp_array, lines, boxes)
        self._analysis[idx] = analysis

        self._rebuild_image_list()
        self._show_detail(idx)
        self._status(f"{pole_name}: {len(lines)} línea(s), {len(boxes)} caja(s) — "
                     f"ΔT={analysis['delta_t']:.2f}°C → {analysis['estado']}", SUCCESS)

    def _run_ai(self, idx):
        key = self._var_gemini.get().strip()
        if not key:
            messagebox.showwarning("API Key", "Ingresá la API Key de Gemini en Configuración.")
            return

        pair = self._pairs[idx]
        pole_name = pair["pole_name"]
        self._status(f"Enviando {pole_name} a Gemini…", ACCENT)

        rgb_path = pair["rgb"].path if pair["rgb"] else None
        _, color_rgb, _, _ = self._extracted.get(idx, (None, None, None, None))
        temp_array = self._extracted[idx][0] if idx in self._extracted else None

        t_min = float(temp_array.min()) if temp_array is not None else None
        t_max = float(temp_array.max()) if temp_array is not None else None

        def work():
            return analyze_pole(
                api_key=key, pole_name=pole_name,
                thermal_rgb=color_rgb, visual_path=rgb_path,
                t_min=t_min, t_max=t_max)

        def done(result):
            self._ai_diag[idx] = result
            if self._current_idx == idx:
                self._show_detail(idx)
            if result:
                self._status(f"{pole_name}: diagnóstico IA recibido", SUCCESS)
            else:
                self._status(f"{pole_name}: sin respuesta de IA", WARNING)

        self._threaded(work, done)

    def _process_all(self):
        if not self._pairs:
            messagebox.showinfo("Sin imágenes", "Buscá imágenes primero en Configuración.")
            return
        if self._processing:
            return

        self._processing = True

        def work():
            total = len(self._pairs)
            key = self._var_gemini.get().strip()

            for idx, pair in enumerate(self._pairs):
                pole_name = pair["pole_name"]

                # Extract
                if idx not in self._extracted:
                    self.after(0, lambda p=pole_name: self._status(
                        f"[{idx+1}/{total}] Extrayendo {p}…"))
                    thermal_path = pair["thermal"].path
                    cache_dir = get_cache_dir(thermal_path, str(CACHE_DIR))
                    temp_array, w, h = extract_temperature(
                        thermal_path, cache_dir,
                        emissivity=float(self._var_emissivity.get() or 0.95),
                        distance=float(self._var_distance.get() or 5.0),
                        humidity=float(self._var_humidity.get() or 70.0),
                        ambient=float(self._var_ambient.get() or 25.0))
                    color_rgb, _, _ = extract_pseudocolor(
                        thermal_path, cache_dir, palette="hot_iron")
                    self._extracted[idx] = (temp_array, color_rgb, w, h)
                    self.after(0, self._rebuild_image_list)

                # ROI (must run on main thread)
                if idx not in self._rois:
                    self.after(0, lambda p=pole_name: self._status(
                        f"[{idx+1}/{total}] ROIs para {p}…"))
                    event = threading.Event()

                    def roi_on_main(i=idx):
                        self._select_image(i)
                        self._open_roi(i)
                        event.set()

                    self.after(0, roi_on_main)
                    event.wait()

                # AI diagnosis
                if idx not in self._ai_diag and key:
                    self.after(0, lambda p=pole_name: self._status(
                        f"[{idx+1}/{total}] IA para {p}…", ACCENT))
                    rgb_path = pair["rgb"].path if pair["rgb"] else None
                    temp_array, color_rgb, _, _ = self._extracted[idx]
                    result = analyze_pole(
                        api_key=key, pole_name=pole_name,
                        thermal_rgb=color_rgb, visual_path=rgb_path,
                        t_min=float(temp_array.min()),
                        t_max=float(temp_array.max()))
                    self._ai_diag[idx] = result

                self.after(0, self._rebuild_image_list)

        def done(_):
            self._processing = False
            self._rebuild_image_list()
            self._refresh_report_table()
            self._status(f"✓ {len(self._pairs)} imágenes procesadas", SUCCESS)
            self._tabs.set("  Informe  ")

        threading.Thread(target=lambda: self._threaded_raw(work, done), daemon=True).start()

    # ═══════════════════════════════════════════════════════════════════
    #  Report generation
    # ═══════════════════════════════════════════════════════════════════

    def _refresh_report_table(self):
        for w in self._report_table_frame.winfo_children():
            w.destroy()

        processed = [i for i in range(len(self._pairs)) if i in self._analysis]
        if not processed:
            ctk.CTkLabel(self._report_table_frame,
                         text="No hay imágenes procesadas aún.",
                         font=ctk.CTkFont(size=13), text_color=TEXT_DIM).pack(pady=20)
            return

        header_frame = ctk.CTkFrame(self._report_table_frame, fg_color=HEADER_BG,
                                     corner_radius=6)
        header_frame.pack(fill="x", pady=(0, 2))

        cols = ["#", "Poste", "Estado", "ΔT", "ROIs", "IA", "GPS"]
        widths = [40, 140, 100, 80, 80, 50, 50]
        for c, w in zip(cols, widths):
            ctk.CTkLabel(header_frame, text=c, width=w,
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color="white").pack(side="left", padx=4, pady=6)

        for idx in processed:
            pair = self._pairs[idx]
            a = self._analysis[idx]
            lines, boxes = self._rois.get(idx, ([], []))

            has_ia = "✓" if self._ai_diag.get(idx) else "—"
            pole_num = _extract_pole_number(pair["pole_name"])
            has_gps = "✓" if pole_num and pole_num in self._pole_coords else "—"

            row = ctk.CTkFrame(self._report_table_frame, fg_color="#1E2D3D",
                               corner_radius=4)
            row.pack(fill="x", pady=1)

            vals = [
                str(idx + 1), pair["pole_name"], a["estado"],
                f"{a['delta_t']:.2f}°C", f"{len(lines)}L {len(boxes)}B",
                has_ia, has_gps,
            ]
            colors_row = [
                "white", "white",
                SUCCESS if a["estado"] == "Normal" else WARNING if a["estado"] == "Leve" else DANGER,
                "white", TEXT_DIM, SUCCESS if has_ia == "✓" else TEXT_DIM,
                SUCCESS if has_gps == "✓" else TEXT_DIM,
            ]

            for val, w, clr in zip(vals, widths, colors_row):
                ctk.CTkLabel(row, text=val, width=w,
                             font=ctk.CTkFont(size=11),
                             text_color=clr).pack(side="left", padx=4, pady=5)

    def _generate_pdf(self):
        processed = [i for i in range(len(self._pairs)) if i in self._analysis]
        if not processed:
            messagebox.showwarning("Sin datos", "No hay imágenes procesadas para generar el informe.")
            return

        self._save_current_fields()

        pdf_path = self._var_output.get().strip()
        if not pdf_path:
            messagebox.showwarning("Ruta requerida", "Indicá la ruta de salida del PDF.")
            return

        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

        meta = {
            "empresa": self._var_empresa.get(),
            "inspector": self._var_inspector.get(),
            "ubicacion_general": self._var_ubicacion.get(),
            "id_informe": self._var_informe.get(),
            "fecha": datetime.now().strftime("%d/%m/%Y"),
        }

        self._btn_generate.configure(state="disabled")
        self._status("Generando PDF…")

        def work():
            report = ThermalReport(pdf_path, meta, logo_path=self._logo_path)
            total = len(processed)

            for i, idx in enumerate(processed):
                pair = self._pairs[idx]
                a = self._analysis[idx]
                lines, boxes = self._rois.get(idx, ([], []))
                temp_array, color_rgb, _, _ = self._extracted[idx]

                color_annotated = _annotate_image(color_rgb, lines, boxes) if (
                    lines or boxes) else color_rgb

                fields = self._entry_fields.get(idx, {})
                pole_name = pair["pole_name"]
                pole_num = _extract_pole_number(pole_name)
                gps_coord = ""
                gps_url = ""
                if pole_num and pole_num in self._pole_coords:
                    gps_coord = self._pole_coords[pole_num]
                    gps_url = _make_google_maps_url(gps_coord)

                entry = {
                    **fields,
                    **a,
                    "pole_name": pole_name,
                    "thermal_path": pair["thermal"].path,
                    "rgb_path": pair["rgb"].path if pair["rgb"] else None,
                    "color_rgb": color_annotated,
                    "temp_array": temp_array,
                    "timestamp": pair["thermal"].timestamp,
                    "gps_coord": gps_coord,
                    "gps_url": gps_url,
                    "diagnostico_ia": self._ai_diag.get(idx, ""),
                }

                entry.setdefault("ubicacion", self._var_ubicacion.get())
                entry.setdefault("equipo", pole_name)
                entry.setdefault("componente", "Seccionador")
                entry.setdefault("prioridad", "N/A")
                entry.setdefault("precinto", "N/A")
                entry.setdefault("diagnostico_texto",
                                 "No se observan puntos calientes ni perfil térmico anormal.")

                report.add_entry(entry)
                self.after(0, lambda p=(i+1)/total: self._progress.set(p))

            report.build()
            return pdf_path

        def done(result):
            self._btn_generate.configure(state="normal")
            self._pdf_path = result
            self._progress.set(1.0)
            self._btn_open_pdf.configure(state="normal", fg_color=SUCCESS,
                                          hover_color="#229954")
            self._status(f"✓ PDF generado: {result}", SUCCESS)

        self._threaded(work, done)

    def _open_pdf(self):
        if self._pdf_path and os.path.isfile(self._pdf_path):
            import subprocess
            subprocess.Popen(["xdg-open", self._pdf_path])

    # ═══════════════════════════════════════════════════════════════════
    #  Utility helpers
    # ═══════════════════════════════════════════════════════════════════

    def _save_current_fields(self):
        if self._current_idx is not None and hasattr(self, '_detail_vars'):
            fields = {}
            for key, var in self._detail_vars.items():
                fields[key] = var.get()
            self._entry_fields[self._current_idx] = fields

    def _browse_folder(self):
        path = filedialog.askdirectory(title="Seleccionar carpeta de imágenes")
        if path:
            self._var_folder.set(path)

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="Guardar informe PDF",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")])
        if path:
            self._var_output.set(path)

    def _section(self, parent, text):
        lbl = ctk.CTkLabel(parent, text=text,
                           font=ctk.CTkFont(size=13, weight="bold"),
                           text_color=ACCENT)
        lbl.pack(anchor="w", pady=(14, 2))
        sep = ctk.CTkFrame(parent, height=2, fg_color=ACCENT)
        sep.pack(fill="x", pady=(0, 6))

    def _form_field(self, parent, label, row, col, default=""):
        ctk.CTkLabel(parent, text=label, font=ctk.CTkFont(size=12),
                     text_color="#AABBCC").grid(row=row, column=col,
                                                sticky="w", padx=(0, 6), pady=4)
        var = ctk.StringVar(value=default)
        ctk.CTkEntry(parent, textvariable=var, height=34,
                     font=ctk.CTkFont(size=12)).grid(
            row=row, column=col + 1, sticky="ew", padx=(0, 16), pady=4)
        return var

    def _stat_chip(self, parent, label, value, color="white"):
        chip = ctk.CTkFrame(parent, fg_color="#162940", corner_radius=6)
        chip.pack(side="left", padx=4, pady=4)
        ctk.CTkLabel(chip, text=label, font=ctk.CTkFont(size=10),
                     text_color=TEXT_DIM).pack(padx=8, pady=(4, 0))
        ctk.CTkLabel(chip, text=value, font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=color).pack(padx=8, pady=(0, 4))

    def _threaded(self, func, on_done=None):
        def wrapper():
            try:
                result = func()
                if on_done:
                    self.after(0, lambda: on_done(result))
            except Exception as e:
                traceback.print_exc()
                self.after(0, lambda: self._status(f"Error: {e}", DANGER))
        threading.Thread(target=wrapper, daemon=True).start()

    def _threaded_raw(self, func, on_done):
        try:
            func()
            if on_done:
                self.after(0, lambda: on_done(None))
        except Exception as e:
            traceback.print_exc()
            self.after(0, lambda: self._status(f"Error: {e}", DANGER))


# ═══════════════════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════════════════

def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
