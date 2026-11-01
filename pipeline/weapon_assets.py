"""Independent, immutable weapon assets. Model basis: +Y tip, +Z face, length=1.
Calibration is explicit; no character normalization or component removal is used.
"""
from task_lock import serialized
import argparse
import hashlib
import json
import math
from pathlib import Path
import secrets
import shutil


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def asset_dir(root, identity):
    from mixamo_state import character_name
    character_name(identity)
    base=Path(root)/'weapons'
    path=base/identity
    if base.is_symlink() or path.is_symlink() or path.resolve().parent!=base.resolve():
        raise ValueError('非法武器资产路径')
    return path


def load(root, identity, confirmed=False):
    path=asset_dir(root,identity)
    data=json.loads((path/'weapon.json').read_text())
    if data.get('schema')!=1 or data.get('id')!=identity:
        raise ValueError('武器资产记录无效')
    validate_calibration(data.get('length_meters'),data.get('grip'))
    model=path/'model.glb'
    if model.is_symlink() or not model.is_file() or digest(model)!=data.get('model_sha256'):
        raise ValueError('武器模型已变化，请重新导入确认')
    if confirmed and data.get('confirmed') is not True:
        raise ValueError('请先检查并确认武器握点与朝向')
    return data


def catalog(root):
    result=[]
    for path in sorted((Path(root)/'weapons').glob('*/weapon.json'),reverse=True):
        try: result.append(load(root,path.parent.name))
        except (ValueError,OSError,KeyError,TypeError): continue
    return result


def validate_calibration(length, grip):
    if isinstance(length,bool) or not isinstance(length,(int,float)) or not math.isfinite(length) or not .1<=length<=2:
        raise ValueError('武器总长需为0.1–2米')
    if not isinstance(grip,list) or len(grip)!=3 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in grip):
        raise ValueError('握点需为三个有限数值')
    if not (-.3<=grip[0]<=.3 and 0<=grip[1]<=1 and -.3<=grip[2]<=.3):
        raise ValueError('握点超出武器范围')


