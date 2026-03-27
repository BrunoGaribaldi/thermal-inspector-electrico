"""
reporter.py — PDF report generator for thermal inspection results.
"""

import os
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image as RLImage, KeepTogether
)
from io import BytesIO
from PIL import Image as PILImage
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

PAGE_W, PAGE_H = A4
MARGIN = 1.2 * cm

BLUE_DARK = colors.HexColor("#16365C")
BLUE_LIGHT = colors.HexColor("#DCE6F1")
GREEN_OK = colors.HexColor("#92D050")
GREY_BG = colors.HexColor("#F2F2F2")

_ZERO_PAD = [
    ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ("TOPPADDING", (0, 0), (-1, -1), 0),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
]

_LINE_COLORS_MPL = ['#C0392B', '#27AE60', '#2980B9', '#E67E22', '#8E44AD']
_LINE_COLORS_RL = [
    colors.HexColor('#C0392B'),
    colors.HexColor('#27AE60'),
    colors.HexColor('#2980B9'),
    colors.HexColor('#E67E22'),
    colors.HexColor('#8E44AD'),
]


def _np_to_rl_image(rgb_array: np.ndarray, max_w: float, max_h: float) -> RLImage:
    buf = BytesIO()
    pil = PILImage.fromarray(rgb_array.astype(np.uint8))
    pil.save(buf, format="PNG")
    buf.seek(0)
    img = RLImage(buf)
    h, w = rgb_array.shape[:2]
    scale = min(max_w / w, max_h / h, 1.0)
    img.drawWidth = w * scale
    img.drawHeight = h * scale
    img.hAlign = 'CENTER'
    return img


def _make_profile_chart(line_stats: list, box_stats: list, spot_stats: list) -> BytesIO | None:
    if not line_stats:
        return None

    fig, ax = plt.subplots(figsize=(5, 2.8))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')

    for i, line in enumerate(line_stats):
        samples = np.array(line.get('samples', []))
        if samples.size == 0:
            continue
        color = _LINE_COLORS_MPL[i % len(_LINE_COLORS_MPL)]
        ax.plot(np.arange(len(samples)), samples, color=color, linewidth=0.9)

    ax.set_ylabel("°C", fontsize=8)
    ax.tick_params(axis='both', which='major', labelsize=7)
    ax.grid(axis="y", linestyle=":", alpha=0.45, color='grey')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_color('#CCCCCC')
    ax.spines['left'].set_color('#CCCCCC')

    fig.tight_layout(pad=0.3)
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor='white')
    plt.close(fig)
    buf.seek(0)
    return buf


def _make_endpoints_chart(line_stats: list) -> BytesIO | None:
    """Chart showing temperatures at the start (A) and end (B) points of each line."""
    valid = [ls for ls in line_stats if ls.get('samples')]
    if not valid:
        return None

    from matplotlib.lines import Line2D

    fig, ax = plt.subplots(figsize=(5, 2.4))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')

    labels = []
    for i, line in enumerate(valid):
        color = _LINE_COLORS_MPL[i % len(_LINE_COLORS_MPL)]
        t_a = line['t_start']
        t_b = line['t_end']

        ax.scatter(i - 0.13, t_a, color=color, marker='o', s=70, zorder=5, edgecolors='white', linewidths=0.5)
        ax.scatter(i + 0.13, t_b, color=color, marker='s', s=70, zorder=5, edgecolors='white', linewidths=0.5)

        ax.plot([i - 0.13, i + 0.13], [t_a, t_b], color=color, linewidth=1.2, alpha=0.35)

        va_a = 'bottom' if t_a <= t_b else 'top'
        va_b = 'bottom' if t_b >= t_a else 'top'
        off_a = 7 if va_a == 'bottom' else -7
        off_b = 7 if va_b == 'bottom' else -7

        ax.annotate(f"{t_a:.1f}°C", (i - 0.13, t_a), textcoords="offset points",
                    xytext=(0, off_a), ha='center', va=va_a, fontsize=7, color=color, fontweight='bold')
        ax.annotate(f"{t_b:.1f}°C", (i + 0.13, t_b), textcoords="offset points",
                    xytext=(0, off_b), ha='center', va=va_b, fontsize=7, color=color, fontweight='bold')

        labels.append(line['label'])

    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=8, fontweight='bold')
    ax.set_ylabel("°C", fontsize=8)
    ax.tick_params(axis='y', labelsize=7)
    ax.grid(axis="y", linestyle=":", alpha=0.45, color='grey')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_color('#CCCCCC')
    ax.spines['left'].set_color('#CCCCCC')

    margin = 0.5
    ax.set_xlim(-0.5, len(labels) - 0.5)
    y_min, y_max = ax.get_ylim()
    ax.set_ylim(y_min - margin, y_max + margin)

    legend_elements = [
        Line2D([0], [0], marker='o', color='grey', markerfacecolor='grey',
               markersize=6, label='Punto A (inicio)', linestyle='None'),
        Line2D([0], [0], marker='s', color='grey', markerfacecolor='grey',
               markersize=6, label='Punto B (fin)', linestyle='None'),
    ]
    ax.legend(handles=legend_elements, fontsize=7, loc='upper right', framealpha=0.8)

    fig.tight_layout(pad=0.3)
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor='white')
    plt.close(fig)
    buf.seek(0)
    return buf


