"""
Marching Cubes Isosurface Extraction
=====================================
Extracts triangle mesh from 3D scalar grid data (cube file format).
Uses PyMCubes (well-tested Cython marching cubes) for the core algorithm,
with coordinate transformation and gradient-based normal computation.
"""

import numpy as np

try:
    import mcubes
    _HAS_MCUBES = True
except ImportError:
    _HAS_MCUBES = False


# ── Cube File Reader ───────────────────────────────────────

class CubeData:
    """Represents data read from a Gaussian cube file."""

    def __init__(self):
        self.n_atoms = 0
        self.origin = np.zeros(3, dtype=np.float32)
        self.nx = self.ny = self.nz = 0
        self.dx = self.dy = self.dz = (1.0, 0.0, 0.0)
        self.atoms = []
        self.data = None

    @property
    def shape(self):
        return (self.nx, self.ny, self.nz)

    def voxel_to_world(self, ix, iy, iz):
        x = self.origin[0] + ix*self.dx[0] + iy*self.dy[0] + iz*self.dz[0]
        y = self.origin[1] + ix*self.dx[1] + iy*self.dy[1] + iz*self.dz[1]
        z = self.origin[2] + ix*self.dx[2] + iy*self.dy[2] + iz*self.dz[2]
        return np.array([x, y, z], dtype=np.float32)


def read_cube(filepath):
    """Read a Gaussian cube file and return a CubeData object."""
    with open(filepath, 'r') as f:
        f.readline()  # comment line 1
        f.readline()  # comment line 2

        parts = f.readline().split()
        n_atoms = int(parts[0])
        ox, oy, oz = float(parts[1]), float(parts[2]), float(parts[3])

        parts = f.readline().split()
        nx = int(parts[0])
        dx = (float(parts[1]), float(parts[2]), float(parts[3]))

        parts = f.readline().split()
        ny = int(parts[0])
        dy = (float(parts[1]), float(parts[2]), float(parts[3]))

        parts = f.readline().split()
        nz = int(parts[0])
        dz = (float(parts[1]), float(parts[2]), float(parts[3]))

        atoms = []
        for _ in range(n_atoms):
            parts = f.readline().split()
            atomic_num = int(parts[0])
            charge = float(parts[1])
            ax, ay, az = float(parts[2]), float(parts[3]), float(parts[4])
            atoms.append((atomic_num, charge, ax, ay, az))

        raw_data = []
        for line in f:
            for val in line.split():
                raw_data.append(float(val))

        total = nx * ny * nz
        if len(raw_data) != total:
            raise ValueError(f"Expected {total} points, got {len(raw_data)}")

        data = np.array(raw_data, dtype=np.float32).reshape((nx, ny, nz))

    cube = CubeData()
    cube.n_atoms = n_atoms
    cube.origin = np.array([ox, oy, oz], dtype=np.float32)
    cube.nx, cube.ny, cube.nz = nx, ny, nz
    cube.dx = dx
    cube.dy = dy
    cube.dz = dz
    cube.atoms = atoms
    cube.data = data
    return cube


# ── IsoSurface Data Structure ──────────────────────────────

class IsoSurface:
    """Triangle mesh data for an isosurface."""
    def __init__(self):
        self.vertices = None    # (N,3) float32
        self.normals = None     # (N,3) float32
        self.indices = None     # (M,) uint32
        self.colors = None      # (N,4) float32 (RGBA)

    @property
    def vertex_count(self):
        return len(self.vertices) if self.vertices is not None else 0

    @property
    def triangle_count(self):
        return len(self.indices) // 3 if self.indices is not None else 0


# ── Gradient Computation ───────────────────────────────────

def _compute_gradients(data):
    """Compute central-difference gradients of the scalar field."""
    nx, ny, nz = data.shape
    gx = np.zeros_like(data)
    gy = np.zeros_like(data)
    gz = np.zeros_like(data)

    if nx > 2:
        gx[1:-1, :, :] = (data[2:, :, :] - data[:-2, :, :]) * 0.5
    if ny > 2:
        gy[:, 1:-1, :] = (data[:, 2:, :] - data[:, :-2, :]) * 0.5
    if nz > 2:
        gz[:, :, 1:-1] = (data[:, :, 2:] - data[:, :, :-2]) * 0.5

    # boundaries
    gx[0, :, :] = data[1, :, :] - data[0, :, :]
    if nx > 1:
        gx[-1, :, :] = data[-1, :, :] - data[-2, :, :]
    gy[:, 0, :] = data[:, 1, :] - data[:, 0, :]
    if ny > 1:
        gy[:, -1, :] = data[:, -1, :] - data[:, -2, :]
    gz[:, :, 0] = data[:, :, 1] - data[:, :, 0]
    if nz > 1:
        gz[:, :, -1] = data[:, :, -1] - data[:, :, -2]

    return gx, gy, gz


