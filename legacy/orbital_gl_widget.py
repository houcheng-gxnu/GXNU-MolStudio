"""
OpenGL Orbital Renderer — QOpenGLWidget with Depth Peeling
===========================================================
Based on IboView (c) 2015 Gerald Knizia, GPLv3 — modified.
Contains a verbatim port of IboView's covalent-radii table (g_CovalentRadii)
and shader-derived code (via glsl_shaders); distributed under the GNU GPLv3
as part of a derivative work of IboView.

Replaces VMD for orbital visualization. Features:
  - IboView-inspired three-directional Phong lighting
  - Depth peeling for correct transparency ordering
  - Arcball rotation (quaternion-based)
  - Style system integration (vcube2.0 STYLES)
  - Atom sphere rendering
  - Zoom, pan, and screenshot support
"""

import ctypes
import numpy as np
from collections import namedtuple

from PyQt5.QtWidgets import QOpenGLWidget, QWidget
from PyQt5.QtCore import Qt, QPoint, QSize
from PyQt5.QtGui import (
    QMouseEvent, QWheelEvent, QImage, QPainter, QSurfaceFormat,
)

from PyQt5.QtOpenGL import QGLContext  # kept for compat if needed

try:
    from OpenGL.GL import *
    from OpenGL.GLU import *
    _HAS_OPENGL = True
except ImportError:
    _HAS_OPENGL = False

from glsl_shaders import (
    VERTEX_SHADER, FRAGMENT_OPAQUE, FRAGMENT_ORBITAL_DP,
    FRAGMENT_COMPOSITE, FRAGMENT_ATOM, FULLSCREEN_VERTEX,
    style_to_shader_params, parse_style_rgb,
)
from marching_cubes import (
    read_cube, marching_cubes, IsoSurface, CubeData,
    compute_bounding_sphere,
)

try:
    from fchk_orbital import ELEMENT_SYMBOLS
except ImportError:
    ELEMENT_SYMBOLS = None

# ── GaussView element color scheme (from gview_color.tcl) ──
# GaussView exchanges colors via palette slots 101..211 (Z = slot - 101).
# The `color change rgb NNN r g b` entries use a 0..1000 range; we divide by
# 1000 to get linear 0..1 RGB. Default bond color in GaussView is black.
_GVIEW_PALETTE = {
    101: (145, 110,  90), 102: (190, 190, 190), 103: (255, 140,  40),
    104: (255, 200, 150), 105: (255, 190,  90), 106: ( 90,  90,  90),
    107: ( 30,  90, 255), 108: (255,  25,  25), 109: (120, 255, 120),
    110: (240, 230, 240), 111: (200,  20, 200), 112: (160,  80, 100),
    113: (190, 190, 190), 114: (240, 200, 160), 115: (255, 160,  60),
    116: (255, 230,  40), 117: ( 30, 255,  30), 118: (100, 100, 255),
    119: (220, 130, 220), 120: (160,  80, 100), 121: (150, 150, 150),
    122: (150, 150, 150), 123: (150, 150, 150), 124: ( 90, 150, 240),
    125: (150, 120, 200), 126: (110, 170, 220), 127: (110, 170, 220),
    128: (110, 170, 220), 129: (120, 190, 230), 130: (120, 190, 230),
    131: (120, 190, 230), 132: (120, 190, 230), 133: (120, 190, 230),
    134: (120, 190, 230), 135: (120, 190, 230), 136: (120, 190, 230),
    137: (120, 190, 230), 138: (120, 190, 230), 139: (120, 190, 230),
    140: (120, 190, 230), 141: (120, 190, 230), 142: (120, 190, 230),
    143: (120, 190, 230), 144: (120, 190, 230), 145: (120, 190, 230),
    146: (120, 190, 230), 147: (120, 190, 230), 148: (120, 190, 230),
    149: (120, 190, 230), 150: (120, 190, 230), 151: (120, 190, 230),
    152: (120, 190, 230), 153: (120, 190, 230), 154: (120, 190, 230),
    155: (120, 190, 230), 156: (120, 190, 230), 157: (120, 190, 230),
    158: (120, 190, 230), 159: (120, 190, 230), 160: (120, 190, 230),
    161: (120, 190, 230), 162: (120, 190, 230), 163: (120, 190, 230),
    164: (120, 190, 230), 165: (120, 190, 230), 166: (120, 190, 230),
    167: (120, 190, 230), 168: (120, 190, 230), 169: (120, 190, 230),
    170: (120, 190, 230), 171: (120, 190, 230), 172: (120, 190, 230),
    173: (120, 190, 230), 174: (120, 190, 230), 175: (120, 190, 230),
    176: (120, 190, 230), 177: (120, 190, 230), 178: (120, 190, 230),
    179: (120, 190, 230), 180: (120, 190, 230), 181: (120, 190, 230),
    182: (120, 190, 230), 183: (120, 190, 230), 184: (120, 190, 230),
    185: (120, 190, 230), 186: (120, 190, 230), 187: (120, 190, 230),
    188: (120, 190, 230), 189: (120, 190, 230), 190: (120, 190, 230),
    191: (120, 190, 230), 192: (120, 190, 230), 193: (120, 190, 230),
    194: (120, 190, 230), 195: (120, 190, 230), 196: (120, 190, 230),
    197: (120, 190, 230), 198: (120, 190, 230), 199: (120, 190, 230),
    200: (120, 190, 230), 201: (120, 190, 230), 202: (120, 190, 230),
    203: (120, 190, 230), 204: (120, 190, 230), 205: (120, 190, 230),
    206: (120, 190, 230), 207: (120, 190, 230), 208: (120, 190, 230),
    209: (120, 190, 230), 210: (120, 190, 230), 211: (120, 190, 230),
}
# Map atomic number (Z = slot - 100) -> (r,g,b) in 0..1
GVIEW_ELEMENT_COLORS = {
    (slot - 100): (r / 1000.0, g / 1000.0, b / 1000.0)
    for slot, (r, g, b) in _GVIEW_PALETTE.items()
}
# Fallback for unknown elements
GVIEW_FALLBACK = (0.5, 0.5, 0.5)
# GaussView default bond color
GVIEW_BOND_COLOR = (0.0, 0.0, 0.0)

# ── IboView covalent radii (Bohr), g_CovalentRadii ──
# Used by bond detection together with the (Bohr) cube atom coordinates so the
# comparison is unit-consistent. BondRadiusFactor defaults to 1.3 in IboView.
_BOHR_TO_ANGSTROM = 0.529177
_COVALENT_RADII_BOHR = [
    0.0, 0.7181, 0.6047, 2.5322, 1.7008, 1.5496, 1.4551, 1.4173, 1.3795,
    1.3417, 1.3039, 2.9102, 2.4566, 2.2299, 2.0976, 2.0031, 1.9275, 1.8708,
    1.8330, 3.7039, 3.2881, 2.7212, 2.5700, 2.3622, 2.4000, 2.6267, 2.3622,
    2.3811, 2.2866, 2.6078, 2.4755, 2.3811, 2.3055, 2.2488, 2.1921, 2.1543,
    2.0787, 3.9873, 3.6283, 3.0614, 2.7968, 2.5889, 2.7401, 2.9480, 2.3811,
    2.5511, 2.4755, 2.8913, 2.7968, 2.7212, 2.6645, 2.6078, 2.5511, 2.5133,
    2.4566, 4.2519, 3.7417, 3.1936, 3.4355, 3.4469, 3.4280, 3.4658, 3.4091,
    3.4091, 3.4091, 3.3505, 3.3656, 3.3297, 3.3278, 3.3240, 3.3259, 3.0236,
    2.8346, 2.6078, 2.7590, 3.0047, 2.7188, 2.5889, 2.7188, 2.7212, 2.8157,
    2.7968, 2.7779, 2.7590, 2.8300, 2.9200, 2.7401, 5.4400, 4.7500, 3.7500,
    3.3826, 3.0803, 2.9480, 2.9291, 3.0047, 3.2692, 3.2881, 3.2125, 3.5149,
    3.5149, 3.2400, 3.1900, 3.1700, 3.2100, 3.2000, 3.2000, 3.2000, 3.2000,
    3.2000, 3.2000, 3.2000, 3.2000, 3.2000, 3.2000, 3.2000, 3.2000, 3.2000,
    3.2000, 3.2000, 3.2000, 3.2000, 3.2000, 3.2000, 3.2000, 3.2000, 3.2000,
    3.2000,
]

