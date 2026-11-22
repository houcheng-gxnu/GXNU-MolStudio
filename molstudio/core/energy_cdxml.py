# -*- coding: utf-8 -*-
"""Export energy-profile diagrams as editable ChemDraw CDXML.

CDXML is an XML representation of ChemDraw objects.  This writer deliberately
uses only native ChemDraw graphic lines and text objects, so the exported
diagram can be opened, moved, recoloured, and edited directly in ChemDraw.

The coordinate and object layout follows the public CDXML structure used by
Energy Diagram Plotter CDXML (Yuanhe Li, Apache-2.0):
https://github.com/liyuanhe211/Energy_Diagram_Plotter_CDXML
"""

import math
import os
import re
from html import escape


_BASE_COLORS = [
    (1.0, 1.0, 1.0),  # white
    (0.0, 0.0, 0.0),  # black
    (1.0, 0.0, 0.0),
    (1.0, 1.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 1.0, 1.0),
    (0.0, 0.0, 1.0),
    (1.0, 0.0, 1.0),
]


def _number(value):
    """Compact, locale-independent number formatting for CDXML attributes."""
    value = float(value)
    if abs(value) < 0.00005:
        return "0"
    text = "%.4f" % value
    return text.rstrip("0").rstrip(".")


def _xml_attr(value):
    return escape(str(value), quote=True)


def _hex_to_rgb(value):
    text = str(value).strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        raise ValueError("Unsupported colour value: %s" % text)
    return tuple(int(text[i:i + 2], 16) / 255.0 for i in (1, 3, 5))


class _Ids:
    def __init__(self, start=1000):
        self.value = start

    def next(self):
        value = self.value
        self.value += 1
        return value


class _Colors:
    """CDXML colour table.

    ChemDraw's colour index is the one-based index in the XML table plus one;
    the first two table entries are treated specially.  Keeping this rule here
    avoids mismatches between the preview colours and ChemDraw colours.
    """

    def __init__(self):
        self.entries = list(_BASE_COLORS)
        self.lookup = {rgb: index + 2 for index, rgb in enumerate(self.entries)}

    def index(self, color):
        if not isinstance(color, str) or not color.startswith("#"):
            raise ValueError("Unsupported colour value: %s" % color)
        rgb = _hex_to_rgb(color)
        if rgb not in self.lookup:
            self.entries.append(rgb)
            self.lookup[rgb] = len(self.entries) + 1
        return self.lookup[rgb]

    def xml(self):
        rows = ["<colortable>"]
        for red, green, blue in self.entries:
            rows.append(
                '<color r="%s" g="%s" b="%s"/>'
                % (_number(red), _number(green), _number(blue))
            )
        rows.append("</colortable>")
        return "\n".join(rows)


def _nice_ticks(low, high, target=6):
    span = float(high) - float(low)
    if span <= 0:
        return []
    raw_step = span / max(target, 1)
    magnitude = 10.0 ** math.floor(math.log10(raw_step))
    normalized = raw_step / magnitude
    if normalized <= 1.0:
        step = magnitude
    elif normalized <= 2.0:
        step = 2.0 * magnitude
    elif normalized <= 2.5:
        step = 2.5 * magnitude
    elif normalized <= 5.0:
        step = 5.0 * magnitude
    else:
        step = 10.0 * magnitude

    first = math.ceil(float(low) / step - 1e-10) * step
    values = []
    value = first
    while value <= float(high) + step * 1e-8:
        clean = 0.0 if abs(value) < step * 1e-8 else value
        values.append(clean)
        value += step
    return values, step


