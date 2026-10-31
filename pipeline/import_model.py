"""Import self-contained, unrigged textured GLB without image reconstruction."""
import json
from pathlib import Path
import shutil
import struct
import uuid
import zipfile
import numpy as np
import trimesh
from asset_inspector import BASE_DIR
from model_optimization import digest


def validate_glb(content):
    if len(content)<20:raise ValueError('GLB 文件不完整')
    magic,version,total=struct.unpack_from('<III',content)
    if magic!=0x46546c67 or version!=2 or total!=len(content):raise ValueError('需要完整的 glTF 2.0 GLB')
    length,kind=struct.unpack_from('<II',content,12)
    if kind!=0x4e4f534a or length>len(content)-20:raise ValueError('GLB JSON 无效')
    try:doc=json.loads(content[20:20+length])
    except (ValueError,UnicodeError):raise ValueError('GLB JSON 无效')
    if doc.get('skins') or doc.get('animations'):raise ValueError('当前导入仅支持未绑定、无动画的模型；已有骨骼不能在此入口保留')
    for item in doc.get('buffers',[])+doc.get('images',[]):
        if item.get('uri') and not item['uri'].startswith('data:'):raise ValueError('GLB 必须内嵌全部贴图与网格，不能引用外部文件')
    if len(doc.get('materials',[]))!=1:raise ValueError('第一版只支持单材质人物模型')
    return doc


def import_character(root,character,source,up='Y',yaw=0):
    root=Path(root);source=Path(source);validate_glb(source.read_bytes())
    scene=trimesh.load(source,force='scene',process=False)
    mesh=scene.to_geometry()
    if len(mesh.faces)>3_000_000 or len(mesh.faces)<1:raise ValueError('模型面数须在 1–300万之间')
    if mesh.visual.kind!='texture' or mesh.visual.uv is None:raise ValueError('模型缺少 UV 贴图')
    material=mesh.visual.material
    image=getattr(material,'baseColorTexture',None) or getattr(material,'image',None)
    if image is None:raise ValueError('模型缺少基础颜色贴图')
    rotations={'Y':np.eye(4),'-Y':trimesh.transformations.rotation_matrix(np.pi,[1,0,0]),'Z':trimesh.transformations.rotation_matrix(-np.pi/2,[1,0,0]),'-Z':trimesh.transformations.rotation_matrix(np.pi/2,[1,0,0]),'X':trimesh.transformations.rotation_matrix(np.pi/2,[0,0,1]),'-X':trimesh.transformations.rotation_matrix(-np.pi/2,[0,0,1])}
    if up not in rotations or yaw not in (0,90,180,270):raise ValueError('模型朝向设置无效')
    mesh.apply_transform(rotations[up]);mesh.apply_transform(trimesh.transformations.rotation_matrix(np.radians(yaw),[0,1,0]))
    bounds=mesh.bounds;height=float(bounds[1,1]-bounds[0,1])
    if not np.isfinite(mesh.vertices).all() or height<1e-8:raise ValueError('模型尺寸无效')
    mesh.apply_translation([-bounds[:,0].mean(),-bounds[0,1],-bounds[:,2].mean()]);mesh.apply_scale(1.7/height)
    mesh.visual.material=trimesh.visual.material.SimpleMaterial(image=image.convert('RGB'),diffuse=[255]*4,name='body')
    ws=root/'workspaces'/character;models=ws/'models';models.mkdir(exist_ok=True)
    if (models/f'{character}.obj').exists():raise ValueError('导入模型必须创建独立人物，不能覆盖现有人物')
    staging=models/('import-'+uuid.uuid4().hex[:12]);staging.mkdir()
    mesh.export(staging/'preview.glb');image.convert('RGB').save(staging/'albedo.png')
    with (staging/'model.obj').open('w') as f:
        f.write('mtllib model.mtl\no body\n')
        for v in mesh.vertices:f.write('v %.9f %.9f %.9f\n'%tuple(v))
        for uv in mesh.visual.uv:f.write('vt %.9f %.9f\n'%tuple(uv))
        f.write('usemtl body\n')
        for face in mesh.faces+1:f.write('f '+' '.join(f'{v}/{v}' for v in face)+'\n')
    (staging/'model.mtl').write_text('newmtl body\nKd 1 1 1\nKs 0 0 0\nillum 1\nmap_Kd albedo.png\n')
    with zipfile.ZipFile(staging/'mixamo.zip','w',zipfile.ZIP_DEFLATED) as bundle:
        for name in ('model.obj','model.mtl','albedo.png'):bundle.write(staging/name,name)
    from preview_model import preview
    preview(root,staging)
    canonical=models/f'{character}.obj'
    # Publish only after conversion and preview pass. The source GLB stays immutable.
    shutil.copy2(staging/'model.obj',canonical)
    receipt={'source':str(source),'source_sha256':digest(canonical),'import_source_sha256':digest(source),'triangles_before':len(mesh.faces),'triangles_after':len(mesh.faces),'height_meters':1.7,'up_axis':'Y','texture_resolution':image.width,'visual_review':'pending','origin':'import_glb','import_up':up,'import_yaw':yaw,'cleanup':'No decimation or fragment removal; normalized to 1.7m Y-up. Imported base-color texture only.'}
    (staging/'prepare.json').write_text(json.dumps(receipt,indent=2)+'\n')
    dest=models/'prepared'/uuid.uuid4().hex[:12];dest.parent.mkdir(exist_ok=True);staging.rename(dest)
    return dest