# ── Marching Cubes ─────────────────────────────────────────

def _trilinear(field, idx0, idx1, frac):
    """Trilinear sample of `field` at fractional indices (vectorised).

    idx0/idx1: (N,3) int arrays of the lower/upper corner indices.
    frac:      (N,3) float array of the fractional offsets in [0,1).
    """
    x0, y0, z0 = idx0[:, 0], idx0[:, 1], idx0[:, 2]
    x1, y1, z1 = idx1[:, 0], idx1[:, 1], idx1[:, 2]
    fx, fy, fz = frac[:, 0], frac[:, 1], frac[:, 2]
    gx_, gy_, gz_ = 1.0 - fx, 1.0 - fy, 1.0 - fz
    return (field[x0, y0, z0] * gx_ * gy_ * gz_ +
            field[x1, y0, z0] * fx * gy_ * gz_ +
            field[x0, y1, z0] * gx_ * fy * gz_ +
            field[x1, y1, z0] * fx * fy * gz_ +
            field[x0, y0, z1] * gx_ * gy_ * fz +
            field[x1, y0, z1] * fx * gy_ * fz +
            field[x0, y1, z1] * gx_ * fy * fz +
            field[x1, y1, z1] * fx * fy * fz)


def marching_cubes(cube_data, isovalue, flip_normal=False):
    """Extract isosurface from CubeData using mcubes marching cubes.

    Normal handling follows IboView's ``FIsoSurface::FixVolumeDataNormals``
    (IvIsoSurface.cpp): the raw normal is the *gradient* of the volume data at
    the vertex.  For a surface enclosing a region where the data is **larger**
    than the iso level (the positive lobe), the gradient points *into* the
    solid, so both the normal **and** the triangle winding have to be flipped
    to keep the outward-facing side the front face.  For the negative lobe
    (data < -iso) the gradient already points outwards and nothing is flipped.

    Args:
        cube_data: CubeData with 3D grid values
        isovalue: threshold value for the isosurface (may be negative)
        flip_normal: set for the negative lobe; keeps the raw gradient normal

    Returns:
        IsoSurface with vertices, normals, indices (outward normals, CCW front
        faces).
    """
    if not _HAS_MCUBES:
        raise RuntimeError("PyMCubes is required. Install with: pip install PyMCubes")

    data = cube_data.data.astype(np.float64)

    # mcubes expects (nx, ny, nz) indexed as [ix, iy, iz]
    # Returns vertices in [0, nx-1] index space and triangles as index triples
    mc_verts, mc_tris = mcubes.marching_cubes(data, float(isovalue))

    result = IsoSurface()
    n_verts = len(mc_verts)
    if n_verts == 0 or len(mc_tris) == 0:
        result.vertices = np.zeros((0, 3), dtype=np.float32)
        result.normals = np.zeros((0, 3), dtype=np.float32)
        result.indices = np.zeros((0,), dtype=np.uint32)
        return result

    mc_verts = np.asarray(mc_verts, dtype=np.float64)
    tris = np.asarray(mc_tris, dtype=np.int64).reshape(-1, 3)

    # ── Index space -> world coordinates (vectorised voxel_to_world) ──
    basis = np.array([cube_data.dx, cube_data.dy, cube_data.dz], dtype=np.float64)
    world_verts = (cube_data.origin.astype(np.float64) +
                   mc_verts @ basis).astype(np.float32)

    # ── Gradient-based normals (trilinear interpolation) ──
    gx, gy, gz = _compute_gradients(data.astype(np.float32))

    dims = np.array([cube_data.nx, cube_data.ny, cube_data.nz], dtype=np.int64)
    idx0 = np.floor(mc_verts).astype(np.int64)
    np.clip(idx0, 0, dims - 1, out=idx0)
    idx1 = np.minimum(idx0 + 1, dims - 1)
    frac = mc_verts - idx0

    grad = np.empty((n_verts, 3), dtype=np.float64)
    grad[:, 0] = _trilinear(gx, idx0, idx1, frac)
    grad[:, 1] = _trilinear(gy, idx0, idx1, frac)
    grad[:, 2] = _trilinear(gz, idx0, idx1, frac)

    # The gradient is expressed in *index* space; convert to world space so the
    # normals stay correct for non-cubic / skewed cube grids.  For a linear map
    # x_world = B^T * i, gradients transform with the inverse transpose.
    try:
        grad = grad @ np.linalg.inv(basis)
    except np.linalg.LinAlgError:
        pass

    mag = np.linalg.norm(grad, axis=1, keepdims=True)
    normals = np.divide(grad, mag, out=np.zeros_like(grad), where=(mag > 1e-10))
    degenerate = (mag[:, 0] <= 1e-10)
    if degenerate.any():
        normals[degenerate] = (0.0, 0.0, 1.0)

    # ── IboView FixVolumeDataNormals: flip normals *and* winding together ──
    #
    # PyMCubes emits triangles whose geometric face normal (CCW cross product)
    # points along -grad, i.e. towards *decreasing* data.  Therefore:
    #   * positive lobe (data > +iso): outward == -grad, so the raw winding is
    #     already correct and the shading normal is simply -grad;
    #   * negative lobe (data < -iso): outward == +grad, so both the normal and
    #     the winding have to be flipped, exactly as IboView's
    #     FixVolumeDataNormals does when it detects a sign mismatch.
    if flip_normal:
        tris = tris[:, [0, 2, 1]]      # negative lobe: outward is +grad
    else:
        normals = -normals             # positive lobe: outward is -grad

    result.vertices = world_verts
    result.normals = normals.astype(np.float32)
    result.indices = np.ascontiguousarray(tris, dtype=np.uint32).flatten()
    return result


