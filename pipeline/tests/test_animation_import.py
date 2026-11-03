"""Exercise the real Godot importer with compensating motion at several scales."""
import base64
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from animation_import import prepare, PLUGIN

GODOT = os.environ.get('GODOT_BIN', '/Applications/Godot.app/Contents/MacOS/Godot')


def fixture(path, height):
    times = [i / 5 for i in range(6)]
    angles = [0, .1, 0, -.1, 0, 0]
    hips = [(height / 2 * math.sin(a), 0, 0) for a in angles]
    rotations = [(0, 0, math.sin(a / 2), math.cos(a / 2)) for a in angles]
    data = bytearray()
    views, accessors = [], []
    for values, kind in (([(t,) for t in times], 'SCALAR'), (hips, 'VEC3'), (rotations, 'VEC4')):
        raw = b''.join(struct.pack('<' + 'f' * len(row), *row) for row in values)
        views.append({'buffer': 0, 'byteOffset': len(data), 'byteLength': len(raw)})
        data.extend(raw)
        accessor = {'bufferView': len(views)-1, 'componentType': 5126, 'count': len(values), 'type': kind}
        if kind == 'SCALAR': accessor.update(min=[0], max=[1])
        accessors.append(accessor)
    document = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}],
        'nodes': [{'name': 'Hip', 'children': [1]}, {'name': 'Leg', 'children': [2]},
                  {'name': 'Foot', 'translation': [0, height / 2, 0]}],
        'buffers': [{'byteLength': len(data), 'uri': 'data:application/octet-stream;base64,' + base64.b64encode(data).decode()}],
        'bufferViews': views, 'accessors': accessors,
        'animations': [{'name': 'contact', 'samplers': [{'input': 0, 'output': 1}, {'input': 0, 'output': 2}],
            'channels': [{'sampler': 0, 'target': {'node': 0, 'path': 'translation'}},
                         {'sampler': 1, 'target': {'node': 1, 'path': 'rotation'}}]}]}
    path.write_text(json.dumps(document))


PROBE = '''extends SceneTree
func _initialize(): call_deferred("run")
func run():
    var results = {}
    for file in ["tiny", "human", "large"]:
        var node = load("res://" + file + ".gltf").instantiate()
        root.add_child(node)
        var player = node.find_child("*", true, false) as AnimationPlayer
        for child in node.find_children("*", "AnimationPlayer", true, false):
            player = child
        var clip = ""
        for name in player.get_animation_list():
            if name != "RESET": clip = name
        player.play(clip)
        player.advance(0)
        player.pause()
        var samples = []
        for i in 6:
            player.seek(float(i)/5, true)
            var hip = node.find_child("Hip", true, false)
            var foot = node.find_child("Foot", true, false)
            samples.append([hip.position.x, foot.global_position.x])
        results[file] = samples
        node.free()
    var output = FileAccess.open("res://samples.json", FileAccess.WRITE)
    output.store_string(JSON.stringify(results))
    quit()
'''


class AnimationImportTests(unittest.TestCase):
    def test_staging_is_idempotent_and_preserves_other_plugins(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = root/'project.godot'
            p.write_text('config_version=5\n[editor_plugins]\nenabled=PackedStringArray("res://other/plugin.cfg")\n[rendering]\nx=1\n')
            prepare(root)
            first = p.read_text()
            prepare(root)
            self.assertEqual(first, p.read_text())
            self.assertEqual(first.count(PLUGIN), 1)
            self.assertIn('"res://other/plugin.cfg"', first)
            self.assertIn('[rendering]\nx=1', first)

    @unittest.skipUnless(Path(GODOT).is_file() or shutil.which(GODOT), 'Godot unavailable')
    def test_real_import_preserves_contact_and_travel_at_all_scales(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'project.godot').write_text('config_version=5\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n')
            sizes = {'tiny': .017, 'human': 1.7, 'large': 170}
            for name, height in sizes.items(): fixture(root/(name+'.gltf'), height)
            (root/'probe.gd').write_text(PROBE)
            def run(*args):
                result = subprocess.run([GODOT, '--headless', '--path', str(root), *args], capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn('ERROR:', result.stderr)
            # Control reproduces the bug using Godot's default import settings.
            run('--editor', '--import')
            run('--script', 'res://probe.gd')
            control = json.loads((root/'samples.json').read_text())
            self.assertGreater(max(abs(row[1]) for row in control['tiny']), .0001)
            # Rebuild from the same sources with the production staging policy.
            prepare(root)
            shutil.rmtree(root/'.godot')
            for path in root.glob('*.import'): path.unlink()
            run('--editor', '--import')
            run('--script', 'res://probe.gd')
            fixed = json.loads((root/'samples.json').read_text())
            for name, height in sizes.items():
                with self.subTest(scale=height):
                    self.assertLess(max(abs(row[1]) for row in fixed[name]), height * 1e-5)
                    self.assertGreater(max(abs(row[0]) for row in fixed[name]), height * .049)


if __name__ == '__main__': unittest.main()
