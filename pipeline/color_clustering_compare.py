"""Non-destructive shared-palette experiment on finished sprite sheets."""
import argparse,hashlib,json,shutil
from pathlib import Path
import numpy as np
from PIL import Image
from sheet_layout import tiles


from color_clustering import make_palette,apply_palette


def build(source,output):
    source=Path(source).resolve();output=Path(output).resolve()
    if source==output or source in output.parents:raise ValueError('Comparison must be outside source delivery')
    data=json.loads((source/'manifest.json').read_text())
    names=[k for k,v in data.items() if k.endswith('_spritesheet.png') and v.get('body_height_px')==96]
    if not names:raise ValueError('请选择包含 96px 图集的交付目录')
    sheets=[source/name for name in names];output.mkdir(parents=True,exist_ok=True)
    report={'schema':1,'source':str(source),'palette_scope':'all_selected_actions','dither':False,'alpha':'unchanged','variants':{},'source_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sheets}}
    for variant,colors in [('original',None),('64',64),('32',32)]:
        folder=output/variant;folder.mkdir(exist_ok=True)
        palette=make_palette(sheets,data,colors) if colors else None
        result={'palette':palette.tolist() if colors else None,'clips':{}}
        for path in sheets:
            if colors:result['clips'][path.name]=apply_palette(path,folder/path.name,palette)
            else:shutil.copy2(path,folder/path.name)
            result['clips'].setdefault(path.name,{})['png_bytes']=(folder/path.name).stat().st_size
        report['variants'][variant]=result
    clips={name.removesuffix('_spritesheet.png'):{**data[name],'sheet':name} for name in names}
    (output/'clips.json').write_text(json.dumps(clips))
    (output/'report.json').write_text(json.dumps(report,indent=2))
    shutil.copy2(Path(__file__).parent/'palette_compare.html',output/'index.html')
    # Static contact sheet shows identical frames at the same integer zoom.
    size=max(data[n]['frame_width'] for n in names);board=Image.new('RGBA',(size*3,size*len(names)), '#dfe4e1')
    for row,name in enumerate(names):
        cell=data[name]['frame_width'];frame=min(10,data[name]['frame_count']-1);cols=data[name]['columns']
        for column,variant in enumerate(('original','64','32')):
            with Image.open(output/variant/name) as image:
                tile=image.crop((frame%cols*cell,frame//cols*cell,frame%cols*cell+cell,frame//cols*cell+cell))
                board.alpha_composite(tile,(column*size,row*size))
    board.convert('RGB').save(output/'contact.png')
    return output

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source');parser.add_argument('output');args=parser.parse_args()
    print(build(args.source,args.output))