# IboView default bond-radius heuristic factor
BOND_RADIUS_FACTOR = 1.3


# ── Shader Compilation Helpers ─────────────────────────────

def _compile_shader(src, shader_type):
    """Compile a single shader, return shader object ID."""
    shader = glCreateShader(shader_type)
    glShaderSource(shader, src)
    glCompileShader(shader)
    if not glGetShaderiv(shader, GL_COMPILE_STATUS):
        log = glGetShaderInfoLog(shader).decode('utf-8', errors='replace')
        raise RuntimeError(f"Shader compile error:\n{log}")
    return shader


def _link_program(*shaders):
    """Link multiple shaders into a program, return program ID."""
    prog = glCreateProgram()
    for s in shaders:
        glAttachShader(prog, s)
    glLinkProgram(prog)
    if not glGetProgramiv(prog, GL_LINK_STATUS):
        log = glGetProgramInfoLog(prog).decode('utf-8', errors='replace')
        raise RuntimeError(f"Program link error:\n{log}")
    for s in shaders:
        glDetachShader(prog, s)
        glDeleteShader(s)
    return prog


# ── GPU Mesh ───────────────────────────────────────────────

class GlMesh:
    """VAO/VBO/EBO wrapper for a triangle mesh."""
    def __init__(self):
        self.vao = 0
        self.vbo_pos = 0
        self.vbo_norm = 0
        self.vbo_color = 0
        self.ebo = 0
        self.index_count = 0
        self.vertex_count = 0

    def upload(self, surface: IsoSurface):
        """Upload IsoSurface data to GPU buffers."""
        if surface.vertex_count == 0:
            return

        self.vertex_count = surface.vertex_count
        self.index_count = len(surface.indices)

        # Create VAO
        self.vao = glGenVertexArrays(1)
        glBindVertexArray(self.vao)

        # Positions (location=0)
        self.vbo_pos = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo_pos)
        glBufferData(GL_ARRAY_BUFFER, surface.vertices.nbytes,
                     surface.vertices, GL_STATIC_DRAW)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, None)
        glEnableVertexAttribArray(0)

        # Normals (location=1)
        if surface.normals is not None:
            self.vbo_norm = glGenBuffers(1)
            glBindBuffer(GL_ARRAY_BUFFER, self.vbo_norm)
            glBufferData(GL_ARRAY_BUFFER, surface.normals.nbytes,
                         surface.normals, GL_STATIC_DRAW)
            glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 0, None)
            glEnableVertexAttribArray(1)

        # Colors (location=2)
        if surface.colors is not None:
            self.vbo_color = glGenBuffers(1)
            glBindBuffer(GL_ARRAY_BUFFER, self.vbo_color)
            glBufferData(GL_ARRAY_BUFFER, surface.colors.nbytes,
                         surface.colors, GL_STATIC_DRAW)
            glVertexAttribPointer(2, 4, GL_FLOAT, GL_FALSE, 0, None)
            glEnableVertexAttribArray(2)

        # Element indices
        if self.index_count > 0:
            self.ebo = glGenBuffers(1)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo)
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, surface.indices.nbytes,
                         surface.indices, GL_STATIC_DRAW)

        glBindVertexArray(0)

    def draw(self):
        """Draw the mesh (assumes shader program is already active)."""
        if self.vao == 0 or self.index_count == 0:
            return
        glBindVertexArray(self.vao)
        glDrawElements(GL_TRIANGLES, self.index_count, GL_UNSIGNED_INT, None)
        glBindVertexArray(0)

    def destroy(self):
        if self.vao:
            glDeleteVertexArrays(1, [self.vao])
        if self.vbo_pos:
            glDeleteBuffers(1, [self.vbo_pos])
        if self.vbo_norm:
            glDeleteBuffers(1, [self.vbo_norm])
        if self.vbo_color:
            glDeleteBuffers(1, [self.vbo_color])
        if self.ebo:
            glDeleteBuffers(1, [self.ebo])
        self.vao = 0


def make_cylinder(radius=1.0, height=1.0, seg=18):
    """Unit (open) cylinder along +Y, base at y=0, top at y=height.

    Returns (positions[N,3], normals[N,3]) in the local frame; the caller
    applies a rigid transform to place/orient the bond.  Normals point
    radially outward.
    """
    ring = []
    for k in range(seg):
        a = 2.0 * np.pi * k / seg
        ring.append((np.cos(a), np.sin(a)))
    ring.append(ring[0])
    pos = []
    nrm = []
    # side walls
    for k in range(len(ring) - 1):
        c0 = ring[k]
        c1 = ring[k + 1]
        y0 = 0.0
        y1 = height
        # four corners of the quad
        p00 = (c0[0] * radius, y0, c0[1] * radius)
        p10 = (c1[0] * radius, y0, c1[1] * radius)
        p11 = (c1[0] * radius, y1, c1[1] * radius)
        p01 = (c0[0] * radius, y1, c0[1] * radius)
        n00 = (c0[0], 0.0, c0[1])
        n10 = (c1[0], 0.0, c1[1])
        n11 = (c1[0], 0.0, c1[1])
        n01 = (c0[0], 0.0, c0[1])
        pos += [p00, p10, p11, p00, p11, p01]
        nrm += [n00, n10, n11, n00, n11, n01]
    return np.array(pos, dtype=np.float64), np.array(nrm, dtype=np.float64)


def make_dashed_bond_geometry(p, q, bond_r, n_segments=0, dash_weight=0.4,
                               seg=12):
    """Generate dashed/dotted bond geometry between two 3D points.

    Ported from IboView's DrawBond1 / RenderHalfBond: instead of a single
    continuous cylinder, the bond is drawn as a series of short cylinder
    segments placed along the p→q vector with gaps between them.

    Parameters
    ----------
    p, q : ndarray of shape (3,) — start / end positions (Bohr).
    bond_r : float — cylinder radius.
    n_segments : int — number of dash segments; 0 = auto (derived from length).
    dash_weight : float — 0..1, fill ratio (1.0 = solid, 0.4 = IboView default
                   dotted bond).
    seg : int — tessellation of each cylinder cross-section.

    Returns
    -------
    (verts, norms) — concatenated vertex + normal arrays ready to be
    transformed into world space by the caller.
    """
    d = q - p
    length = float(np.linalg.norm(d))
    if length < 1e-4:
        return np.zeros((0, 3)), np.zeros((0, 3))

    # IboView's dot-weight mapping: fBondDotWeightTrafo4(x) = 1 - (1-x)²
    dot_weight = 1.0 - (1.0 - dash_weight) ** 2

    if n_segments <= 0:
        n_segments = max(2, int(np.floor(1.0 + length / 0.5)))

    dot_scale = 1.0 - dot_weight           # gap fraction
    seg_h = length / (n_segments - dot_scale / 2.0)
    seg_len = (1.0 - dot_scale) * seg_h    # length of each solid segment
    gap = seg_len / (1.0 - dot_scale) - seg_len  # gap between segments

    y_axis = np.array([0.0, 1.0, 0.0])
    seg_v = d / length
    axis = np.cross(y_axis, seg_v)
    s = np.linalg.norm(axis)
    if s < 1e-9:
        R = np.eye(3, dtype=np.float64) if np.dot(y_axis, seg_v) > 0 else -np.eye(3)
    else:
        axis /= s
        cth = float(np.dot(y_axis, seg_v))
        skew = np.array([[0, -axis[2], axis[1]],
                         [axis[2], 0, -axis[0]],
                         [-axis[1], axis[0], 0]])
        R = np.eye(3) + skew + skew @ skew * ((1.0 - cth) / (s * s))

    verts_list = []
    norms_list = []

    for i in range(n_segments):
        t = (i / (n_segments - 0.5)) if n_segments > 1 else 0.0
        start_t = t - seg_len / length * 0.5
        if start_t < 0.0:
            start_t = 0.0
        # Build a short unit-height cylinder, then scale and place it
        cv, cn = make_cylinder(radius=1.0, height=1.0, seg=seg)
        S = np.diag([bond_r, seg_len, bond_r])
        T = R @ S
        # Transform to world space: position at the segment's start point
        seg_start = p + seg_v * (start_t * length)
        cv = cv @ T.T + seg_start
        cn = cn @ R.T
        verts_list.append(cv)
        norms_list.append(cn)

    if not verts_list:
        return np.zeros((0, 3)), np.zeros((0, 3))
    return np.vstack(verts_list), np.vstack(norms_list)


