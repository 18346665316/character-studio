"""Prepare TripoSR vertex-colored meshes for texture-preserving interchange."""
from task_lock import serialized
import hashlib
import json
from pathlib import Path
import uuid
import zipfile

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt
import trimesh
import xatlas


def rasterize_colors(uvs, faces, colors, resolution):
    """Barycentric RGB interpolation in UV space; UV V=0 is the PNG bottom."""
    texture = np.zeros((resolution, resolution, 3), dtype=np.uint8)
    covered = np.zeros((resolution, resolution), dtype=bool)
    xy = np.asarray(uvs, dtype=np.float64) * (resolution - 1)
    xy[:, 1] = (resolution - 1) - xy[:, 1]
    for face in np.asarray(faces):
        points = xy[face]
        minimum = np.maximum(np.floor(points.min(axis=0)).astype(int), 0)
        maximum = np.minimum(np.ceil(points.max(axis=0)).astype(int), resolution - 1)
        if np.any(maximum < minimum):
            continue
        xx, yy = np.meshgrid(np.arange(minimum[0], maximum[0] + 1),
                             np.arange(minimum[1], maximum[1] + 1))
        a, b, c = points
        denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(denominator) < 1e-10:
            continue
        wa = ((b[1] - c[1]) * (xx - c[0]) + (c[0] - b[0]) * (yy - c[1])) / denominator
        wb = ((c[1] - a[1]) * (xx - c[0]) + (a[0] - c[0]) * (yy - c[1])) / denominator
        wc = 1.0 - wa - wb
        inside = (wa >= -1e-6) & (wb >= -1e-6) & (wc >= -1e-6)
        rgb = wa[..., None] * colors[face[0], :3] + wb[..., None] * colors[face[1], :3] + wc[..., None] * colors[face[2], :3]
        texture[yy[inside], xx[inside]] = np.clip(rgb[inside], 0, 255).astype(np.uint8)
        covered[yy[inside], xx[inside]] = True
    if not covered.any():
        raise ValueError('UV rasterization produced no covered pixels')
    # Extend colors through unused UV space to avoid black seams under filtering.
    _, indices = distance_transform_edt(~covered, return_indices=True)
    texture[~covered] = texture[tuple(indices[:, ~covered])]
    return Image.fromarray(texture, 'RGB'), float(covered.mean())


def prepare(source, destination, resolution=1024):
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError(f'Prepared destination already exists: {destination}')
    mesh = trimesh.load(source, force='mesh', process=False)
    if mesh.visual.kind != 'vertex' or len(np.unique(mesh.visual.vertex_colors[:, :3], axis=0)) < 8:
        raise ValueError('Expected a vertex-colored reconstruction; refusing to bake a white model')
    original_faces = len(mesh.faces)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.remove_unreferenced_vertices()
    pieces = mesh.split(only_watertight=False, repair=False)
    retained = [piece for piece in pieces if len(piece.faces) >= 64]
    if not retained:
        raise ValueError('No geometry survives tiny-fragment filtering')
    mesh = trimesh.util.concatenate(retained)
    component_faces = [len(piece.faces) for piece in retained]
    mesh.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
    # Set a documented meter-sized, Y-up basis with feet at Y=0.
    bounds = mesh.bounds.copy()
    height = float(bounds[1, 1] - bounds[0, 1])
    if height <= 0:
        raise ValueError('Invalid model height')
    mesh.apply_translation([-bounds[:, 0].mean(), -bounds[0, 1], -bounds[:, 2].mean()])
    mesh.apply_scale(1.7 / height)
    print('Generating UV atlas...', flush=True)
    atlas = xatlas.Atlas()
    atlas.add_mesh(np.asarray(mesh.vertices, dtype=np.float32), np.asarray(mesh.faces, dtype=np.uint32))
    options = xatlas.PackOptions()
    options.resolution = resolution
    options.padding = 8
    atlas.generate(pack_options=options)
    mapping, faces, uv = atlas[0]
    colors = np.asarray(mesh.visual.vertex_colors)[mapping]
    print('Baking vertex colors to texture...', flush=True)
    image, coverage = rasterize_colors(uv, faces, colors, resolution)
    output = trimesh.Trimesh(vertices=mesh.vertices[mapping], faces=faces, process=False)
    material = trimesh.visual.material.SimpleMaterial(image=image, diffuse=[255, 255, 255, 255], name='body')
    output.visual = trimesh.visual.texture.TextureVisuals(uv=uv, material=material)
    destination.mkdir(parents=True)
    image.save(destination / 'albedo.png')
    with (destination / 'model.mtl').open('w') as stream:
        stream.write('newmtl body\nKa 1 1 1\nKd 1 1 1\nKs 0 0 0\nd 1\nillum 1\nmap_Kd albedo.png\n')
    with (destination / 'model.obj').open('w') as stream:
        stream.write('mtllib model.mtl\no body\n')
        for v in output.vertices:
            stream.write('v %.9f %.9f %.9f\n' % tuple(v))
        for value in uv:
            stream.write('vt %.9f %.9f\n' % tuple(value))
        stream.write('usemtl body\n')
        for face in output.faces + 1:
            stream.write('f ' + ' '.join(f'{v}/{v}' for v in face) + '\n')
    output.export(destination / 'preview.glb')
    with zipfile.ZipFile(destination / 'mixamo.zip', 'w', zipfile.ZIP_DEFLATED) as bundle:
        for name in ['model.obj', 'model.mtl', 'albedo.png']:
            bundle.write(destination / name, name)
    receipt = {'source': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
               'triangles_before': original_faces, 'triangles_after': len(output.faces),
               'retained_component_faces': component_faces, 'uv_coverage': coverage,
               'height_meters': 1.7, 'up_axis': 'Y', 'texture_resolution': resolution,
               'visual_review': 'pending', 'cleanup': 'Removed degenerate faces and components smaller than 64 faces; larger disconnected parts require human review.'}
    (destination / 'prepare.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(f'Textured package ready: {destination / "mixamo.zip"}', flush=True)
    return destination


@serialized(lambda base, *args, **kwargs: base)
def prepare_character(base, character):
    source = Path(base) / 'workspaces' / character / 'models' / f'{character}.obj'
    destination = source.parent / 'prepared' / uuid.uuid4().hex[:12]
    return prepare(source, destination)
