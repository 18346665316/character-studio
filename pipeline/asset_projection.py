"""Shared 2:1 dimetric contract. Object artwork is never geometrically warped."""
from PIL import Image

ISOMETRIC='isometric_2_1'


def validate_projection(value, default):
    if not isinstance(value,str) or value not in (default,ISOMETRIC):
        raise ValueError('未知投影规格')
    return value


def contract(width=128):
    return {'id':ISOMETRIC,'ratio':[2,1],'cell_px':[width,width//2],
            'basis_px':[[width/2,width/4],[-width/2,width/4]],
            'camera':{'azimuth_deg':45,'elevation_deg':30.0},
            'screen_axis_angle_deg':26.565051,'lighting':'upper_left','coordinate_system':'screen_x_right_y_down',
            'art_angle_review':'pending'}


def diamond(image, width):
    """Pixel-center inverse mapping fills a half-open rhombus without edge cracks."""
    height=width//2
    # u=x/width+y/height-.5; v=-x/width+y/height+.5
    source=image.convert('RGBA')
    return source.transform((width,height),Image.Transform.AFFINE,
        (source.width/width,source.width/height,-source.width/2,
         -source.height/width,source.height/height,source.height/2),
        Image.Resampling.BICUBIC,fillcolor=(0,0,0,0))


def surface_exports(folder, images, source_size):
    width=source_size*2;height=source_size
    projected=[diamond(image,width) for image in images]
    atlas=Image.new('RGBA',(width*len(images),height))
    entries=[]
    for i,image in enumerate(projected):
        relative=f'tiles/isometric_ground_v{i}.png'
        image.save(folder/relative);atlas.paste(image,(i*width,0))
        entries.append({'id':i,'image':relative,'atlas_rect_px':[i*width,0,width,height],
                        'anchor_px':[width/2,height/2]})
    atlas.save(folder/'isometric_atlas.png')
    preview=Image.new('RGBA',(width*8,height*8),(39,47,52,255))
    for y in range(7):
        for x in range(7):
            image=projected[(x*3+y*5)%len(projected)]
            preview.alpha_composite(image,(int((x-y)*width/2+width*3.5),int((x+y)*height/2+height/2)))
    preview.convert('RGB').save(folder/'isometric_preview.png')
    return {**contract(width),'atlas':'isometric_atlas.png','preview':'isometric_preview.png',
            'variants':entries,'ground_polygon_px':[[width/2,0],[width,height/2],[width/2,height],[0,height/2]],
            'source':'program_projection_of_top_down_texture','collision':False}