class ThermalReport:
    def __init__(self, output_path: str, meta: dict, logo_path: str = None):
        self._path = output_path
        self._meta = meta
        self._logo_path = logo_path
        self._entries: list = []

        self._styles = getSampleStyleSheet()
        self._styles.add(ParagraphStyle("TitleStyle", fontSize=18, textColor=BLUE_DARK,
                                        fontName="Helvetica-Bold", alignment=1, spaceAfter=20))
        self._styles.add(ParagraphStyle("HeaderWhite", fontSize=10, textColor=colors.white,
                                        fontName="Helvetica-Bold", alignment=0))
        self._styles.add(ParagraphStyle("HeaderWhiteCenter", fontSize=10, textColor=colors.white,
                                        fontName="Helvetica-Bold", alignment=1))
        self._styles.add(ParagraphStyle("DataKey", fontSize=9, textColor=colors.black,
                                        fontName="Helvetica-Bold"))
        self._styles.add(ParagraphStyle("DataValue", fontSize=9, textColor=colors.black,
                                        fontName="Helvetica"))
        self._styles.add(ParagraphStyle("DataValueCenter", fontSize=9, textColor=colors.black,
                                        fontName="Helvetica", alignment=1))
        self._styles.add(ParagraphStyle("DataValueWhite", fontSize=9, textColor=colors.white,
                                        fontName="Helvetica-Bold"))
        self._styles.add(ParagraphStyle("FooterText", fontSize=8, textColor=colors.black,
                                        alignment=1))

    def add_entry(self, entry: dict) -> int:
        self._entries.append(entry)
        return len(self._entries) + 2

    def build(self):
        doc = SimpleDocTemplate(
            self._path, pagesize=A4,
            leftMargin=MARGIN, rightMargin=MARGIN,
            topMargin=MARGIN, bottomMargin=MARGIN * 1.5
        )

        story = []

        story += self._cover_page()
        story.append(PageBreak())

        story += self._index_page()
        story.append(PageBreak())

        for i, entry in enumerate(self._entries, 1):
            story += self._entry_pages(entry, i)
            if i < len(self._entries):
                story.append(PageBreak())

        doc.build(story, onFirstPage=self._header_footer, onLaterPages=self._header_footer)

    # ------------------------------------------------------------------ #
    #  Cover page                                                          #
    # ------------------------------------------------------------------ #

    def _cover_page(self) -> list:
        tw = PAGE_W - 2 * MARGIN
        elements = []

        if self._logo_path and os.path.isfile(self._logo_path):
            elements.append(Spacer(1, 1.5 * cm))
            try:
                logo = RLImage(self._logo_path)
                logo_max = 5.5 * cm
                scale = min(logo_max / logo.imageWidth, logo_max / logo.imageHeight)
                logo.drawWidth = logo.imageWidth * scale
                logo.drawHeight = logo.imageHeight * scale
                logo.hAlign = 'CENTER'
                elements.append(logo)
                elements.append(Spacer(1, 1.2 * cm))
            except Exception:
                elements.append(Spacer(1, 3 * cm))
        else:
            elements.append(Spacer(1, 4 * cm))

        elements.append(Paragraph("Mantenimiento Predictivo - Termografía",
                                  self._styles["TitleStyle"]))
        elements.append(Paragraph(
            "SECTOR DE MANTENIMIENTO<br/>PREDICTIVO ELÉCTRICO",
            ParagraphStyle("SubTitle", fontSize=14, alignment=1, spaceAfter=2 * cm)))

        info_rows = [
            [Paragraph("<b>Lugar:</b>", self._styles["DataValue"]),
             Paragraph(self._meta.get("ubicacion_general", ""), self._styles["DataValue"])],
            [Paragraph("<b>Inspector:</b>", self._styles["DataValue"]),
             Paragraph(self._meta.get("inspector", ""), self._styles["DataValue"])],
            [Paragraph("<b>Período:</b>", self._styles["DataValue"]),
             Paragraph(self._meta.get("fecha", ""), self._styles["DataValue"])],
            [Paragraph("<b>N° Informe:</b>", self._styles["DataValue"]),
             Paragraph(self._meta.get("id_informe", ""), self._styles["DataValue"])],
        ]

        tbl = Table(info_rows, colWidths=[3.5 * cm, tw - 3.5 * cm])
        tbl.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("BACKGROUND", (0, 0), (0, -1), GREY_BG),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        tbl.hAlign = 'CENTER'
        elements.append(tbl)
        return elements

    # ------------------------------------------------------------------ #
    #  Index page                                                          #
    # ------------------------------------------------------------------ #

    def _index_page(self) -> list:
        tw = PAGE_W - 2 * MARGIN
        elements = [Paragraph("ÍNDICE DE TERMOGRAMAS", self._styles["TitleStyle"]),
                    Spacer(1, 0.5 * cm)]

        index_data = [["Ubicación", "Equipo", "Componente", "Diagnóstico",
                       "Prioridad", "Precinto", "Pág."]]

        for idx, entry in enumerate(self._entries, 1):
            diag = entry.get('estado', 'Admisible')
            page_num = str(idx + 2)
            is_ok = diag.lower() in ['admisible', 'normal']
            diag_style = self._styles["DataValueWhite"] if is_ok else self._styles["DataValueCenter"]

            index_data.append([
                Paragraph(entry.get('ubicacion', ''), self._styles["DataValue"]),
                Paragraph(entry.get('equipo', ''), self._styles["DataValue"]),
                Paragraph(entry.get('componente', ''), self._styles["DataValue"]),
                Paragraph(diag, diag_style),
                Paragraph(entry.get('prioridad', 'N/A'), self._styles["DataValueCenter"]),
                Paragraph(entry.get('precinto', 'N/A'), self._styles["DataValueCenter"]),
                Paragraph(page_num, self._styles["DataValueCenter"]),
            ])

        col_widths = [tw * 0.20, tw * 0.15, tw * 0.20, tw * 0.15,
                      tw * 0.10, tw * 0.10, tw * 0.10]
        tbl = Table(index_data, colWidths=col_widths)

        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), BLUE_DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (3, 1), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]

        for row_idx, entry in enumerate(self._entries, 1):
            if entry.get('estado', 'Admisible').lower() in ['admisible', 'normal']:
                style_cmds.append(("BACKGROUND", (3, row_idx), (3, row_idx), GREEN_OK))

        tbl.setStyle(TableStyle(style_cmds))
        tbl.hAlign = 'CENTER'
        elements.append(tbl)
        return elements

    # ------------------------------------------------------------------ #
    #  Entry pages (one per thermogram)                                    #
    # ------------------------------------------------------------------ #

    def _entry_pages(self, entry: dict, idx: int) -> list:
        tw = PAGE_W - 2 * MARGIN
        half_w = tw / 2.0
        elements = []

        # ── Row 1: image headers ──────────────────────────────────────
        h_table = Table(
            [[Paragraph("TERMOGRAMA", self._styles["HeaderWhiteCenter"]),
              Paragraph("IMAGEN VISUAL", self._styles["HeaderWhiteCenter"])]],
            colWidths=[half_w, half_w])
        h_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BLUE_DARK),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(h_table)

        # ── Row 2: images ─────────────────────────────────────────────
        img_h = 7.0 * cm
        color_rgb = entry.get("color_rgb")
        rgb_path = entry.get("rgb_path")

        img_cells = []
        if color_rgb is not None:
            img_cells.append(_np_to_rl_image(color_rgb, half_w - 6, img_h - 6))
        else:
            img_cells.append("")

        if rgb_path:
            try:
                vis = RLImage(rgb_path)
                s = min((half_w - 6) / vis.imageWidth, (img_h - 6) / vis.imageHeight)
                vis.drawWidth = vis.imageWidth * s
                vis.drawHeight = vis.imageHeight * s
                vis.hAlign = 'CENTER'
                img_cells.append(vis)
            except Exception:
                img_cells.append(Paragraph("Imagen visual no disponible",
                                           self._styles["DataValueCenter"]))
        else:
            img_cells.append(Paragraph("Sin imagen visual",
                                       self._styles["DataValueCenter"]))

        img_tbl = Table([img_cells], colWidths=[half_w, half_w], rowHeights=[img_h])
        img_tbl.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        elements.append(img_tbl)

        # ── Row 2b: GPS location ──────────────────────────────────────
        gps_coord = entry.get("gps_coord", "")
        gps_url = entry.get("gps_url", "")
        if gps_coord:
            gps_header = Table(
                [[Paragraph("UBICACIÓN GPS", self._styles["HeaderWhiteCenter"])]],
                colWidths=[tw])
            gps_header.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), BLUE_DARK),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            elements.append(gps_header)

            link_style = ParagraphStyle(
                "GPSLink", fontSize=9, textColor=colors.HexColor("#2471A3"),
                fontName="Helvetica")
            if gps_url:
                gps_text = (
                    f'<b>Coordenadas:</b> {gps_coord} &nbsp;&nbsp;|&nbsp;&nbsp; '
                    f'<a href="{gps_url}" color="#2471A3">'
                    f'<u>Ver en Google Maps</u></a>'
                )
            else:
                gps_text = f'<b>Coordenadas:</b> {gps_coord}'

            gps_body = Table(
                [[Paragraph(gps_text, link_style)]],
                colWidths=[tw])
            gps_body.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), BLUE_LIGHT),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            elements.append(gps_body)

        # ── Row 3: data headers ───────────────────────────────────────
        h2_table = Table(
            [[Paragraph("TABLA DE DATOS", self._styles["HeaderWhiteCenter"]),
              Paragraph("PERFIL TÉRMICO", self._styles["HeaderWhiteCenter"])]],
            colWidths=[half_w, half_w])
        h2_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BLUE_DARK),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(h2_table)

        # ── Row 4: data table (left) + chart (right) ─────────────────
        diag = entry.get("estado", "Normal")
        is_ok = diag.lower() in ['admisible', 'normal']
        diag_p = Paragraph(diag, self._styles["DataValueWhite"] if is_ok
                           else self._styles["DataValue"])

        data_rows = [
            [Paragraph("Ubicación", self._styles["DataKey"]),
             Paragraph(entry.get('ubicacion', ''), self._styles["DataValue"])],
            [Paragraph("Equipo", self._styles["DataKey"]),
             Paragraph(entry.get('equipo', ''), self._styles["DataValue"])],
            [Paragraph("Componente", self._styles["DataKey"]),
             Paragraph(entry.get('componente', ''), self._styles["DataValue"])],
            [Paragraph("Diagnóstico", self._styles["DataKey"]), diag_p],
            [Paragraph("Prioridad", self._styles["DataKey"]),
             Paragraph(entry.get('prioridad', 'N/A'), self._styles["DataValue"])],
            [Paragraph("Precinto", self._styles["DataKey"]),
             Paragraph(entry.get('precinto', 'N/A'), self._styles["DataValue"])],
            [Paragraph("Measurements", self._styles["HeaderWhite"]), ""],
        ]
        meas_row = len(data_rows) - 1

        for bx in entry.get("box_stats", []):
            data_rows.append([
                Paragraph(f"{bx['label']} Maximum", self._styles["DataKey"]),
                Paragraph(f"{bx['t_max']:.1f} °C", self._styles["DataValue"]),
            ])
        if not entry.get("box_stats"):
            data_rows.append([
                Paragraph("Máxima Detectada", self._styles["DataKey"]),
                Paragraph(f"{entry.get('t_max', 0):.1f} °C", self._styles["DataValue"]),
            ])
        data_rows.append([Paragraph("Spots", self._styles["DataKey"]),
                          Paragraph("-", self._styles["DataValue"])])
        data_rows.append([Paragraph("Deltas", self._styles["DataKey"]),
                          Paragraph("-", self._styles["DataValue"])])

        data_t = Table(data_rows, colWidths=[half_w * 0.42, half_w * 0.58])
        data_style = [
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, meas_row), (-1, meas_row), BLUE_DARK),
            ("SPAN", (0, meas_row), (1, meas_row)),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        if is_ok:
            data_style.append(("BACKGROUND", (1, 3), (1, 3), GREEN_OK))
        data_t.setStyle(TableStyle(data_style))

        # Profile chart
        chart_img = ""
        chart_buf = _make_profile_chart(
            entry.get("line_stats", []),
            entry.get("box_stats", []),
            entry.get("spot_stats", []))
        if chart_buf:
            chart_img = RLImage(chart_buf)
            chart_img.drawWidth = half_w - 8
            chart_img.drawHeight = 4.8 * cm
            chart_img.hAlign = 'CENTER'

        # Endpoints chart (A/B temperatures)
        endpts_img = ""
        endpts_buf = _make_endpoints_chart(entry.get("line_stats", []))
        if endpts_buf:
            endpts_img = RLImage(endpts_buf)
            endpts_img.drawWidth = half_w - 8
            endpts_img.drawHeight = 3.5 * cm
            endpts_img.hAlign = 'CENTER'

        # Stats table
        scw = half_w / 4.0
        stats_rows = [[
            Paragraph("<b>Label</b>", self._styles["DataValueCenter"]),
            Paragraph("<b>Minimum</b>", self._styles["DataValueCenter"]),
            Paragraph("<b>Maximum</b>", self._styles["DataValueCenter"]),
            Paragraph("<b>Average</b>", self._styles["DataValueCenter"]),
        ]]
        stats_style = [
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
            ("BACKGROUND", (0, 0), (-1, 0), BLUE_LIGHT),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        for i, st in enumerate(entry.get("line_stats", [])):
            rl_c = _LINE_COLORS_RL[i % len(_LINE_COLORS_RL)]
            lbl_s = ParagraphStyle(f"_lc{idx}_{i}", fontSize=8, textColor=rl_c,
                                   fontName="Helvetica-Bold", alignment=1)
            stats_rows.append([
                Paragraph(st['label'], lbl_s),
                Paragraph(f"{st['t_min']:.2f}", self._styles["DataValueCenter"]),
                Paragraph(f"{st['t_max']:.2f}", self._styles["DataValueCenter"]),
                Paragraph(f"{st['t_mean']:.2f}", self._styles["DataValueCenter"]),
            ])

        stats_t = Table(stats_rows, colWidths=[scw] * 4)
        stats_t.setStyle(TableStyle(stats_style))

        right_rows = []
        if chart_img:
            right_rows.append([chart_img])
        if endpts_img:
            right_rows.append([endpts_img])
        right_rows.append([stats_t])

        right_q = Table(right_rows, colWidths=[half_w])
        right_q.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ] + _ZERO_PAD))

        mid_table = Table([[data_t, right_q]], colWidths=[half_w, half_w])
        mid_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ] + _ZERO_PAD))
        elements.append(mid_table)

        # ── Row 5: text blocks ────────────────────────────────────────
        text_rows = [
            [Paragraph("DIAGNÓSTICO", self._styles["DataKey"])],
            [Paragraph(entry.get("diagnostico_texto", ""), self._styles["DataValue"])],
            [Paragraph("RECOMENDACIONES", self._styles["DataKey"])],
            [Paragraph(entry.get("recomendaciones", ""), self._styles["DataValue"])],
            [Paragraph("REPARACIONES REALIZADAS", self._styles["DataKey"])],
            [Paragraph(entry.get("reparaciones", ""), self._styles["DataValue"])],
        ]

        text_t = Table(text_rows, colWidths=[tw])
        text_t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), BLUE_LIGHT),
            ("BACKGROUND", (0, 2), (0, 2), BLUE_LIGHT),
            ("BACKGROUND", (0, 4), (0, 4), BLUE_LIGHT),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(text_t)

        return [KeepTogether(elements)]

    # ------------------------------------------------------------------ #
    #  Header / footer                                                     #
    # ------------------------------------------------------------------ #

    def _header_footer(self, canvas, doc):
        canvas.saveState()
        tw = PAGE_W - 2 * MARGIN

        if doc.page > 1:
            canvas.setFillColor(BLUE_DARK)
            canvas.rect(MARGIN, PAGE_H - MARGIN + 10, tw, 15, fill=1, stroke=0)
            canvas.setFillColor(colors.white)
            canvas.setFont("Helvetica-Bold", 9)
            canvas.drawString(MARGIN + 5, PAGE_H - MARGIN + 14,
                              "Mantenimiento Predictivo - Termografía")

        canvas.restoreState()
