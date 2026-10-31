"""Offline regression checks for asset isolation and delivery promotion."""
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw

spec = importlib.util.spec_from_file_location('studio_core', Path(__file__).resolve().parents[1] / 'studio_core.py')
studio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(studio)


def sheet(path, animated=True, blank=False):
    image = Image.new('RGBA', (1280, 128))
    if not blank:
        draw = ImageDraw.Draw(image)
        for i in range(10):
            offset = i if animated else 0
            draw.rectangle((i * 128 + 30 + offset, 30, i * 128 + 60 + offset, 100), fill='red')
    image.save(path)


class Boundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patch = patch.object(studio, 'BASE_DIR', self.root)
        self.patch.start()
        self.progress_patch = patch("progress.BASE_DIR", self.root)
        self.progress_patch.start()
        self.inspect_patch = patch.object(studio, 'inspect_download', return_value={
            'textured_surfaces': 1, 'animations': [{'changing_tracks': 12}]})
        self.inspect_patch.start()
        template = self.root / 'pipeline/godot'
        template.mkdir(parents=True)
        (template / 'project.godot').write_text('config_version=5\n')
        source = studio.workspace('hero') / 'animations/run1'
        source.mkdir(parents=True)
        (source / 'run.fbx').write_bytes(b'fixture-selected-animation')
        (source / 'ignored.fbx').write_bytes(b'not-in-receipt')
        (source / 'batch.json').write_text(json.dumps({
            'character': 'hero', 'batch': 'run1',
            'files': {'run.fbx': studio.digest(source / 'run.fbx')}
        }))

    def tearDown(self):
        self.inspect_patch.stop()
        self.progress_patch.stop()
        self.patch.stop()
        self.temp.cleanup()

    def renderer(self, animated=True, fail=False):
        def fake_run(args, **kwargs):
            project = Path(args[args.index('--path') + 1])
            self.assertEqual(sorted(p.name for p in (project / 'animations').iterdir()), ['run.fbx'])
            if '--output' in args:
                if fail:
                    raise studio.subprocess.CalledProcessError(1, args)
                output = Path(args[args.index('--output') + 1])
                sheet(output / 'run_spritesheet.png', animated=animated)
                (output / 'run_render.json').write_text(json.dumps({
                    'duration_seconds': 1.0, 'frame_count': 10, 'fps': 10.0, 'view': 'three_quarter'}))
        return fake_run

    def test_nonempty_and_moving_gate(self):
        path = self.root / 'sheet.png'
        sheet(path)
        self.assertEqual(studio.validate_sheet(path)['unique_frames'], 10)
        for options in [{'animated': False}, {'blank': True}]:
            sheet(path, **options)
            with self.assertRaises(ValueError):
                studio.validate_sheet(path)

    def test_only_selected_batch_published_with_manifest(self):
        with patch.object(studio.subprocess, 'run', side_effect=self.renderer()):
            destination = studio.bake('hero', 'run1')
        self.assertEqual(sorted(p.name for p in destination.iterdir()), ['manifest.json', 'run_preview.gif', 'run_render.json', 'run_spritesheet.png'])
        manifest = json.loads((destination / 'manifest.json').read_text())
        self.assertEqual(list(manifest['source']['files']), ['run.fbx'])

    def test_static_output_never_published(self):
        with patch.object(studio.subprocess, 'run', side_effect=self.renderer(animated=False)):
            with self.assertRaises(ValueError):
                studio.bake('hero', 'run1')
        self.assertFalse((self.root / 'deliverables').exists())
        self.assertEqual(len(list((self.root / '.local/jobs').glob('*/staging/*.png'))), 1)

    def test_renderer_failure_never_published(self):
        with patch.object(studio.subprocess, 'run', side_effect=self.renderer(fail=True)):
            with self.assertRaises(studio.subprocess.CalledProcessError):
                studio.bake('hero', 'run1')
        self.assertFalse((self.root / 'deliverables').exists())

    def test_changed_or_foreign_source_rejected_before_import(self):
        source = studio.workspace('hero') / 'animations/run1'
        (source / 'run.fbx').write_bytes(b'changed')
        with patch.object(studio.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                studio.bake('hero', 'run1')
            run.assert_not_called()
        with self.assertRaises(ValueError):
            studio.bake('other_hero', 'run1')

    def test_legacy_requires_explicit_registration(self):
        receipt = studio.workspace('hero') / 'animations/run1/batch.json'
        receipt.unlink()
        with self.assertRaises(ValueError):
            studio.bake('hero', 'run1')

    def test_white_model_and_cropped_frames_are_rejected(self):
        path = self.root / 'bad.png'
        sheet(path)
        image = Image.open(path).convert('RGBA')
        pixels = image.load()
        for y in range(image.height):
            for x in range(image.width):
                if pixels[x, y][3]:
                    pixels[x, y] = (240, 240, 240, 255)
        image.save(path)
        with self.assertRaisesRegex(ValueError, '白模|灰模'):
            studio.validate_sheet(path)
        sheet(path)
        image = Image.open(path).convert('RGBA')
        ImageDraw.Draw(image).point((0, 40), fill='red')
        image.save(path)
        with self.assertRaisesRegex(ValueError, '裁切'):
            studio.validate_sheet(path)

    def test_untextured_source_never_reaches_renderer(self):
        self.inspect_patch.stop()
        with patch.object(studio, 'inspect_download', return_value={
                'textured_surfaces': 0, 'animations': [{'changing_tracks': 12}]}), \
             patch.object(studio.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, '缺失贴图'):
                studio.bake('hero', 'run1')
            run.assert_not_called()
        self.inspect_patch.start()

    def test_gif_preserves_different_clip_durations(self):
        path = self.root / 'sheet.png'
        sheet(path)
        for seconds in [0.63, 8.33]:
            output = self.root / f'{seconds}.gif'
            studio.make_preview(path, output, seconds)
            with Image.open(output) as gif:
                durations = []
                for i in range(gif.n_frames):
                    gif.seek(i)
                    durations.append(gif.info['duration'])
            self.assertAlmostEqual(sum(durations), seconds * 1000, delta=10)

    def test_path_traversal_rejected(self):
        for value in ['../hero', '/tmp/hero', 'hero/other', '']:
            with self.assertRaises(studio.argparse.ArgumentTypeError):
                studio.slug(value)


if __name__ == '__main__':
    unittest.main()
