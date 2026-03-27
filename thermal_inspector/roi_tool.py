"""
roi_tool.py — Interactive tkinter-based ROI selector for thermal images.

Controls:
  Left click        → place anchor / confirm point
  Mouse move        → rubber-band preview
  'n' or Enter      → start a new line (after current is committed)
  'b'               → switch to box mode
  'l'               → switch to line mode
  Escape            → cancel current in-progress ROI
  'q' or close      → finish and return all ROIs
"""

import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageDraw, ImageTk
import numpy as np
from enum import Enum, auto
from analyzer import LineROI, BoxROI


class _Mode(Enum):
    LINE = auto()
    BOX = auto()


class ROITool:
    # Colors (RGB tuples for PIL, hex strings for tkinter canvas)
    _LINE_COLOR_PIL = (255, 255, 255)
    _LINE_COLOR_TK = "white"
    _BOX_COLOR_PIL = (255, 220, 0)
    _BOX_COLOR_TK = "#ffdc00"
    _PREVIEW_COLOR = "#aaaaaa"
    _DOT_RADIUS = 4

    # Line colors for up to 8 lines (cycling)
    _LINE_PALETTE_TK = [
        "white", "#3498db", "#2ecc71", "#e74c3c",
        "#f39c12", "#9b59b6", "#1abc9c", "#e67e22",
    ]
    _LINE_PALETTE_PIL = [
        (255, 255, 255), (52, 152, 219), (46, 204, 113), (231, 76, 60),
        (243, 156, 18), (155, 89, 182), (26, 188, 156), (230, 126, 34),
    ]

    def __init__(
        self,
        temp_array: np.ndarray,
        pseudocolor_rgb: np.ndarray,
        title: str = "Selección de ROI",
        max_w: int = 900,
        max_h: int = 680,
    ):
        self._temp = temp_array
        self._rgb = pseudocolor_rgb
        self._title = title
        self._img_h, self._img_w = temp_array.shape

        # Scale factor to fit display
        self._scale = min(max_w / self._img_w, max_h / self._img_h, 1.0)
        self._disp_w = int(self._img_w * self._scale)
        self._disp_h = int(self._img_h * self._scale)

        # ROI storage
        self._lines: list = []   # list of LineROI
        self._boxes: list = []   # list of BoxROI
        self._line_counter = 0
        self._box_counter = 0

        # State
        self._mode = _Mode.LINE
        self._anchor = None      # (canvas_x, canvas_y) of first click
        self._preview_item = None

        self._result_ready = False

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def run(self) -> tuple:
        """Open window, block until user presses 'q'. Returns (lines, boxes)."""
        existing_root = tk._default_root
        try:
            if existing_root:
                self._root = tk.Toplevel(existing_root)
                self._is_toplevel = True
            else:
                self._root = tk.Tk()
                self._is_toplevel = False
        except tk.TclError as e:
            raise RuntimeError(f"Cannot open display: {e}")

        self._root.title(f"ROI — {self._title}")
        self._root.resizable(False, False)

        self._setup_ui()
        self._root.focus_set()

        if self._is_toplevel:
            self._root.grab_set()
            self._root.wait_window()
        else:
            self._root.mainloop()
            try:
                self._root.destroy()
            except Exception:
                pass

        return self._lines, self._boxes

    # ------------------------------------------------------------------ #
    #  UI setup                                                            #
    # ------------------------------------------------------------------ #

    def _setup_ui(self):
        # ── Left: canvas ──────────────────────────────────────────────
        self._canvas = tk.Canvas(
            self._root,
            width=self._disp_w,
            height=self._disp_h,
            cursor="crosshair",
            bg="black",
        )
        self._canvas.grid(row=0, column=0, rowspan=20)

        # Draw background thermal image (kept as instance attr to avoid GC)
        pil_img = Image.fromarray(self._rgb).resize(
            (self._disp_w, self._disp_h), Image.NEAREST
        )
        self._tk_photo = ImageTk.PhotoImage(pil_img)
        self._canvas.create_image(0, 0, anchor="nw", image=self._tk_photo, tags="bg")

        # ── Right: info panel ─────────────────────────────────────────
        panel = tk.Frame(self._root, bg="#1e1e1e", width=220, padx=10, pady=10)
        panel.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        def lbl(text, bold=False, fg="#dddddd", pady=2):
            font = ("Helvetica", 9, "bold" if bold else "normal")
            tk.Label(panel, text=text, bg="#1e1e1e", fg=fg,
                     font=font, anchor="w", justify="left",
                     wraplength=200).pack(fill="x", pady=pady)

        lbl("INSPECTOR TERMOGRÁFICO", bold=True, fg="white")
        lbl("─" * 28, fg="#555555")
        lbl("MODO:", bold=True, fg="#aaaaaa")
        self._lbl_mode = tk.Label(panel, text="LÍNEA", bg="#1e1e1e",
                                   fg="#3498db", font=("Helvetica", 11, "bold"),
                                   anchor="w")
        self._lbl_mode.pack(fill="x")

        lbl("─" * 28, fg="#555555")
        lbl("CONTROLES:", bold=True, fg="#aaaaaa")
        lbl("Click  → anclar punto")
        lbl("'n'    → nueva línea")
        lbl("'b'    → modo caja")
        lbl("'l'    → modo línea")
        lbl("Esc    → cancelar ROI actual")
        lbl("'q'    → finalizar")
        lbl("─" * 28, fg="#555555")

        self._lbl_temp = tk.Label(panel, text="Cursor: —", bg="#1e1e1e",
                                   fg="#f39c12", font=("Helvetica", 9, "bold"),
                                   anchor="w")
        self._lbl_temp.pack(fill="x", pady=2)

        lbl("─" * 28, fg="#555555")
        lbl("ROIs definidos:", bold=True, fg="#aaaaaa")
        self._lbl_rois = tk.Label(panel, text="Líneas: 0\nCajas:  0",
                                   bg="#1e1e1e", fg="#2ecc71",
                                   font=("Helvetica", 9), anchor="w",
                                   justify="left")
        self._lbl_rois.pack(fill="x")

        lbl("─" * 28, fg="#555555")
        btn_done = tk.Button(
            panel, text="✔  Finalizar (q)",
            bg="#27ae60", fg="white",
            font=("Helvetica", 9, "bold"),
            relief="flat", padx=6, pady=4,
            command=self._finish,
        )
        btn_done.pack(fill="x", pady=(8, 2))

        btn_cancel = tk.Button(
            panel, text="✖  Cancelar actual (Esc)",
            bg="#7f8c8d", fg="white",
            font=("Helvetica", 9),
            relief="flat", padx=6, pady=4,
            command=self._cancel_current,
        )
        btn_cancel.pack(fill="x", pady=2)

        # ── Event bindings ────────────────────────────────────────────
        self._canvas.bind("<ButtonPress-1>", self._on_click)
        self._canvas.bind("<Motion>", self._on_motion)
        self._root.bind("<Key>", self._on_key)
        self._root.protocol("WM_DELETE_WINDOW", self._finish)

    # ------------------------------------------------------------------ #
    #  Event handlers                                                      #
    # ------------------------------------------------------------------ #

    def _on_click(self, event):
        cx, cy = event.x, event.y
        if self._anchor is None:
            self._anchor = (cx, cy)
            # Draw anchor dot
            self._canvas.create_oval(
                cx - self._DOT_RADIUS, cy - self._DOT_RADIUS,
                cx + self._DOT_RADIUS, cy + self._DOT_RADIUS,
                fill=self._LINE_COLOR_TK if self._mode == _Mode.LINE else self._BOX_COLOR_TK,
                outline="", tags="roi_preview_dot",
            )
        else:
            # Second click → commit
            ax, ay = self._anchor
            px1, py1 = self._canvas_to_image(ax, ay)
            px2, py2 = self._canvas_to_image(cx, cy)
            if self._mode == _Mode.LINE:
                self._commit_line((px1, py1), (px2, py2))
            else:
                self._commit_box((px1, py1), (px2, py2))
            self._anchor = None
            self._canvas.delete("roi_preview_dot")
            self._canvas.delete("preview")
            self._update_info()

    def _on_motion(self, event):
        cx, cy = event.x, event.y
        # Update temperature display
        px, py = self._canvas_to_image(cx, cy)
        t = self._temp[py, px]
        self._lbl_temp.config(text=f"Cursor: {t:.2f} °C")

        # Rubber-band preview
        if self._anchor is not None:
            ax, ay = self._anchor
            self._canvas.delete("preview")
            if self._mode == _Mode.LINE:
                self._canvas.create_line(
                    ax, ay, cx, cy,
                    fill=self._PREVIEW_COLOR, width=1,
                    dash=(4, 4), tags="preview",
                )
            else:
                self._canvas.create_rectangle(
                    ax, ay, cx, cy,
                    outline=self._PREVIEW_COLOR, width=1,
                    dash=(4, 4), tags="preview",
                )

    def _on_key(self, event):
        key = event.keysym.lower()
        if key in ("q", "return") and self._anchor is None:
            self._finish()
        elif key == "n":
            self._cancel_current()
            self._mode = _Mode.LINE
            self._update_info()
        elif key == "b":
            self._cancel_current()
            self._mode = _Mode.BOX
            self._update_info()
        elif key == "l":
            self._cancel_current()
            self._mode = _Mode.LINE
            self._update_info()
        elif key == "escape":
            self._cancel_current()

    # ------------------------------------------------------------------ #
    #  ROI commit helpers                                                  #
    # ------------------------------------------------------------------ #

    def _commit_line(self, p1, p2):
        self._line_counter += 1
        label = f"Li{self._line_counter}"
        color_tk = self._LINE_PALETTE_TK[(self._line_counter - 1) % len(self._LINE_PALETTE_TK)]
        color_pil = self._LINE_PALETTE_PIL[(self._line_counter - 1) % len(self._LINE_PALETTE_PIL)]

        self._lines.append(LineROI(label=label, p1=p1, p2=p2))

        # Draw on canvas (scaled coords)
        cx1 = int(p1[0] * self._scale)
        cy1 = int(p1[1] * self._scale)
        cx2 = int(p2[0] * self._scale)
        cy2 = int(p2[1] * self._scale)

        self._canvas.create_line(cx1, cy1, cx2, cy2,
                                  fill=color_tk, width=2, tags="roi")
        for cx, cy in [(cx1, cy1), (cx2, cy2)]:
            self._canvas.create_oval(
                cx - self._DOT_RADIUS, cy - self._DOT_RADIUS,
                cx + self._DOT_RADIUS, cy + self._DOT_RADIUS,
                fill=color_tk, outline="", tags="roi",
            )
        # Label at start point
        self._canvas.create_text(
            cx1 + 6, cy1 - 10,
            text=label, fill=color_tk,
            font=("Helvetica", 8, "bold"), tags="roi",
        )

    def _commit_box(self, p1, p2):
        self._box_counter += 1
        label = f"Bx{self._box_counter}"
        x1, y1 = min(p1[0], p2[0]), min(p1[1], p2[1])
        x2, y2 = max(p1[0], p2[0]), max(p1[1], p2[1])

        self._boxes.append(BoxROI(label=label, x1=x1, y1=y1, x2=x2, y2=y2))

        cx1, cy1 = int(x1 * self._scale), int(y1 * self._scale)
        cx2, cy2 = int(x2 * self._scale), int(y2 * self._scale)

        self._canvas.create_rectangle(
            cx1, cy1, cx2, cy2,
            outline=self._BOX_COLOR_TK, width=2, tags="roi",
        )
        self._canvas.create_text(
            cx1 + 4, cy1 + 4,
            text=label, fill=self._BOX_COLOR_TK,
            font=("Helvetica", 8, "bold"), anchor="nw", tags="roi",
        )

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _canvas_to_image(self, cx: int, cy: int) -> tuple:
        px = int(cx / self._scale)
        py = int(cy / self._scale)
        px = max(0, min(px, self._img_w - 1))
        py = max(0, min(py, self._img_h - 1))
        return px, py

    def _cancel_current(self):
        self._anchor = None
        self._canvas.delete("preview")
        self._canvas.delete("roi_preview_dot")
        self._update_info()

    def _update_info(self):
        mode_text = "LÍNEA" if self._mode == _Mode.LINE else "CAJA"
        mode_color = "#3498db" if self._mode == _Mode.LINE else "#ffdc00"
        self._lbl_mode.config(text=mode_text, fg=mode_color)
        self._lbl_rois.config(
            text=f"Líneas:  {len(self._lines)}\nCajas:   {len(self._boxes)}"
        )
        self._root.title(
            f"ROI — {self._title} | "
            f"{len(self._lines)} líneas, {len(self._boxes)} cajas | 'q' para finalizar"
        )

    def _finish(self):
        if len(self._lines) == 0 and len(self._boxes) == 0:
            if not messagebox.askyesno(
                "Sin ROIs",
                "No se definieron líneas ni cajas.\n"
                "¿Continuar sin análisis de perfil?",
            ):
                return
        self._result_ready = True
        if hasattr(self, '_is_toplevel') and self._is_toplevel:
            self._root.grab_release()
            self._root.destroy()
        else:
            self._root.quit()
