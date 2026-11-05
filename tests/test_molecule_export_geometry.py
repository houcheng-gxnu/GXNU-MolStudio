# -*- coding: utf-8 -*-
"""Low-level geometry checks for the PowerPoint GLB exporter."""

import numpy as np

from molstudio.core.molecule_export import _ContactAOBaker, _Part


def _check_front_faces(part):
    vertices = np.asarray(part.positions, dtype=float).reshape(-1, 3)
    normals = np.asarray(part.normals, dtype=float).reshape(-1, 3)
    indices = np.asarray(part.indices, dtype=int).reshape(-1, 3)
    checked = 0
    for triangle in indices:
        a, b, c = vertices[triangle]
        face = np.cross(b - a, c - a)
        if np.linalg.norm(face) < 1e-12:
            continue
        vertex_normal = normals[triangle].mean(axis=0)
        assert float(np.dot(face, vertex_normal)) > 0.0
        checked += 1
    assert checked > 0


def test_sphere_and_cylinder_triangles_face_outward():
    sphere = _Part()
    sphere.add_sphere(np.zeros(3), 1.0, latitude=7, longitude=12)
    _check_front_faces(sphere)

    cylinder = _Part()
    cylinder.add_cylinder(
        np.array((0.0, 0.0, -1.0)),
        np.array((0.0, 0.0, 1.0)),
        0.2, sides=12)
    _check_front_faces(cylinder)

    outline = _Part()
    outline.add_sphere(
        np.zeros(3), 1.03, latitude=12, longitude=18, flip=True)
    _check_front_faces(outline)


def test_contact_ao_darkens_overlapping_atom_surface():
    baker = _ContactAOBaker(
        centers=np.array(((0.0, 0.0, 0.0), (0.9, 0.0, 0.0))),
        radii=np.array((1.0, 1.0)),
        rays=16,
        max_distance=3.8,
    )
    near = baker.factors(
        np.array(((1.0, 0.0, 0.0),)),
        np.array(((1.0, 0.0, 0.0),)),
    )
    far = baker.factors(
        np.array(((-1.0, 0.0, 0.0),)),
        np.array(((-1.0, 0.0, 0.0),)),
    )
    assert 0.65 <= near[0] < 1.0
    assert far[0] > near[0]