def _line_pair(ids, x1, y1, x2, y2, z, color_index, width=0.6,
               dashed=False, bold=False):
    """Return a ChemDraw line graphic and its backing arrow object."""
    graphic_id = ids.next()
    arrow_id = ids.next()
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    bbox = "%s %s %s %s" % (
        _number(left), _number(top), _number(right), _number(bottom)
    )
    line_type = ""
    if dashed:
        line_type = ' LineType="Dashed"'
    elif bold:
        line_type = ' LineType="Bold"'

    graphic = (
        '<graphic id="%s" SupersededBy="%s" BoundingBox="%s" Z="%s" '
        'color="%s" GraphicType="Line"%s/>'
        % (graphic_id, arrow_id, bbox, z, color_index, line_type)
    )
    arrow = (
        '<arrow id="%s" BoundingBox="%s" Z="%s" FillType="None" '
        'ArrowheadType="Solid" color="%s" Head3D="%s %s 0" '
        'LineWidth="%s" Tail3D="%s %s 0" Center3D="538.5 445.75 0" '
        'MajorAxisEnd3D="735.5 445.75 0" '
        'MinorAxisEnd3D="538.5 642.75 0"%s/>'
        % (
            arrow_id, bbox, z, color_index, _number(x2), _number(y2),
            _number(width), _number(x1), _number(y1), line_type
        )
    )
    return graphic + arrow


def _node(ids, x, y, z):
    node_id = ids.next()
    return node_id, (
        '<n id="%s" p="%s %s" Z="%s" AS="N"/>'
        % (node_id, _number(x), _number(y), z)
    )


def _bond(ids, begin_id, end_id, z, color_index, display=None):
    display_attr = ' Display="%s"' % display if display else ""
    return (
        '<b id="%s" Z="%s" color="%s" B="%s" E="%s"%s BS="N"/>'
        % (
            ids.next(), z, color_index, begin_id, end_id,
            display_attr
        )
    )


def _fragment(ids, children, z, bbox):
    bbox_text = "%s %s %s %s" % tuple(_number(item) for item in bbox)
    return (
        '<fragment id="%s" BoundingBox="%s" Z="%s">%s</fragment>'
        % (ids.next(), bbox_text, z, "".join(children))
    )


def _text(ids, value, x, y, z, color_index, size, bold=False,
          align="Center", vertical=False):
    if value is None or str(value).strip() == "":
        return ""
    face = 1 if bold else 0
    rotation = (' RotationAngle="17694720"' if vertical else "")
    text_id = ids.next()
    return (
        '<t id="%s" p="%s %s" BoundingBox="0 0 110 110" Z="%s" '
        'CaptionJustification="%s" Justification="%s"%s LineHeight="auto">'
        '<s font="3" size="%s" color="%s" face="%s">%s</s></t>'
        % (
            text_id, _number(x), _number(y), z, align, align, rotation,
            _number(size), color_index, face, escape(str(value))
        )
    )


def _group(ids, children, z, bbox=None, integral=False):
    if not children:
        return ""
    if bbox is None:
        bbox = "0 0 0 0"
    else:
        bbox = "%s %s %s %s" % tuple(_number(item) for item in bbox)
    integral_attr = ' Integral="yes"' if integral else ""
    return (
        '<group id="%s" BoundingBox="%s" Z="%s"%s>%s</group>'
        % (ids.next(), bbox, z, integral_attr, "".join(children))
    )


def _document_objects(objects, width, height, name, colors, page_id):
    root_bbox = "0 0 %s %s" % (_number(width), _number(height))
    return """<?xml version="1.0" encoding="UTF-8" ?>
<!DOCTYPE CDXML SYSTEM "http://www.cambridgesoft.com/xml/cdxml.dtd" >
<CDXML CreationProgram="GXNU MolStudio" Name="%s"
 BoundingBox="%s" WindowPosition="0 0"
 WindowSize="-2147483648 -2147483648" WindowIsZoomed="yes"
 LabelFont="3" LabelSize="10" LabelFace="96"
 CaptionFont="3" CaptionSize="10" HashSpacing="2.49"
 MarginWidth="1.59" LineWidth="0.60" BoldWidth="2.01"
 BondLength="14.40" BondSpacing="18"
 PrintMargins="99.21 70.87 99.21 70.87" color="0" bgcolor="1">
%s
<fonttable>
<font id="3" charset="iso-8859-1" name="Arial"/>
</fonttable>
<page id="%s" BoundingBox="%s" HeaderPosition="36"
 FooterPosition="36" PrintTrimMarks="yes"
 HeightPages="1" WidthPages="1">
%s
</page>
</CDXML>
""" % (
        _xml_attr(name), root_bbox, colors.xml(), page_id, root_bbox,
        "\n".join(objects)
    )


