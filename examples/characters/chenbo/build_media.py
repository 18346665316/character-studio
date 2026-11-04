"""Compose README media from this sample's existing assets and Godot captures."""
import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--frames', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--font', type=Path, help='Optional TrueType font for the static diagram')
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)


def font(size):
    if args.font:
        return ImageFont.truetype(str(args.font), size)
    return ImageFont.load_default(size=size)


# Presentation only: do not retouch, recolor, or interpolate the animation frames.
canvas = Image.new('RGB', (1280, 480), '#e6eceb')
draw = ImageDraw.Draw(canvas)
draw.text((30, 22), 'SOURCE ART  >  PREPARED MODEL  >  EXPORTED SPRITE FRAMES', font=font(26), fill='#17332f')
for x, label in [(30, '01  Source art'), (445, '02  Model preview'), (860, '03  Actual output frames')]:
    draw.text((x, 78), label, font=font(21), fill='#17332f')
for filename, x in [('reference.png', 60), ('model-preview.png', 465)]:
    im = Image.open(BASE / filename).convert('RGB')
    im.thumbnail((300, 300), Image.Resampling.LANCZOS)
    canvas.paste(im, (x, 116))
char = BASE / 'character_assets/character-50e87c3235'
import json
manifest = json.loads((char / 'manifest.json').read_text())
for action, x in [('walk', 905), ('run', 1085)]:
    info = manifest['actions'][action]
    sheet = Image.open(char / info['texture']).convert('RGBA')
    size = info['frame_size']
    # Frame zero is a real exported pose, not a newly drawn sprite.
    im = sheet.crop((0, 0, size, size)).resize((size * 2, size * 2), Image.Resampling.NEAREST)
    anchor = info['anchor_px']
    canvas.paste(im, (int(x - anchor[0] * 2), int(378 - anchor[1] * 2)), im)
    draw.text((x - 20, 398), action, font=font(17), fill='#17332f')
draw.text((30, 448), 'Existing production snapshot. Model shape and details differ from the source art.', font=font(17), fill='#44665f')
canvas.save(args.output / 'chenbo-pipeline.png', optimize=True)

files = sorted(args.frames.glob('frame-*.png'))
if len(files) != 120:
    raise SystemExit(f'Expected 120 captured frames; found {len(files)}')
# GIF durations are in centiseconds: 80 + 80 + 90 ms = 250 ms per three frames.
# One shared palette avoids per-frame color flicker. The source PNG files stay intact.
contact = Image.new('RGB', (320 * 6, 155 * 4))
for i in range(24):
    with Image.open(files[i * 5]) as im:
        contact.paste(im.convert('RGB').resize((320, 155)), ((i % 6) * 320, (i // 6) * 155))
palette = contact.quantize(colors=256)
frames = []
for file in files:
    with Image.open(file) as im:
        frames.append(im.convert('RGB').quantize(palette=palette, dither=Image.Dither.NONE))
frames[0].save(args.output / 'chenbo-actions.gif', save_all=True, append_images=frames[1:],
               duration=[80, 80, 90] * 40, loop=0, optimize=True, disposal=1)
print('Wrote actual Godot playback GIF (10 s) and source/model/frame diagram')
