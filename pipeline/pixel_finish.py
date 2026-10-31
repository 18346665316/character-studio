"""A shared batch palette and alpha outline, with shared colors and outline at the final display resolution."""
from pathlib import Path
import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation


def finish_batch(sheets, colors=64, frame_size=128):
    images = [Image.open(p).convert('RGBA') for p in sheets]
    # Resize RGBA tiles before quantization/outline. Pillow uses premultiplied
    # alpha for RGBA BOX filtering, preventing transparent RGB from darkening edges.
    resized = []
    for image in images:
        source_size = image.height
        if image.width % source_size or frame_size > source_size:
            raise ValueError('Invalid source tile size or requested upscale')
        target = Image.new('RGBA', (image.width // source_size * frame_size, frame_size))
        for i, start in enumerate(range(0, image.width, source_size)):
            tile = image.crop((start, 0, start + source_size, source_size))
            tile = tile.resize((frame_size, frame_size), Image.Resampling.BOX)
            target.paste(tile, (i * frame_size, 0))
        resized.append(target)
    images = resized
    samples = []
    for image in images:
        pixels = np.array(image)
        rgb = pixels[pixels[:, :, 3] >= 128, :3]
        if len(rgb):
            samples.append(rgb[::max(1, len(rgb) // 60000)])
    if not samples:
        raise ValueError('No foreground colors to create a palette')
    pixels = np.concatenate(samples)
    sample_image = Image.fromarray(pixels.reshape((-1, 1, 3)), 'RGB')
    palette = sample_image.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    for path, image in zip(sheets, images):
        rgb = np.array(image.convert('RGB').quantize(palette=palette, dither=Image.Dither.NONE).convert('RGB'))
        original = np.array(image)
        output = np.zeros_like(original)
        # Process every tile individually; dilation must not leak into the next frame.
        for start in range(0, image.width, frame_size):
            mask = original[:, start:start + frame_size, 3] >= 128
            outline = binary_dilation(mask) & ~mask
            tile = output[:, start:start + frame_size]
            tile[mask, :3] = rgb[:, start:start + frame_size][mask]
            tile[mask, 3] = 255
            tile[outline] = (25, 29, 32, 255)
        Image.fromarray(output, 'RGBA').save(path)
    return {'palette_colors': colors, 'outline_pixels': 1, 'dither': False,
            'palette_scope': 'whole_batch', 'alpha_threshold': 128,
            'frame_size': frame_size, 'coverage_filter': 'premultiplied_rgba_box',
            'outline_stage': 'after_resize'}