def extract_orbital_surfaces(cube_file, isovalue, pos_color=None, neg_color=None):
    """Extract both positive and negative isosurfaces from a cube file.

    Args:
        cube_file: path to .cub file
        isovalue: positive isovalue threshold
        pos_color: (r, g, b) tuple for positive surface
        neg_color: (r, g, b) tuple for negative surface

    Returns:
        tuple of (pos_surface, neg_surface, cube_data)
    """
    cube = read_cube(cube_file)

    pos_surf = marching_cubes(cube, isovalue, flip_normal=False)
    neg_surf = marching_cubes(cube, -isovalue, flip_normal=True)

    if pos_color:
        c = np.array([pos_color[0], pos_color[1], pos_color[2], 1.0], dtype=np.float32)
        pos_surf.colors = np.tile(c, (pos_surf.vertex_count, 1))
    else:
        pos_surf.colors = np.tile(
            np.array([0.1, 0.8, 0.1, 1.0], dtype=np.float32),
            (pos_surf.vertex_count, 1))

    if neg_color:
        c = np.array([neg_color[0], neg_color[1], neg_color[2], 1.0], dtype=np.float32)
        neg_surf.colors = np.tile(c, (neg_surf.vertex_count, 1))
    else:
        neg_surf.colors = np.tile(
            np.array([0.9, 0.25, 0.25, 1.0], dtype=np.float32),
            (neg_surf.vertex_count, 1))

    return pos_surf, neg_surf, cube


def relative_iso_threshold(cube_data, percent=80.0):
    """IboView-like *relative* iso threshold for a volume data set.

    IboView's ``IsoThreshold`` (default 80.0) is not an absolute isovalue: it
    asks for the iso surface enclosing a given percentage of the total
    ``|data|`` weight.  This helper reproduces that behaviour by sorting the
    grid values by magnitude and finding the cut-off |value| at which the
    accumulated weight reaches ``percent`` % of the total.

    Note: IboView integrates rho = |psi|^2 over real space; here we use the
    raw grid samples of the cube file, which is an approximation (it assumes a
    uniform voxel volume and ignores the actual quadrature weights).

    Args:
        cube_data: CubeData
        percent: target percentage of the total |data| weight (0..100)

    Returns:
        A positive float isovalue.
    """
    a = np.abs(np.asarray(cube_data.data, dtype=np.float64).ravel())
    total = a.sum()
    if total <= 0.0 or a.size == 0:
        return 0.05

    order = np.argsort(a)[::-1]          # largest magnitude first
    cum = np.cumsum(a[order])
    target = total * max(0.0, min(percent, 100.0)) / 100.0
    k = int(np.searchsorted(cum, target))
    k = min(k, a.size - 1)
    iso = float(a[order][k])
    return iso if iso > 0.0 else 0.05


def compute_bounding_sphere(cube_data):
    """Compute bounding sphere center and radius from cube data atoms."""
    if not cube_data.atoms:
        corners = []
        for iz in [0, cube_data.nz-1]:
            for iy in [0, cube_data.ny-1]:
                for ix in [0, cube_data.nx-1]:
                    corners.append(cube_data.voxel_to_world(ix, iy, iz))
        pts = np.array(corners)
        center = pts.mean(axis=0)
        radius = float(np.max(np.linalg.norm(pts - center, axis=1)))
        return center, radius

    pts = np.array([(a[2], a[3], a[4]) for a in cube_data.atoms])
    center = pts.mean(axis=0)
    radius = float(np.max(np.linalg.norm(pts - center, axis=1)))
    radius *= 1.5
    return center, max(radius, 1.0)
