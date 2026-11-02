"""Deterministic, parameterized building reference compiler (no paid requests).

World x/y are measured in ground cells. Heights are world units, projected at
cell_px/2 pixels per unit. A small orthographic z-buffer resolves both ridge
orientations without hand-coded painter ordering. This is reference geometry,
not a game collision mesh or a finished building sprite.
"""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from asset_projection import contract
from asset_repository import atomic

PALETTE = {
    1: ('wall_-x', '#b7bec1'), 2: ('wall_+x', '#a8b0b4'),
    3: ('wall_-y', '#dce0df'), 4: ('wall_+y', '#d7d9d7'),
    5: ('roof_negative_slope', '#c6ced5'),
    6: ('roof_positive_slope', '#929fab'),
    7: ('roof_negative_gable', '#cbd0d1'),
    8: ('roof_positive_gable', '#bdc3c4'),
    9: ('roof_underside', '#7c8790'),
    10: ('door', '#596774'), 11: ('window', '#8ca0ac'),
}


def number(value, low, high, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{label}须为{low}–{high}之间的数值')
    return float(value)


def validate(data):
    if not isinstance(data, dict):
        raise ValueError('建筑结构须为对象')
    allowed = {'footprint_cells', 'cell_px', 'wall_height_units', 'roof', 'openings'}
    if set(data)-allowed:
        raise ValueError('未知建筑参数：'+', '.join(sorted(set(data)-allowed)))
    footprint = data.get('footprint_cells', [3, 2])
    if not isinstance(footprint, list) or len(footprint) != 2:
        raise ValueError('占地须为两个整数')
    if any(type(v) is not int or not 1 <= v <= 8 for v in footprint):
        raise ValueError('占地长宽须为1–8格整数')
    cell = data.get('cell_px', 128)
    if type(cell) is not int or cell not in (64, 128):
        raise ValueError('地格宽度须为64或128像素')
    height = number(data.get('wall_height_units', 1.5), .5, 4, '墙高')
    roof = data.get('roof', {})
    if not isinstance(roof, dict) or set(roof)-{'type', 'ridge_axis', 'rise_units', 'overhang_cells'}:
        raise ValueError('屋顶参数无效')
    if roof.get('type', 'gable') != 'gable' or roof.get('ridge_axis', 'x') not in ('x', 'y'):
        raise ValueError('首轮支持双坡屋顶，屋脊方向须为x或y')
    rise = number(roof.get('rise_units', 1), .2, 3, '屋顶高度')
    overhang = number(roof.get('overhang_cells', .2), 0, .5, '出檐')
    axis = roof.get('ridge_axis', 'x')
    cross = footprint[1 if axis == 'x' else 0]
    if height-rise*overhang/(cross/2) < .2:
        raise ValueError('出檐过低，请降低屋顶坡度或减小出檐')
    openings = data.get('openings', [
        {'type': 'door', 'facade': '+y', 'center': footprint[0]/2,
         'bottom': 0, 'width': .6, 'height': min(1.05, height*.7)},
    ])
    if not isinstance(openings, list) or len(openings) > 17:
        raise ValueError('门窗清单无效，最多17个')
    normalized = []
    for opening in openings:
        if not isinstance(opening, dict) or set(opening)-{'type', 'facade', 'center', 'bottom', 'width', 'height'}:
            raise ValueError('门窗参数无效')
        kind, facade = opening.get('type'), opening.get('facade')
        if kind not in ('door', 'window') or facade not in ('+x', '-x', '+y', '-y'):
            raise ValueError('门窗类型或所属墙面无效')
        length = footprint[1 if facade.endswith('x') else 0]
        center = number(opening.get('center'), 0, length, '门窗中心')
        width = number(opening.get('width'), .15, length, '门窗宽度')
        bottom = number(opening.get('bottom', 0), 0, height, '门窗底高')
        opening_height = number(opening.get('height'), .15, height, '门窗高度')
        if center-width/2 < .05 or center+width/2 > length-.05 or bottom+opening_height > height-.05:
            raise ValueError('门窗超出墙面或距离边缘过近')
        if kind == 'door' and bottom != 0:
            raise ValueError('首轮入口门必须落地')
        item = dict(type=kind, facade=facade, center=center, width=width,
                    bottom=bottom, height=opening_height)
        for previous in normalized:
            if previous['facade'] == facade and abs(previous['center']-center) < (previous['width']+width)/2+.05:
                if min(previous['bottom']+previous['height'], bottom+opening_height) > max(previous['bottom'], bottom)-.05:
                    raise ValueError('同墙面门窗重叠或间距不足')
        normalized.append(item)
    if sum(o['type'] == 'door' for o in normalized) != 1:
        raise ValueError('首轮需要且仅支持一个入口门')
    return dict(footprint_cells=list(footprint), cell_px=cell, wall_height_units=height,
                roof=dict(type='gable', ridge_axis=axis, rise_units=rise, overhang_cells=overhang),
                openings=normalized)


def facade_point(facade, u, z, width, depth, offset=0):
    if facade == '+x': return (width+offset, u, z)
    if facade == '-x': return (-offset, u, z)
    if facade == '+y': return (u, depth+offset, z)
    return (u, -offset, z)


def geometry(spec):
    width, depth = spec['footprint_cells']
    height = spec['wall_height_units']
    faces, landmarks = [], {}
    for index, facade in enumerate(['-x', '+x', '-y', '+y'], 1):
        length = depth if facade.endswith('x') else width
        points = [facade_point(facade, u, z, width, depth) for u, z in
                  [(0, 0), (length, 0), (length, height), (0, height)]]
        faces.append((index, points))
        landmarks['wall_'+facade] = points
    roof = spec['roof']; axis = roof['ridge_axis']
    length, cross = (width, depth) if axis == 'x' else (depth, width)
    overhang = roof['overhang_cells']
    eave = height-roof['rise_units']*overhang/(cross/2)
    top = height+roof['rise_units']

    def point(a, b, z): return (a, b, z) if axis == 'x' else (b, a, z)

    a, b = -overhang, length+overhang
    lo, mid, hi = -overhang, cross/2, cross+overhang
    faces.extend([
        (5, [point(a, lo, eave), point(b, lo, eave), point(b, mid, top), point(a, mid, top)]),
        (6, [point(a, mid, top), point(b, mid, top), point(b, hi, eave), point(a, hi, eave)]),
        (7, [point(a, lo, eave), point(a, mid, top), point(a, hi, eave)]),
        (8, [point(b, lo, eave), point(b, mid, top), point(b, hi, eave)]),
        (9, [point(a, lo, eave), point(b, lo, eave), point(b, hi, eave), point(a, hi, eave)]),
    ])
    landmarks['ridge'] = [point(a, mid, top), point(b, mid, top)]
    landmarks['eaves'] = [point(a, lo, eave), point(b, lo, eave), point(b, hi, eave), point(a, hi, eave)]
    for i, opening in enumerate(spec['openings']):
        u, w = opening['center'], opening['width']; z, h = opening['bottom'], opening['height']
        points = [facade_point(opening['facade'], x, y, width, depth, .002)
                  for x, y in [(u-w/2, z), (u+w/2, z), (u+w/2, z+h), (u-w/2, z+h)]]
        faces.append((20+i, points))
        landmarks['opening_'+str(i)] = points
    return faces, landmarks


def screen(point, cell):
    x, y, z = point
    return np.array([(x-y)*cell/2, (x+y)*cell/4-z*cell/2])


def render(spec, faces):
    cell = spec['cell_px']; margin = 32
    bounds = np.array([screen(p, cell) for _, points in faces for p in points])
    low, high = bounds.min(axis=0), bounds.max(axis=0)
    origin = np.ceil(margin-low)
    size = np.ceil((high+origin+margin)/16).astype(int)*16
    if max(size) > 2048:
        raise ValueError('结构画布超过2048像素，请降低地格尺寸或建筑规格')
    scale = 2
    width, height = map(int, size*scale)
    depth_buffer = np.full((height, width), -np.inf, dtype=np.float32)
    ids = np.zeros((height, width), dtype=np.uint8)
    for identity, vertices in faces:
        projected = [(screen(p, cell)+origin)*scale for p in vertices]
        for i in range(1, len(vertices)-1):
            indices = [0, i, i+1]; a, b, c = [projected[j] for j in indices]
            lower = np.floor(np.min([a, b, c], axis=0)).astype(int)
            upper = np.ceil(np.max([a, b, c], axis=0)).astype(int)
            x0, y0 = np.maximum(lower, 0); x1, y1 = np.minimum(upper, [width, height])
            if x1 <= x0 or y1 <= y0: continue
            yy, xx = np.mgrid[y0:y1, x0:x1]; xx = xx+.5; yy = yy+.5
            denominator = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
            if abs(denominator) < 1e-8: continue
            wa = ((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/denominator
            wb = ((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/denominator
            wc = 1-wa-wb
            z = sum(weight*sum(vertices[j]) for weight, j in zip([wa, wb, wc], indices))
            region = depth_buffer[y0:y1, x0:x1]
            use = (wa >= -1e-8) & (wb >= -1e-8) & (wc >= -1e-8) & (z >= region)
            region[use] = z[use]; ids[y0:y1, x0:x1][use] = identity
    visibility = []
    for i, opening in enumerate(spec['openings']):
        points = np.array([screen(p, cell)*scale for p in faces[9+i][1]])
        area = abs(np.dot(points[:, 0], np.roll(points[:, 1], 1))-np.dot(points[:, 1], np.roll(points[:, 0], 1)))/2
        visible = int(np.count_nonzero(ids == 20+i))
        ratio = min(1., visible/max(area, 1))
        visibility.append(dict(index=i, type=opening['type'], facade=opening['facade'],
                               visible_ratio=round(ratio, 4), visible_pixels=visible,
                               warning='不可见或被屋檐完全遮挡' if ratio < .01 else ('部分遮挡' if ratio < .9 else None)))
        ids[ids == 20+i] = 10 if opening['type'] == 'door' else 11
    colors = np.zeros((12, 4), dtype=np.uint8)
    for identity, (_, color) in PALETTE.items():
        colors[identity] = [*bytes.fromhex(color[1:]), 255]
    sprite = Image.fromarray(colors[ids], 'RGBA').resize(tuple(size), Image.Resampling.LANCZOS)
    face_map = Image.fromarray(ids, 'L').resize(tuple(size), Image.Resampling.NEAREST)
    return sprite, face_map, origin.tolist(), visibility


def compile_structure(data, output):
    spec = validate(data)
    faces, landmarks = geometry(spec)
    sprite, face_map, origin, visibility = render(spec, faces)
    if any(o['type'] == 'door' and o['visible_ratio'] < .1 for o in visibility):
        raise ValueError('入口在当前投影中不可见或被屋檐遮挡，请修改入口墙面、门高或出檐')
    output = Path(output)
    # Compile once to a fresh directory. Never overwrite a reference used by an attempt.
    output.mkdir(parents=True, exist_ok=False)
    cell = spec['cell_px']; width, depth = spec['footprint_cells']

    def pixel(p): return (screen(p, cell)+origin).tolist()

    footprint = [pixel(p) for p in [(0, 0, 0), (width, 0, 0), (width, depth, 0), (0, depth, 0)]]
    anchor = pixel((width/2, depth/2, 0))
    door = next(o for o in spec['openings'] if o['type'] == 'door')
    entrance_world = facade_point(door['facade'], door['center'], 0, width, depth)
    direction = {'+x': [1, 0, 0], '-x': [-1, 0, 0], '+y': [0, 1, 0], '-y': [0, -1, 0]}[door['facade']]
    sprite.save(output/'structure.png'); face_map.save(output/'faces.png')
    sprite.getchannel('A').save(output/'silhouette.png')
    reference = Image.new('RGBA', sprite.size, '#f3f1ec'); reference.alpha_composite(sprite)
    reference.convert('RGB').save(output/'reference.png')
    inspection = reference.convert('RGB'); pen = ImageDraw.Draw(inspection)
    pen.line([tuple(p) for p in footprint+[footprint[0]]], '#e98428', 2)
    pen.ellipse((anchor[0]-4, anchor[1]-4, anchor[0]+4, anchor[1]+4), fill='#d95163')
    entrance = pixel(entrance_world)
    approach = pixel([v+d*.6 for v, d in zip(entrance_world, direction)])
    pen.line([tuple(entrance), tuple(approach)], '#008f99', 3)
    inspection.save(output/'inspection.png')
    canonical = json.dumps(spec, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    result = {
        'schema': 'studio.building-structure/0.1', 'spec': spec,
        'structure_sha256': hashlib.sha256(canonical.encode()).hexdigest(),
        'projection': contract(cell), 'vertical_screen_px_per_unit': cell/2,
        'world_origin_px': origin, 'canvas_px': list(sprite.size),
        'ground_anchor_px': anchor, 'footprint_polygon_px': footprint,
        'landmarks_px': {key: [pixel(p) for p in points] for key, points in landmarks.items()},
        'entrance': {'world_position': entrance_world, 'pixel_position': entrance,
                     'approach_world_direction': direction, 'interaction': 'scene_transition_marker'},
        'opening_visibility': visibility,
        'face_ids': {str(k): v[0] for k, v in PALETTE.items()},
        'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.glob('*.png'))},
        'review': {'structure': 'pending', 'art': 'not_generated', 'occlusion': 'not_tested'},
        'collision_enabled': False,
    }
    atomic(output/'structure.json', result)
    return result