# ── Fullscreen Quad ────────────────────────────────────────

def _create_fullscreen_quad():
    """Create a fullscreen quad VAO for composite passes."""
    verts = np.array([
        -1.0, -1.0,  0.0, 0.0,
         1.0, -1.0,  1.0, 0.0,
         1.0,  1.0,  1.0, 1.0,
        -1.0,  1.0,  0.0, 1.0,
    ], dtype=np.float32)
    indices = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)

    vao = glGenVertexArrays(1)
    glBindVertexArray(vao)

    vbo = glGenBuffers(1)
    glBindBuffer(GL_ARRAY_BUFFER, vbo)
    glBufferData(GL_ARRAY_BUFFER, verts.nbytes, verts, GL_STATIC_DRAW)
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 16, None)
    glEnableVertexAttribArray(0)
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 16, ctypes.c_void_p(8))
    glEnableVertexAttribArray(1)

    ebo = glGenBuffers(1)
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo)
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)

    glBindVertexArray(0)
    return vao, 6


# ── Atom Sphere Generator ─────────────────────────────────

def _make_sphere_mesh(radius=1.0, subdivisions=2):
    """Generate an icosahedron-based sphere mesh (like IboView's MakeSubdivSphere)."""
    # Start with icosahedron
    t = (1.0 + np.sqrt(5.0)) / 2.0
    verts = np.array([
        [-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0],
        [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
        [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1],
    ], dtype=np.float64)

    faces = np.array([
        [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
        [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
        [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
        [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1],
    ], dtype=np.int32)

    # Subdivide
    for _ in range(subdivisions):
        new_faces = []
        edge_mid = {}
        for face in faces:
            v0, v1, v2 = face
            # Get midpoints
            mids = []
            for a, b in [(v0, v1), (v1, v2), (v2, v0)]:
                key = (min(a, b), max(a, b))
                if key not in edge_mid:
                    mid = verts[a] + verts[b]
                    mid /= np.linalg.norm(mid)
                    idx = len(verts)
                    verts = np.vstack([verts, mid])
                    edge_mid[key] = idx
                mids.append(edge_mid[key])
            m01, m12, m20 = mids
            new_faces.extend([
                [v0, m01, m20],
                [v1, m12, m01],
                [v2, m20, m12],
                [m01, m12, m20],
            ])
        faces = np.array(new_faces, dtype=np.int32)

    # Normalize and scale
    verts = verts / np.linalg.norm(verts, axis=1, keepdims=True) * radius

    # Build flattened arrays for GPU
    v_array = verts.astype(np.float32)
    n_array = v_array / radius  # normals = normalized positions for sphere
    indices = faces.astype(np.uint32).flatten()

    return v_array, n_array, indices


# ── Arcball Camera ─────────────────────────────────────────

class ArcballCamera:
    """Quaternion-based arcball rotation camera."""
    def __init__(self):
        self.rotation = np.array([0.0, 0.0, 0.0, 1.0])  # quaternion (x,y,z,w)
        self.translation = np.array([0.0, 0.0, 0.0])
        self.zoom = 1.0
        self.center = np.array([0.0, 0.0, 0.0])
        self._last_pos = None
        self._dragging = False

    def begin_drag(self, x, y, width, height):
        self._last_pos = (x, y)
        self._drag_sphere = self._map_to_sphere(x, y, width, height)
        self._dragging = True

    def drag(self, x, y, width, height, pan=False):
        if not self._dragging or self._last_pos is None:
            return
        if pan:
            dx = (x - self._last_pos[0]) / width * 2.0
            dy = -(y - self._last_pos[1]) / height * 2.0
            self.translation[0] += dx * 2.0 / self.zoom
            self.translation[1] += dy * 2.0 / self.zoom
        else:
            curr = self._map_to_sphere(x, y, width, height)
            # quaternion from drag
            q = self._quat_from_vectors(self._drag_sphere, curr)
            self.rotation = self._quat_mult(q, self.rotation)
            self._drag_sphere = curr
        self._last_pos = (x, y)

    def end_drag(self):
        self._dragging = False
        self._last_pos = None

    def zoom_by(self, delta):
        self.zoom *= (1.0 + delta * 0.001)
        self.zoom = max(0.01, min(self.zoom, 100.0))

    def get_view_matrix(self):
        """Return 4x4 modelview matrix from camera state."""
        # Build rotation matrix from quaternion
        rot_mat = self._quat_to_matrix(self.rotation)

        # Build full 4x4
        mat = np.eye(4, dtype=np.float32)
        mat[:3, :3] = rot_mat
        mat[0, 3] = self.translation[0]
        mat[1, 3] = self.translation[1]
        mat[2, 3] = self.translation[2] - 3.0 / self.zoom

        # Translate to center
        t_mat = np.eye(4, dtype=np.float32)
        t_mat[0, 3] = -self.center[0]
        t_mat[1, 3] = -self.center[1]
        t_mat[2, 3] = -self.center[2]

        return mat @ t_mat

    def get_normal_matrix(self):
        """Return 3x3 normal matrix (inverse transpose of upper-left of view)."""
        view = self.get_view_matrix()
        n = view[:3, :3]
        return np.linalg.inv(n).T.astype(np.float32)

    def reset(self):
        self.rotation = np.array([0.0, 0.0, 0.0, 1.0])
        self.translation = np.array([0.0, 0.0, 0.0])
        self.zoom = 1.0

    @staticmethod
    def _map_to_sphere(x, y, w, h):
        v = np.array([
            (2.0 * x - w) / w,
            (h - 2.0 * y) / h,
            0.0
        ])
        d = np.linalg.norm(v)
        if d < 1.0:
            v[2] = np.sqrt(1.0 - d * d)
        else:
            v /= d
        return v

    @staticmethod
    def _quat_from_vectors(v0, v1):
        """Quaternion rotating v0 to v1."""
        cross = np.cross(v0, v1)
        dot = np.dot(v0, v1)
        q = np.array([cross[0], cross[1], cross[2], 1.0 + dot])
        return q / np.linalg.norm(q)

    @staticmethod
    def _quat_mult(q1, q2):
        x1, y1, z1, w1 = q1
        x2, y2, z2, w2 = q2
        return np.array([
            w1*x2 + x1*w2 + y1*z2 - z1*y2,
            w1*y2 - x1*z2 + y1*w2 + z1*x2,
            w1*z2 + x1*y2 - y1*x2 + z1*w2,
            w1*w2 - x1*x2 - y1*y2 - z1*z2,
        ])

    @staticmethod
    def _quat_to_matrix(q):
        x, y, z, w = q
        xx, yy, zz = x*x, y*y, z*z
        xy, xz, yz = x*y, x*z, y*z
        wx, wy, wz = w*x, w*y, w*z
        return np.array([
            [1 - 2*(yy + zz),     2*(xy - wz),     2*(xz + wy)],
            [    2*(xy + wz), 1 - 2*(xx + zz),     2*(yz - wx)],
            [    2*(xz - wy),     2*(yz + wx), 1 - 2*(xx + yy)],
        ], dtype=np.float32)


# ── Main OpenGL Widget ─────────────────────────────────────

class OrbitalGLWidget(QOpenGLWidget):
    """Interactive OpenGL widget for orbital visualization with depth peeling."""

    DEPTH_PEEL_LAYERS = 4
    MIN_LAYERS = 2

    def __init__(self, parent=None):
        super().__init__(parent)

        if not _HAS_OPENGL:
            return

        # Set OpenGL format
        fmt = QSurfaceFormat()
        fmt.setSamples(0)  # we handle anti-aliasing ourselves
        fmt.setDepthBufferSize(24)
        fmt.setStencilBufferSize(0)
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.CoreProfile)
        self.setFormat(fmt)

        self.setMinimumSize(300, 200)
        self.setMouseTracking(True)

        # Camera
        self.camera = ArcballCamera()

        # Meshes
        self.mesh_pos = GlMesh()
        self.mesh_neg = GlMesh()
        self.mesh_atoms = GlMesh()
        self.mesh_bonds = GlMesh()

        # Ball-and-stick display scales (user-adjustable via sliders)
        self._atom_scale = 2.0   # multiplies base atom radius (default 2.0×)
        self._bond_scale = 1.8   # multiplies base bond radius (default 1.8×)

        # Bond radius factor — dual-threshold for solid / dashed / no-bond
        # Ported from IboView: bonds with rij <= rf_tight * (cov_i+cov_j) are
        # solid; bonds with rf_tight < rij <= rf_loose * (cov_i+cov_j) are
        # dashed (BOND_Partial). Defaults match IboView's BondRadiusFactor=1.3.
        self._bond_rf_tight = 1.0   # ≤ this → solid bond
        self._bond_rf_loose = 1.3   # ≤ this → dashed bond; > this → no bond
        self._dash_weight = 0.4     # fill ratio for dashed bonds (0..1)

        # Atom data (for per-atom coloring)
        self._atom_positions = None  # (N,3)
        self._atom_colors = None     # (N,3)
        self._atom_radii = None       # (N,)

        # Style settings
        self._style_params = {
            'ShaderReg0': 1.5, 'ShaderReg1': 0.55, 'ShaderReg2': 1.0,
            'ShaderReg3': 1.0, 'FadeBias': 0.2, 'FadeWidth': 6.0,
            'opacity': 0.7,
        }
        self._pos_color = (0.1, 0.8, 0.1)
        self._neg_color = (0.9, 0.25, 0.25)
        self._bg_color = (0.15, 0.15, 0.15, 1.0)

        # OpenGL resources (created in initializeGL)
        self._initialized = False
        self._prog_orbital = 0      # orbital depth peel shader
        self._prog_composite = 0     # composite shader
        self._prog_atom = 0          # atom shader
        self._prog_fullscreen = 0    # fullscreen quad shader
        self._fsq_vao = 0
        self._fsq_count = 0

        # FBOs for depth peeling
        self._dp_fbos = []           # list of (fbo, color_tex, depth_tex)
        self._acc_fbo = 0
        self._acc_color = 0
        self._acc_depth = 0
        self._fbo_width = 0
        self._fbo_height = 0

        # Current data
        self._pos_surface = None
        self._neg_surface = None
        self._cube_data = None
        self._isovalue = 0.05

        # Interactive atom/bond picking & override system (IboView context-menu)
        self._bond_overrides = {}   # {(i,j): 'solid'|'dashed'|'none'}
        self._selected_atoms = []   # indices of currently selected atoms
        self._drag_start = None     # (x, y) of mouse press for click-vs-drag
        self._was_drag = False
        self._phase_colors_dirty = False

    # ── Public API ────────────────────────────────────────

    def load_cube_file(self, cube_path, isovalue=None):
        """Load orbital data from a cube file and generate isosurfaces."""
        if not _HAS_OPENGL:
            return

        if isovalue is not None:
            self._isovalue = isovalue

        cube = read_cube(cube_path)
        self._cube_data = cube

        pos = marching_cubes(cube, self._isovalue, flip_normal=False)
        neg = marching_cubes(cube, -self._isovalue, flip_normal=True)

        # Set colors
        pc = np.array([*self._pos_color, 1.0], dtype=np.float32)
        nc = np.array([*self._neg_color, 1.0], dtype=np.float32)
        pos.colors = np.tile(pc, (pos.vertex_count, 1))
        neg.colors = np.tile(nc, (neg.vertex_count, 1))

        self._pos_surface = pos
        self._neg_surface = neg

        # Generate atom meshes
        self._gen_atom_mesh()

        # Center camera
        center, radius = compute_bounding_sphere(cube)
        self.camera.center = center
        self.camera.zoom = 3.0 / max(radius, 0.01)

        # Upload to GPU (defer to paintGL if context not ready yet)
        if self._initialized:
            self.makeCurrent()
            self._upload_meshes()
            self.doneCurrent()
        else:
            self._phase_colors_dirty = True

        self.update()

    def set_isovalue(self, value):
        """Change isovalue and regenerate surfaces."""
        if abs(self._isovalue - value) < 1e-6 or self._cube_data is None:
            return
        self._isovalue = value

        pos = marching_cubes(self._cube_data, value, flip_normal=False)
        neg = marching_cubes(self._cube_data, -value, flip_normal=True)

        pc = np.array([*self._pos_color, 1.0], dtype=np.float32)
        nc = np.array([*self._neg_color, 1.0], dtype=np.float32)
        pos.colors = np.tile(pc, (pos.vertex_count, 1))
        neg.colors = np.tile(nc, (neg.vertex_count, 1))

        self._pos_surface = pos
        self._neg_surface = neg

        if self._initialized:
            self.makeCurrent()
            self._upload_meshes()
            self.doneCurrent()
        else:
            self._phase_colors_dirty = True
        self.update()

    def set_style(self, style_name, styles_dict=None):
        """Apply a style from the STYLES dictionary."""
        if styles_dict is None:
            from fchk_orbital import STYLES as styles_dict

        style = styles_dict.get(style_name)
        if style is None:
            return

        # Parse shader params
        sm = style.get('surface_mat')
        if sm:
            self._style_params = style_to_shader_params(sm)

        self._style_params['opacity'] = sm[5] if sm else 0.7

        # Parse colors
        pc = parse_style_rgb(style.get('pos_color', []))
        nc = parse_style_rgb(style.get('neg_color', []))
        if pc:
            self._pos_color = pc
        if nc:
            self._neg_color = nc

        # Recolor existing surfaces
        if self._pos_surface and pc:
            c = np.array([*pc, 1.0], dtype=np.float32)
            self._pos_surface.colors = np.tile(c, (self._pos_surface.vertex_count, 1))
        if self._neg_surface and nc:
            c = np.array([*nc, 1.0], dtype=np.float32)
            self._neg_surface.colors = np.tile(c, (self._neg_surface.vertex_count, 1))

        self.makeCurrent()
        self._upload_meshes()
        self.doneCurrent()
        self.update()

    def set_opacity(self, value):
        """Set surface opacity (0.0 - 1.0)."""
        self._style_params['opacity'] = max(0.0, min(1.0, value))
        self.update()

    def set_phase_colors(self, pos_rgb=None, neg_rgb=None):
        """设置正/负相位等值面颜色（RGB 0-255 元组，None 表示保持当前）。

        仅更新 CPU 端颜色并标记脏，推迟到下一帧 paintGL（在有效 GL
        上下文内）重新上传 GPU 顶点色，避免在信号回调里直接 makeCurrent
        触发原生崩溃（未初始化上下文时会 segfault 导致程序闪退）。
        """
        if pos_rgb is not None:
            self._pos_color = tuple(c / 255.0 for c in pos_rgb)
        if neg_rgb is not None:
            self._neg_color = tuple(c / 255.0 for c in neg_rgb)
        if self._pos_surface and pos_rgb is not None:
            c = np.array([*self._pos_color, 1.0], dtype=np.float32)
            self._pos_surface.colors = np.tile(c, (self._pos_surface.vertex_count, 1))
        if self._neg_surface and neg_rgb is not None:
            c = np.array([*self._neg_color, 1.0], dtype=np.float32)
            self._neg_surface.colors = np.tile(c, (self._neg_surface.vertex_count, 1))
        self._phase_colors_dirty = True
        self.update()

    def set_background_color(self, r, g, b):
        self._bg_color = (r, g, b, 1.0)
        self.update()

    def reset_view(self):
        self.camera.reset()
        if self._cube_data:
            center, radius = compute_bounding_sphere(self._cube_data)
            self.camera.center = center
            self.camera.zoom = 3.0 / max(radius, 0.01)
        self.update()

    def grab_image(self, width=None, height=None):
        """Render to an offscreen image and return QImage."""
        self.makeCurrent()
        w = width or self.width()
        h = height or self.height()

        self._ensure_fbos(w, h)
        self._render_scene(w, h)

        # Read accumulation buffer
        glBindFramebuffer(GL_READ_FRAMEBUFFER, self._acc_fbo)
        data = glReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE)
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0)

        image = QImage(data, w, h, QImage.Format_RGBA8888)
        image = image.mirrored(False, True)  # OpenGL origin is bottom-left

        self.doneCurrent()
        return image

    # ── OpenGL Lifecycle ──────────────────────────────────

    def initializeGL(self):
        if not _HAS_OPENGL:
            return

        glClearColor(*self._bg_color)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_CULL_FACE)
        glCullFace(GL_BACK)

        # Compile shaders
        vs = _compile_shader(VERTEX_SHADER, GL_VERTEX_SHADER)
        fs_orb = _compile_shader(FRAGMENT_ORBITAL_DP, GL_FRAGMENT_SHADER)
        self._prog_orbital = _link_program(vs, fs_orb)

        vs2 = _compile_shader(VERTEX_SHADER, GL_VERTEX_SHADER)
        fs_atom = _compile_shader(FRAGMENT_ATOM, GL_FRAGMENT_SHADER)
        self._prog_atom = _link_program(vs2, fs_atom)

        vs_fs = _compile_shader(FULLSCREEN_VERTEX, GL_VERTEX_SHADER)
        fs_comp = _compile_shader(FRAGMENT_COMPOSITE, GL_FRAGMENT_SHADER)
        self._prog_composite = _link_program(vs_fs, fs_comp)

        vs_fs2 = _compile_shader(FULLSCREEN_VERTEX, GL_VERTEX_SHADER)
        fs_bg = _compile_shader("""
            #version 330 core
            in vec2 v_TexCoord;
            layout(location=0) out vec4 out_Color;
            uniform vec4 u_BgColor;
            void main() { out_Color = u_BgColor; }
        """, GL_FRAGMENT_SHADER)
        self._prog_fullscreen = _link_program(vs_fs2, fs_bg)

        # Fullscreen quad
        self._fsq_vao, self._fsq_count = _create_fullscreen_quad()

        self._initialized = True

    def resizeGL(self, w, h):
        if not _HAS_OPENGL or not self._initialized:
            return
        glViewport(0, 0, w, h)
        self._fbo_width = 0  # force FBO recreation
        self._fbo_height = 0

    def paintGL(self):
        if not _HAS_OPENGL or not self._initialized:
            return

        w = self.width() * self.devicePixelRatio()
        h = self.height() * self.devicePixelRatio()
        w = max(1, int(w))
        h = max(1, int(h))

        self._ensure_fbos(w, h)

        # 色轮改色：在有效 GL 上下文内重新上传顶点色（避免信号回调中崩溃）
        if self._phase_colors_dirty:
            self._phase_colors_dirty = False
            if self._pos_surface or self._neg_surface:
                self._upload_meshes()

        self._render_scene(w, h)

        # Blit accumulation buffer to default framebuffer
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.defaultFramebufferObject())
        glBindFramebuffer(GL_READ_FRAMEBUFFER, self._acc_fbo)
        glBlitFramebuffer(0, 0, w, h, 0, 0, w, h,
                          GL_COLOR_BUFFER_BIT, GL_NEAREST)
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0)
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0)

    # ── Internal: FBO Management ──────────────────────────

    def _ensure_fbos(self, w, h):
        """Create/resize depth peeling FBOs if needed."""
        if w == self._fbo_width and h == self._fbo_height:
            return

        # Destroy old FBOs
        for fbo, ct, dt in self._dp_fbos:
            glDeleteFramebuffers(1, [fbo])
            glDeleteTextures([ct, dt])
        self._dp_fbos.clear()
        if self._acc_fbo:
            glDeleteFramebuffers(1, [self._acc_fbo])
            glDeleteTextures([self._acc_color, self._acc_depth])

        # Create new FBOs
        for _ in range(2):  # ping-pong pair for depth peeling
            fbo = glGenFramebuffers(1)
            ct = glGenTextures(1)
            dt = glGenTextures(1)

            glBindFramebuffer(GL_FRAMEBUFFER, fbo)

            # Color texture
            glBindTexture(GL_TEXTURE_2D, ct)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0,
                         GL_RGBA, GL_UNSIGNED_BYTE, None)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                                   GL_TEXTURE_2D, ct, 0)

            # Depth texture
            glBindTexture(GL_TEXTURE_2D, dt)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT24, w, h, 0,
                         GL_DEPTH_COMPONENT, GL_FLOAT, None)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                                   GL_TEXTURE_2D, dt, 0)

            glBindFramebuffer(GL_FRAMEBUFFER, 0)
            self._dp_fbos.append((fbo, ct, dt))

        # Accumulation FBO
        self._acc_fbo = glGenFramebuffers(1)
        self._acc_color = glGenTextures(1)
        self._acc_depth = glGenTextures(1)

        glBindFramebuffer(GL_FRAMEBUFFER, self._acc_fbo)

        glBindTexture(GL_TEXTURE_2D, self._acc_color)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0,
                     GL_RGBA, GL_UNSIGNED_BYTE, None)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                               GL_TEXTURE_2D, self._acc_color, 0)

        glBindTexture(GL_TEXTURE_2D, self._acc_depth)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT24, w, h, 0,
                     GL_DEPTH_COMPONENT, GL_FLOAT, None)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                               GL_TEXTURE_2D, self._acc_depth, 0)

        glBindFramebuffer(GL_FRAMEBUFFER, 0)

        self._fbo_width = w
        self._fbo_height = h

    # ── Internal: Scene Rendering ─────────────────────────

    def _render_scene(self, w, h):
        """Main rendering pipeline with depth peeling."""

        # Projection matrix (perspective)
        aspect = w / h if h > 0 else 1.0
        proj = self._perspective(35.0, aspect, 0.1, 100.0)
        view = self.camera.get_view_matrix()
        normal_mat = self.camera.get_normal_matrix()

        # Get peel FBO references
        fbo0, ct0, dt0 = self._dp_fbos[0]
        fbo1, ct1, dt1 = self._dp_fbos[1]

        # ── Clear accumulation buffer with background color ──
        glBindFramebuffer(GL_FRAMEBUFFER, self._acc_fbo)
        glViewport(0, 0, w, h)
        glUseProgram(self._prog_fullscreen)
        loc = glGetUniformLocation(self._prog_fullscreen, 'u_BgColor')
        glUniform4f(loc, *self._bg_color)
        glBindVertexArray(self._fsq_vao)
        glDisable(GL_DEPTH_TEST)
        glDrawElements(GL_TRIANGLES, self._fsq_count, GL_UNSIGNED_INT, None)
        glEnable(GL_DEPTH_TEST)
        glBindVertexArray(0)

        # ── Initialize peel depth textures to far plane (1.0) ──
        for fbo, _, _ in self._dp_fbos:
            glBindFramebuffer(GL_FRAMEBUFFER, fbo)
            glClear(GL_DEPTH_BUFFER_BIT)

        # ── Depth peeling loop ──
        for i_layer in range(self.DEPTH_PEEL_LAYERS):
            # Swap ping-pong FBOs
            if i_layer % 2 == 0:
                draw_fbo, draw_ct, draw_dt = fbo0, ct0, dt0
                prev_dt = dt1
            else:
                draw_fbo, draw_ct, draw_dt = fbo1, ct1, dt1
                prev_dt = dt0

            # Step 1: Render transparent surfaces to current peel FBO
            glBindFramebuffer(GL_FRAMEBUFFER, draw_fbo)
            glViewport(0, 0, w, h)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

            glUseProgram(self._prog_orbital)

            # Set transforms
            loc = glGetUniformLocation(self._prog_orbital, 'u_ModelView')
            glUniformMatrix4fv(loc, 1, GL_TRUE, view)
            loc = glGetUniformLocation(self._prog_orbital, 'u_NormalMatrix')
            glUniformMatrix3fv(loc, 1, GL_TRUE, normal_mat)
            loc = glGetUniformLocation(self._prog_orbital, 'u_Projection')
            glUniformMatrix4fv(loc, 1, GL_TRUE, proj)

            # Set style uniforms
            self._set_style_uniforms(self._prog_orbital)

            # Bind previous layer depth
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, prev_dt)
            loc = glGetUniformLocation(self._prog_orbital, 'DepthPrev')
            glUniform1i(loc, 0)

            # Render orbital surfaces (transparent)
            self.mesh_pos.draw()
            self.mesh_neg.draw()

            # Step 2: Composite into accumulation buffer
            glBindFramebuffer(GL_FRAMEBUFFER, self._acc_fbo)
            glViewport(0, 0, w, h)
            glDepthMask(GL_FALSE)
            glDisable(GL_DEPTH_TEST)
            glEnable(GL_BLEND)
            glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
                                GL_ONE, GL_ONE)

            glUseProgram(self._prog_composite)
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, draw_ct)
            loc = glGetUniformLocation(self._prog_composite, 'LayerColor')
            glUniform1i(loc, 0)

            glBindVertexArray(self._fsq_vao)
            glDrawElements(GL_TRIANGLES, self._fsq_count, GL_UNSIGNED_INT, None)
            glBindVertexArray(0)

            glDisable(GL_BLEND)
            glDepthMask(GL_TRUE)
            glEnable(GL_DEPTH_TEST)

        # ── Render opaque objects (atoms) directly to accumulation buffer ──
        glBindFramebuffer(GL_FRAMEBUFFER, self._acc_fbo)
        glViewport(0, 0, w, h)
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LESS)

        glUseProgram(self._prog_atom)
        loc = glGetUniformLocation(self._prog_atom, 'u_ModelView')
        glUniformMatrix4fv(loc, 1, GL_TRUE, view)
        loc = glGetUniformLocation(self._prog_atom, 'u_NormalMatrix')
        glUniformMatrix3fv(loc, 1, GL_TRUE, normal_mat)
        loc = glGetUniformLocation(self._prog_atom, 'u_Projection')
        glUniformMatrix4fv(loc, 1, GL_TRUE, proj)

        # Atom-specific style (more diffuse, less specular)
        glUseProgram(self._prog_atom)
        glUniform1f(glGetUniformLocation(self._prog_atom, 'ShaderReg0'), 1.5)
        glUniform1f(glGetUniformLocation(self._prog_atom, 'ShaderReg1'), 0.65)
        glUniform1f(glGetUniformLocation(self._prog_atom, 'ShaderReg2'), 0.5)
        glUniform1f(glGetUniformLocation(self._prog_atom, 'ShaderReg3'), 0.5)
        glUniform1f(glGetUniformLocation(self._prog_atom, 'FadeBias'), 0.2)
        glUniform1f(glGetUniformLocation(self._prog_atom, 'FadeWidth'), 4.0)
        loc = glGetUniformLocation(self._prog_atom, 'DiffuseColor')
        glUniform4f(loc, 0.8, 0.8, 0.8, 1.0)

        self.mesh_atoms.draw()
        self.mesh_bonds.draw()

        glBindFramebuffer(GL_FRAMEBUFFER, 0)

    def _set_style_uniforms(self, prog):
        """Set lighting/style uniforms on the given shader program."""
        sp = self._style_params
        glUniform1f(glGetUniformLocation(prog, 'ShaderReg0'), sp['ShaderReg0'])
        glUniform1f(glGetUniformLocation(prog, 'ShaderReg1'), sp['ShaderReg1'])
        glUniform1f(glGetUniformLocation(prog, 'ShaderReg2'), sp['ShaderReg2'])
        glUniform1f(glGetUniformLocation(prog, 'ShaderReg3'), sp['ShaderReg3'])
        glUniform1f(glGetUniformLocation(prog, 'FadeBias'), sp['FadeBias'])
        glUniform1f(glGetUniformLocation(prog, 'FadeWidth'), sp['FadeWidth'])
        loc = glGetUniformLocation(prog, 'DiffuseColor')
        glUniform4f(loc, 1.0, 1.0, 1.0, sp['opacity'])

    # ── Internal: Mesh Management ─────────────────────────

    def _upload_meshes(self):
        """Upload all surface meshes to GPU."""
        self.mesh_pos.destroy()
        self.mesh_neg.destroy()

        self.mesh_pos = GlMesh()
        self.mesh_neg = GlMesh()

        if self._pos_surface:
            self.mesh_pos.upload(self._pos_surface)
        if self._neg_surface:
            self.mesh_neg.upload(self._neg_surface)

    def _gen_atom_mesh(self):
        """Generate combined atom sphere + bond (cylinder) meshes.

        Atom colours follow the GaussView scheme (GVIEW_ELEMENT_COLORS);
        bonds are drawn black (GVIEW_BOND_COLOR) following GaussView's default.
        Bond detection uses the IboView heuristic in the Bohr frame:
            r_ij <= 0.5 * (bf + bf) * (cov_i + cov_j)  (bf = BOND_RADIUS_FACTOR)
        Cube atom coordinates and the covalent radii are both in Bohr, so the
        comparison is unit-consistent with the orbital (Bohr) scene.
        """
        if self._cube_data is None or not self._cube_data.atoms:
            return

        from fchk_orbital import ATOM_RADII

        atoms = self._cube_data.atoms
        n = len(atoms)
        coords = np.array(
            [[a[2], a[3], a[4]] for a in atoms], dtype=np.float64)
        anums = [int(a[0]) for a in atoms]

        # ---- atoms ----
        atom_verts = []
        atom_norms = []
        atom_colors = []
        atom_indices = []
        voff = 0
        for i in range(n):
            z = anums[i]
            elem = ELEMENT_SYMBOLS.get(z, 'C') if ELEMENT_SYMBOLS else 'C'
            base_r = ATOM_RADII.get(elem, 0.7) * 0.5
            radius = base_r * self._atom_scale
            color = GVIEW_ELEMENT_COLORS.get(z, GVIEW_FALLBACK)
            v, nv, idx = _make_sphere_mesh(radius, 1)
            v = v + coords[i]
            c = np.tile(np.array([*color, 1.0], dtype=np.float32), (len(v), 1))
            atom_verts.append(v)
            atom_norms.append(nv)
            atom_colors.append(c)
            atom_indices.append(idx + voff)
            voff += len(v)

        if atom_verts:
            surf = IsoSurface()
            surf.vertices = np.vstack(atom_verts).astype(np.float32)
            surf.normals = np.vstack(atom_norms).astype(np.float32)
            surf.colors = np.vstack(atom_colors).astype(np.float32)
            surf.indices = np.concatenate(atom_indices).astype(np.uint32)
            self.mesh_atoms.upload(surf)
        else:
            self.mesh_atoms.upload(None)

        # ---- bonds (dual-threshold: solid / dashed / none) ----
        # Ported from IboView's FindBondLines + DrawBond1 / RenderHalfBond.
        # Bonds within rf_tight * (cov_i+cov_j) are solid cylinders.
        # Bonds between rf_tight and rf_loose are dashed (BOND_Partial).
        bond_verts = []
        bond_norms = []
        bond_colors = []
        bond_indices = []
        voff = 0
        bond_r = max(0.18 * self._bond_scale * 0.4, 0.04 * self._bond_scale)
        bond_col = GVIEW_BOND_COLOR
        bf_tight = self._bond_rf_tight
        bf_loose = self._bond_rf_loose
        dash_w = self._dash_weight

        for i in range(n):
            for j in range(i + 1, n):
                p = coords[i]
                q = coords[j]
                d_vec = q - p
                rij = np.linalg.norm(d_vec)
                if rij < 1e-6:
                    continue
                zi = anums[i]
                zj = anums[j]
                ci = _COVALENT_RADII_BOHR[zi] if zi < len(_COVALENT_RADII_BOHR) else 0.7
                cj = _COVALENT_RADII_BOHR[zj] if zj < len(_COVALENT_RADII_BOHR) else 0.7
                cov_sum = ci + cj

                # Check manual bond override first
                key = (i, j)
                override = self._bond_overrides.get(key)
                if override is not None:
                    if override == 'none':
                        continue
                    elif override == 'dashed':
                        is_dashed = True
                    else:  # 'solid'
                        is_dashed = False
                else:
                    is_dashed = False
                    if rij <= bf_tight * cov_sum:
                        pass
                    elif rij <= bf_loose * cov_sum:
                        is_dashed = True
                    else:
                        continue

                if is_dashed:
                    # Generate dashed bond geometry (segmented cylinders)
                    cv, cn = make_dashed_bond_geometry(
                        p, q, bond_r, n_segments=0, dash_weight=dash_w, seg=12)
                    if len(cv) > 0:
                        c = np.tile(np.array([*bond_col, 1.0], dtype=np.float32),
                                    (len(cv), 1))
                        bond_verts.append(cv)
                        bond_norms.append(cn)
                        bond_colors.append(c)
                        bond_indices.append(np.arange(len(cv), dtype=np.uint32) + voff)
                        voff += len(cv)
                else:
                    # Solid bond: single continuous cylinder
                    seg = d_vec / rij
                    y_axis = np.array([0.0, 1.0, 0.0])
                    axis = np.cross(y_axis, seg)
                    s = np.linalg.norm(axis)
                    if s < 1e-9:
                        R = np.eye(3, dtype=np.float64)
                    else:
                        axis /= s
                        cth = float(np.dot(y_axis, seg))
                        skew = np.array([
                            [0, -axis[2], axis[1]],
                            [axis[2], 0, -axis[0]],
                            [-axis[1], axis[0], 0]])
                        R = np.eye(3) + skew + skew @ skew * ((1.0 - cth) / (s * s))
                    S = np.diag([bond_r, rij, bond_r])
                    T = R @ S
                    cv, cn = make_cylinder(radius=1.0, height=1.0, seg=18)
                    cv = cv @ T.T + p
                    cn = cn @ R.T
                    c = np.tile(np.array([*bond_col, 1.0], dtype=np.float32), (len(cv), 1))
                    bond_verts.append(cv)
                    bond_norms.append(cn)
                    bond_colors.append(c)
                    bond_indices.append(np.arange(len(cv), dtype=np.uint32) + voff)
                    voff += len(cv)

        if bond_verts:
            bsurf = IsoSurface()
            bsurf.vertices = np.vstack(bond_verts).astype(np.float32)
            bsurf.normals = np.vstack(bond_norms).astype(np.float32)
            bsurf.colors = np.vstack(bond_colors).astype(np.float32)
            bsurf.indices = np.concatenate(bond_indices).astype(np.uint32)
            self.mesh_bonds.upload(bsurf)
        else:
            self.mesh_bonds.upload(None)

    def set_atom_scale(self, scale):
        """Set atom ball radius multiplier and regenerate the mesh."""
        self._atom_scale = float(scale)
        if self._cube_data is not None:
            self._gen_atom_mesh()
            self.update()

    def set_bond_scale(self, scale):
        """Set bond cylinder radius multiplier and regenerate the mesh."""
        self._bond_scale = float(scale)
        if self._cube_data is not None:
            self._gen_atom_mesh()
            self.update()

    def set_bond_rf_tight(self, value):
        """Set tight bond radius factor — bonds within this threshold are solid."""
        self._bond_rf_tight = max(0.5, min(3.0, float(value)))
        if self._cube_data is not None:
            self._gen_atom_mesh()
            self.update()

    def set_bond_rf_loose(self, value):
        """Set loose bond radius factor — bonds beyond tight but within this
        are dashed; beyond this are not drawn at all."""
        self._bond_rf_loose = max(0.5, min(3.0, float(value)))
        if self._bond_rf_loose < self._bond_rf_tight:
            self._bond_rf_loose = self._bond_rf_tight + 0.05
        if self._cube_data is not None:
            self._gen_atom_mesh()
            self.update()

    def set_dash_weight(self, value):
        """Set dashed bond fill ratio (0..1). 0.4 = IboView default."""
        self._dash_weight = max(0.05, min(1.0, float(value)))
        if self._cube_data is not None:
            self._gen_atom_mesh()
            self.update()

    # ── Bond override API ────────────────────────────────────────────
    def reset_bond_overrides(self):
        """Clear all manual bond overrides — revert to automatic detection."""
        self._bond_overrides.clear()
        self._selected_atoms.clear()
        if self._cube_data is not None:
            self._gen_atom_mesh()
            self.update()

    # ── Atom / bond picking (perspective projection) ────────────────
    def _screen_to_world(self, x, y, w=None, h=None):
        """Unproject screen (x, y) to world-space ray for perspective proj."""
        if w is None or h is None:
            w, h = max(1, self.width()), max(1, self.height())
        aspect = w / h if h > 0 else 1.0
        proj = self._perspective(35.0, aspect, 0.1, 100.0)
        view = self.camera.get_view_matrix()
        # NDC
        ndc_x = 2.0 * x / w - 1.0
        ndc_y = 1.0 - 2.0 * y / h
        # Ray in clip space: start at (ndc, -1, 1), end at (ndc, 1, 1)
        p_near = np.array([ndc_x, ndc_y, -1.0, 1.0], dtype=np.float64)
        p_far  = np.array([ndc_x, ndc_y,  1.0, 1.0], dtype=np.float64)
        inv_vp = np.linalg.inv(proj @ view)
        w_near = inv_vp @ p_near; w_near /= w_near[3]
        w_far  = inv_vp @ p_far;   w_far  /= w_far[3]
        origin = w_near[:3]
        d = w_far[:3] - w_near[:3]
        if np.linalg.norm(d) < 1e-9:
            return origin, np.array([0.0, 0.0, 1.0])
        return origin, d / np.linalg.norm(d)

    def _pick_atom(self, x, y):
        """Ray-sphere intersection: find nearest atom at screen (x,y)."""
        if self._cube_data is None or self._atom_positions is None:
            return -1, float('inf')
        ro, rd = self._screen_to_world(x, y)
        best_idx, best_dist = -1, float('inf')
        coords = self._atom_positions
        atom_r = 0.4 * 0.01 * self._atom_scale * 1.2
        for i, ctr in enumerate(coords):
            oc = ctr - ro
            t_ca = np.dot(oc, rd)
            if t_ca < 0:
                continue
            d2 = np.dot(oc, oc) - t_ca * t_ca
            r2 = atom_r * atom_r
            if d2 < r2:
                t_hc = np.sqrt(r2 - d2)
                t = t_ca - t_hc
                if t < best_dist:
                    best_dist = t; best_idx = i
        return best_idx, best_dist

    def _pick_bond(self, x, y):
        """Ray-cylinder approximation: find nearest bond at screen (x,y)."""
        if self._cube_data is None or self._atom_positions is None:
            return (-1, -1), float('inf')
        ro, rd = self._screen_to_world(x, y)
        coords = self._atom_positions
        anums = self._cube_data.atomic_numbers if hasattr(self._cube_data, 'atomic_numbers') else []
        n = len(coords)
        best_key, best_dist = (-1, -1), float('inf')
        bond_r = max(0.18 * self._bond_scale * 0.4, 0.04 * self._bond_scale) * 3.0
        for i in range(n):
            for j in range(i + 1, n):
                p, q = coords[i], coords[j]
                pq = q - p; l2 = np.dot(pq, pq)
                if l2 < 1e-6:
                    continue
                ro_p = ro - p
                t_l = np.dot(ro_p, pq) / l2
                t_l = max(0.0, min(1.0, t_l))
                closest = p + t_l * pq
                oc = closest - ro
                t_r = np.dot(oc, rd)
                closest_r = ro + max(0.0, t_r) * rd
                d = np.linalg.norm(closest - closest_r)
                if d < bond_r and t_r < best_dist:
                    best_dist = t_r; best_key = (i, j)
        return best_key, best_dist

    # ── Mouse event overrides: click → pick, drag → rotate ──────────
    CLICK_THRESHOLD = 4

    def mousePressEvent(self, event):
        self.setFocus()
        self._drag_start = (event.x(), event.y())
        self._was_drag = False
        btn = event.button()
        if btn in (Qt.LeftButton, Qt.MiddleButton, Qt.RightButton):
            self.camera.begin_drag(event.x(), event.y(), self.width(), self.height())
            self._mouse_button = btn

    def mouseMoveEvent(self, event):
        btn = getattr(self, '_mouse_button', Qt.NoButton)
        if btn == Qt.NoButton:
            return
        dx = event.x() - self._drag_start[0] if self._drag_start else 0
        dy = event.y() - self._drag_start[1] if self._drag_start else 0
        if abs(dx) > self.CLICK_THRESHOLD or abs(dy) > self.CLICK_THRESHOLD:
            self._was_drag = True
        if btn == Qt.LeftButton:
            self.camera.drag(event.x(), event.y(), self.width(), self.height(), pan=False)
            self.update()
        elif btn in (Qt.MiddleButton, Qt.RightButton):
            self.camera.drag(event.x(), event.y(), self.width(), self.height(), pan=True)
            self.update()
        self._drag_start = (event.x(), event.y())

    def mouseReleaseEvent(self, event):
        btn = getattr(self, '_mouse_button', Qt.NoButton)
        self.camera.end_drag()
        self._mouse_button = Qt.NoButton
        if btn == Qt.LeftButton and not self._was_drag:
            hit_idx, _ = self._pick_atom(event.x(), event.y())
            if hit_idx >= 0:
                mods = event.modifiers()
                if mods & Qt.ControlModifier:
                    if hit_idx in self._selected_atoms:
                        self._selected_atoms.remove(hit_idx)
                    else:
                        self._selected_atoms.append(hit_idx)
                else:
                    if hit_idx in self._selected_atoms and len(self._selected_atoms) == 1:
                        self._selected_atoms.clear()
                    else:
                        self._selected_atoms = [hit_idx]
                self._gen_atom_mesh()
                self.update()
        elif btn == Qt.RightButton and not self._was_drag:
            self._show_context_menu(event.globalPos())

    # ── Context menu ──────────────────────────────────────────────
    def _show_context_menu(self, pos):
        from PyQt5.QtWidgets import QMenu, QAction
        menu = QMenu(self)
        has_atoms = self._atom_positions is not None and len(self._atom_positions) > 0
        n_sel = len(self._selected_atoms)
        actions = []

        if n_sel == 2:
            i, j = self._selected_atoms[0], self._selected_atoms[1]
            sel_key = (min(i, j), max(i, j))
            cur = self._bond_overrides.get(sel_key, 'auto')
            actions.append(("连接成键 (实线)", sel_key, 'solid'))
            actions.append(("设为虚线键",        sel_key, 'dashed'))
            actions.append(("断开键",            sel_key, 'none'))
            if cur != 'auto':
                actions.append(("---", None, None))
                actions.append(("重置为自动检测", sel_key, 'reset'))
            actions.append(("---", None, None))

        if has_atoms:
            local_pos = self.mapFromGlobal(pos)
            bk, bd = self._pick_bond(local_pos.x(), local_pos.y())
            if bk != (-1, -1) and bd < 100.0:
                i, j = bk
                nb_key = (min(i, j), max(i, j))
                if nb_key != (sel_key if n_sel == 2 else None):
                    cur = self._bond_overrides.get(nb_key, 'auto')
                    if actions and actions[-1] != ("---", None, None):
                        actions.append(("---", None, None))
                    actions.append((f"键({i}-{j}) → 设为虚线", nb_key, 'dashed'))
                    actions.append((f"键({i}-{j}) → 断开",     nb_key, 'none'))
                    if cur != 'auto':
                        actions.append((f"键({i}-{j}) → 重置自动", nb_key, 'reset'))

        for label, key, state in actions:
            if label == "---":
                menu.addSeparator()
            else:
                act = QAction(label, self)
                act.triggered.connect(self._make_bond_handler(key, state))
                menu.addAction(act)

        if n_sel > 0:
            menu.addSeparator()
            a = QAction("清除选中", self)
            a.triggered.connect(self._clear_selection)
            menu.addAction(a)

        if self._bond_overrides:
            menu.addSeparator()
            a = QAction("重置所有键为自动检测", self)
            a.triggered.connect(self.reset_bond_overrides)
            menu.addAction(a)

        if has_atoms:
            menu.addSeparator()
            a = QAction("适配视图 (F)", self)
            a.triggered.connect(self.reset_view)
            menu.addAction(a)

        menu.popup(pos)

    def _make_bond_handler(self, key, state):
        def handler():
            try:
                if state == 'reset':
                    self._bond_overrides.pop(key, None)
                else:
                    self._bond_overrides[key] = state
                self._gen_atom_mesh()
                self.update()
            except Exception as ex:
                import traceback
                traceback.print_exc()
        return handler

    def _clear_selection(self):
        self._selected_atoms.clear()
        if self._cube_data is not None:
            self._gen_atom_mesh()
            self.update()

    # ── Internal: Projection ──────────────────────────────

    @staticmethod
    def _perspective(fov_y, aspect, near, far):
        """Build a perspective projection matrix."""
        f = 1.0 / np.tan(np.radians(fov_y) / 2.0)
        m = np.zeros((4, 4), dtype=np.float32)
        m[0, 0] = f / aspect
        m[1, 1] = f
        m[2, 2] = (far + near) / (near - far)
        m[2, 3] = (2.0 * far * near) / (near - far)
        m[3, 2] = -1.0
        return m

    # ── Mouse / Keyboard Interaction ──────────────────────

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        self.camera.zoom_by(delta)
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_R:
            self.reset_view()
        elif event.key() == Qt.Key_F:
            # Fit to view
            if self._cube_data:
                center, radius = compute_bounding_sphere(self._cube_data)
                self.camera.center = center
                self.camera.zoom = 3.0 / max(radius, 0.01)
                self.update()
        else:
            super().keyPressEvent(event)