@serialized(lambda root, *args, **kwargs: root)
def calibrate(root, identity, length, grip):
    data=load(root,identity)
    validate_calibration(length,grip)
    new_id='weapon-'+secrets.token_hex(6)
    source=asset_dir(root,identity);target=asset_dir(root,new_id)
    target.mkdir(parents=True)
    for name in ('model.glb','front.png','contact.png','original.png','processed.png'):
        if (source/name).is_symlink(): raise ValueError('武器文件不允许链接')
        if (source/name).is_file(): shutil.copy2(source/name,target/name)
    data.update(id=new_id,parent=identity,length_meters=length,grip=grip,confirmed=True)
    (target/'weapon.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    return data


@serialized(lambda root, *args, **kwargs: root)
def create(root, source, display_name, image=None):
    """Import raw TSR OBJ from the tested upright image. Does not claim inferred real size."""
    import numpy as np
    import trimesh
    from PIL import Image,ImageDraw
    mesh=trimesh.load(source,force='mesh',process=False)
    if mesh.visual.kind!='vertex' or not len(mesh.faces):
        raise ValueError('需要含顶点颜色的TripoSR模型')
    # TSR raw frame: Z up, X depth. Explicit basis, not PCA sign guessing.
    v=np.asarray(mesh.vertices)[:,[1,2,0]].copy()
    low,high=v.min(axis=0),v.max(axis=0)
    height=float(high[1]-low[1])
    if height<=0: raise ValueError('武器长度无效')
    v=(v-np.array([(low[0]+high[0])/2,low[1],(low[2]+high[2])/2]))/height
    mesh.vertices=v
    identity='weapon-'+secrets.token_hex(6);target=asset_dir(root,identity);target.mkdir(parents=True)
    mesh.export(target/'model.glb')
    colors=np.asarray(mesh.visual.vertex_colors[:,:3]);brown=(colors[:,0]>colors[:,2]*1.15)&(colors[:,0]<130)&(v[:,1]<.4)
    grip_y=float(np.median(v[brown,1])) if np.count_nonzero(brown)>20 else .13
    data={'schema':1,'id':identity,'name':display_name,'model_sha256':digest(target/'model.glb'),
          'source_sha256':digest(source),'confirmed':False,'length_meters':.85,'grip':[0,grip_y,0],
          'basis':'+Y blade tip; +Z blade face; normalized model length=1',
          'triangles':len(mesh.faces),'units_note':'Length is a user setting, not inferred from the image.'}
    (target/'weapon.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    if image: shutil.copy2(image,target/'original.png')
    faces=np.asarray(mesh.faces);fc=colors[faces].mean(axis=1);sheet=Image.new('RGB',(1200,1200),'#edf0ea')
    for i in range(8):
        angle=i*np.pi/4;c,s=np.cos(angle),np.sin(angle)
        pv=np.column_stack([v[:,0]*c+v[:,2]*s,v[:,1],-v[:,0]*s+v[:,2]*c])
        xy=np.column_stack([150+pv[:,0]*490,550-pv[:,1]*490]);tile=Image.new('RGB',(300,600),'#e7ece5');draw=ImageDraw.Draw(tile)
        # Render separate front at larger resolution below; contact is 4x2.
        for f in np.argsort(pv[faces,2].mean(axis=1)):
            draw.polygon([tuple(p) for p in xy[faces[f]]],fill=tuple(fc[f].astype(int)))
        draw.text((10,10),f'{i*45} deg',fill='#304b39')
        if i==0:
            tile.save(target/'front.png')
        sheet.paste(tile,((i%4)*300,(i//4)*600))
    sheet.save(target/'contact.png')
    return data




def prepare_white_background(source, destination):
    """Remove only boundary-connected near-white pixels; preserve gray metal."""
    import numpy as np
    from scipy import ndimage
    from PIL import Image
    image=Image.open(source).convert('RGB');pixels=np.asarray(image)
    white=(pixels.min(axis=2)>242)&(np.ptp(pixels,axis=2)<16)
    labels,_=ndimage.label(white)
    border=np.unique(np.concatenate([labels[0],labels[-1],labels[:,0],labels[:,-1]]))
    foreground=~np.isin(labels,border[border!=0])
    y,x=np.nonzero(foreground)
    if not len(x): raise ValueError('原画没有可分离的主体')
    rgba=Image.fromarray(np.dstack([pixels,foreground.astype(np.uint8)*255]))
    cut=rgba.crop((int(x.min()),int(y.min()),int(x.max()+1),int(y.max()+1)))
    side=math.ceil(max(cut.size)/.85)
    canvas=Image.new('RGBA',(side,side),(128,128,128,255))
    canvas.alpha_composite(cut,((side-cut.width)//2,(side-cut.height)//2))
    Path(destination).parent.mkdir(parents=True,exist_ok=True)
    canvas.convert('RGB').save(destination)
    return destination


@serialized(lambda root, *args, **kwargs: root)
def generate(root, source, display_name, job):
    """White-background upright sword MVP. Retain reconstruction and every component."""
    import os
    import subprocess
    root=Path(root);job=Path(job);job.mkdir(parents=True,exist_ok=True)
    prepared=prepare_white_background(source,job/'input.png')
    output=job/'reconstruction';(output/'0').mkdir(parents=True,exist_ok=True)
    mesh=output/'0/mesh.obj'
    request={'image_sha256':digest(source),'name':display_name,'preset':'upright-white-sword-v1'}
    request_path=job/'request.json'
    if request_path.exists() and json.loads(request_path.read_text())!=request:
        raise ValueError('武器输入已变化，请新建任务')
    request_path.write_text(json.dumps(request,ensure_ascii=False))
    if not mesh.is_file():
        subprocess.run([str(root/'.local/python/bin/python3'),str(root/'vendor/TripoSR/run.py'),str(prepared),
                        '--output-dir',str(output),'--model-save-format','obj','--no-remove-bg'],
                       cwd=root,env={**os.environ,'HF_HUB_OFFLINE':'1'},check=True)
    result=create(root,mesh,display_name,source)
    # Store the exact preprocessed image for user inspection.
    shutil.copy2(prepared,asset_dir(root,result['id'])/'processed.png')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='导入已重建的独立武器（竖直原画，TripoSR原始Z-up坐标）')
    parser.add_argument('source');parser.add_argument('--name',required=True);parser.add_argument('--image')
    args=parser.parse_args()
    print(json.dumps(create(Path(__file__).resolve().parent.parent,args.source,args.name,args.image),ensure_ascii=False,indent=2))