def build_energy_diagram_cdxml(
        species,
        result,
        *,
        show_values=True,
        show_tags=True,
        show_grid=True,
        show_span=True,
        line_width=3.0,
        tag_size=12,
        state_span=0.6,
        value_decimals=1,
        y_label="ΔG (kcal/mol)",
        chemdraw_objects="lines",
        link_style="solid",
        filename="energy_span.cdxml"):
    """Build an editable CDXML energy profile from the panel's data model.

    ``species`` and ``result`` use the same dictionaries as
    ``energy_span_panel.compute_energy_span``.  The custom-cycle species in
    ``result["cycle2Species"]`` are included when present.
    """
    if not species or len(species) < 2:
        raise ValueError("At least two species are required")
    if not result:
        raise ValueError("Energy-span result is required")
    if int(result.get("TDI_idx", -1)) < 0 or int(result.get("TDTS_idx", -1)) < 0:
        raise ValueError("TDI/TDTS result is missing")
    state_span = float(state_span)
    if not 0.05 <= state_span <= 1.0:
        raise ValueError("State span must be between 0.05 and 1.0")
    value_decimals = int(value_decimals)
    if not 0 <= value_decimals <= 6:
        raise ValueError("Value decimals must be between 0 and 6")
    if chemdraw_objects not in ("lines", "bonds"):
        raise ValueError("ChemDraw objects must be 'lines' or 'bonds'")
    if link_style not in ("solid", "dashed"):
        raise ValueError("Link style must be 'solid' or 'dashed'")
    y_label = str(y_label).strip() or "ΔG (kcal/mol)"
    value_format = "%." + str(value_decimals) + "f"

    paths = [{
        "label": "cycle 1",
        "color": "#4f46e5",
        "data": list(species),
    }]
    if result.get("needCycle2") and result.get("cycle2Species"):
        paths.append({
            "label": "cycle 2",
            "color": "#14b8a6",
            "data": list(result["cycle2Species"]),
        })

    cycle1_len = len(paths[0]["data"])
    total_states = cycle1_len + (
        len(paths[1]["data"]) if len(paths) > 1 else 0
    )
    all_y = [float(point["G"]) for path in paths for point in path["data"]]
    data_min = min(all_y)
    data_max = max(all_y)
    data_range = data_max - data_min if data_max != data_min else 1.0
    y_pad = data_range * 0.25
    y_min = data_min - y_pad
    y_max = data_max + y_pad

    plot_left = 135.0
    plot_right = plot_left + max(540.0, max(total_states - 1, 1) * 105.0)
    page_width = plot_right + 70.0
    page_height = 520.0
    plot_top = 50.0
    plot_bottom = page_height - 90.0
    plot_width = plot_right - plot_left
    plot_height = plot_bottom - plot_top

    x_min = -0.8
    x_max = total_states - 0.2

    def x_map(value):
        return plot_left + (float(value) - x_min) * plot_width / (
            x_max - x_min
        )

    def y_map(value):
        return plot_top + (y_max - float(value)) * plot_height / (
            y_max - y_min
        )

    ids = _Ids()
    colors = _Colors()
    objects = []
    text_objects = []

    black = colors.index("#000000")
    gray_text = colors.index("#666666")
    grid_color = colors.index("#d1d5db")
    separator_color = colors.index("#cccccc")

    # Horizontal grid and Y axis.  The preview has only left/bottom spines and
    # no numeric X ticks, so the CDXML uses the same visual grammar.
    tick_result = _nice_ticks(y_min, y_max)
    ticks, tick_step = tick_result if tick_result else ([], 1.0)
    if show_grid:
        for tick in ticks:
            y = y_map(tick)
            objects.append(_line_pair(
                ids, plot_left, y, plot_right, y, 10, grid_color,
                width=0.5, dashed=True
            ))

    objects.append(_line_pair(
        ids, plot_left, plot_top, plot_left, plot_bottom, 20, black,
        width=0.8
    ))
    objects.append(_line_pair(
        ids, plot_left, plot_bottom, plot_right, plot_bottom, 20, black,
        width=0.8
    ))

    if tick_step >= 1:
        tick_format = "%.0f"
    elif tick_step >= 0.1:
        tick_format = "%.1f"
    else:
        tick_format = "%.2f"
    for tick in ticks:
        y = y_map(tick)
        objects.append(_line_pair(
            ids, plot_left - 5, y, plot_left, y, 21, black, width=0.6
        ))
        text_objects.append(_text(
            ids, tick_format % tick, plot_left - 10, y, 240, black,
            9.5, align="Right"
        ))

    text_objects.append(_text(
        ids, y_label, 62, (plot_top + plot_bottom) / 2.0,
        240, black, max(10, tag_size), bold=True, vertical=True
    ))
    text_objects.append(_text(
        ids, "Reaction Coordinate", (plot_left + plot_right) / 2.0,
        plot_bottom + 42, 240, black, max(10, tag_size), bold=True
    ))

    if len(paths) > 1:
        separator_x = x_map(cycle1_len - 0.5)
        objects.append(_line_pair(
            ids, separator_x, plot_top, separator_x, plot_bottom, 30,
            separator_color, width=0.8, dashed=True
        ))

    step_w = state_span
    half = step_w / 2.0
    state_width = max(float(line_width), 0.5)
    connector_width = max(float(line_width) * 0.7, 0.5)
    connector_dashed = link_style == "dashed"

    for path_index, path in enumerate(paths):
        color_index = colors.index(path["color"])
        offset = cycle1_len if path_index == 1 else 0
        points = path["data"]
        line_children = []
        bond_nodes = []
        bond_children = []
        path_y = []
        state_nodes = []
        z_base = 100 + path_index * 20

        for point_index, point in enumerate(points):
            x_center = x_map(point_index + offset)
            x1 = x_map(point_index + offset - half)
            x2 = x_map(point_index + offset + half)
            y = y_map(point["G"])
            path_y.append(y)
            if chemdraw_objects == "bonds":
                left_id, left_node = _node(
                    ids, x1, y, z_base + point_index
                )
                right_id, right_node = _node(
                    ids, x2, y, z_base + point_index
                )
                bond_nodes.extend((left_node, right_node))
                state_nodes.append((left_id, right_id))
                bond_children.append(_bond(
                    ids, left_id, right_id, z_base + point_index,
                    color_index, display="Bold"
                ))
            else:
                line_children.append(_line_pair(
                    ids, x1, y, x2, y, z_base + point_index,
                    color_index, width=state_width, bold=True
                ))

            if show_values:
                text_objects.append(_text(
                    ids, value_format % float(point["G"]), x_center, y - 10,
                    300 + path_index * 10 + point_index, color_index,
                    max(8, tag_size - 2), bold=True
                ))
            if show_tags and point.get("name"):
                text_objects.append(_text(
                    ids, point["name"], x_center, y + max(14, tag_size + 3),
                    300 + path_index * 10 + point_index, gray_text,
                    tag_size, bold=True
                ))

        for point_index in range(len(points) - 1):
            x1 = x_map(point_index + offset + half)
            x2 = x_map(point_index + 1 + offset - half)
            y1 = y_map(points[point_index]["G"])
            y2 = y_map(points[point_index + 1]["G"])
            z = 95 + path_index * 20 + point_index
            if chemdraw_objects == "bonds":
                begin_id = state_nodes[point_index][1]
                end_id = state_nodes[point_index + 1][0]
                bond_children.append(_bond(
                    ids, begin_id, end_id, z, color_index,
                    display="Dash" if connector_dashed else None
                ))
            else:
                line_children.append(_line_pair(
                    ids, x1, y1, x2, y2, z, color_index,
                    width=connector_width, dashed=connector_dashed
                ))

        first_x = x_map(offset - half)
        last_x = x_map(offset + len(points) - 1 + half)
        bbox = (first_x, min(path_y), last_x, max(path_y))
        if chemdraw_objects == "bonds":
            path_children = [
                _fragment(
                    ids, bond_children + bond_nodes,
                    90 + path_index * 20, bbox
                )
            ]
        else:
            path_children = line_children
        objects.append(_group(
            ids, path_children, 90 + path_index * 20, bbox=bbox,
            integral=True
        ))

    if show_span:
        tdi_data_index = int(result["TDI_idx"])
        tdts_data_index = int(result["TDTS_idx"])
        if tdi_data_index >= len(species) or tdts_data_index >= len(species):
            raise ValueError("TDI/TDTS index is outside the species list")

        tdi_x = x_map(tdi_data_index)
        tdi_y = y_map(species[tdi_data_index]["G"])
        if result.get("needCycle2") and len(paths) > 1:
            target_x = x_map(tdts_data_index + cycle1_len)
            target_y = y_map(paths[1]["data"][tdts_data_index]["G"])
        else:
            target_x = x_map(tdts_data_index)
            target_y = y_map(species[tdts_data_index]["G"])

        span_children = [
            _line_pair(
                ids, tdi_x, tdi_y, target_x, tdi_y, 180,
                gray_text, width=max(0.8, connector_width * 0.7), dashed=True
            ),
            _line_pair(
                ids, target_x, target_y, target_x, tdi_y, 180,
                gray_text, width=max(0.8, connector_width * 0.7), dashed=True
            ),
        ]
        # ChemDraw line objects are used for the arrow head as well.  This
        # keeps every part of the span marker individually editable.
        arrow_size = 7.0
        direction = -1.0 if tdi_y <= target_y else 1.0
        span_children.extend([
            _line_pair(
                ids, target_x, tdi_y,
                target_x - arrow_size * 0.75,
                tdi_y - direction * arrow_size,
                181, gray_text, width=1.4
            ),
            _line_pair(
                ids, target_x, tdi_y,
                target_x + arrow_size * 0.75,
                tdi_y - direction * arrow_size,
                181, gray_text, width=1.4
            ),
        ])
        objects.append(_group(
            ids, span_children, 170,
            bbox=(
                min(tdi_x, target_x) - arrow_size,
                min(tdi_y, target_y),
                max(tdi_x, target_x) + arrow_size,
                max(tdi_y, target_y) + 10,
            ),
            integral=True
        ))
        text_objects.append(_text(
            ids, "δE = " + value_format % float(result["deltaE"]),
            (tdi_x + target_x) / 2.0, tdi_y - 12, 330, gray_text,
            max(10, tag_size), bold=True
        ))

    # Text is appended last so it stays above the lines in ChemDraw.
    objects.extend(item for item in text_objects if item)
    return _document_objects(
        objects, page_width, page_height, filename, colors, ids.next()
    )


def write_energy_diagram_cdxml(path, species, result, **options):
    """Write an editable CDXML file atomically and return its path."""
    path = os.fspath(path)
    if not path.lower().endswith(".cdxml"):
        path += ".cdxml"
    xml = build_energy_diagram_cdxml(
        species, result, filename=os.path.basename(path), **options
    )
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    temporary = path + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(xml)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return path
