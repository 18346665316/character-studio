"""Blender-only entrypoint: static textured candidates, shared cameras, no rig mutation."""
import argparse
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector


def triangles(obj):
    obj.data.calc_loop_triangles()
    return len(obj.data.loop_triangles)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source',required=True)
    p.add_argument('--output',required=True)
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:])
    output=Path(args.output)
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=args.source)
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    if len(meshes)!=1 or any(o.type=='ARMATURE' for o in bpy.context.scene.objects):
        raise ValueError('Only a single unbound prepared character mesh is supported')
    original=meshes[0];original.name='SM_Character_Original'
    bpy.context.view_layer.objects.active=original
    bpy.ops.object.select_all(action='DESELECT');original.select_set(True)
    bpy.ops.object.transform_apply(location=False,rotation=True,scale=True)
    before=triangles(original)
    # glTF splits vertices at UV seams. Weld coincident geometry while preserving
    # per-corner UVs so collapse does not tear the texture atlas into holes.
    bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles(threshold=0.0000001)
    bpy.ops.object.mode_set(mode='OBJECT')
    # Shared texture and emission shading make color/geometry comparison deterministic.
    if len(original.data.materials)!=1 or not original.data.uv_layers.active:raise ValueError('Expected one material and a UV atlas')
    for mat in original.data.materials:
        textures=[n for n in mat.node_tree.nodes if n.type=='TEX_IMAGE' and n.image]
        if len(textures)!=1:raise ValueError('Expected one baked albedo texture per material')
        albedo=textures[0].image
        mat.node_tree.nodes.clear()
        tex=mat.node_tree.nodes.new('ShaderNodeTexImage');tex.image=albedo
        emission=mat.node_tree.nodes.new('ShaderNodeEmission')
        out=mat.node_tree.nodes.new('ShaderNodeOutputMaterial')
        mat.node_tree.links.new(tex.outputs['Color'],emission.inputs['Color'])
        mat.node_tree.links.new(emission.outputs[0],out.inputs['Surface'])
    scene=bpy.context.scene
    engines={e.identifier for e in scene.render.bl_rna.properties['engine'].enum_items}
    scene.render.engine='BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in engines else 'BLENDER_EEVEE'
    scene.render.resolution_x=512;scene.render.resolution_y=512;scene.render.resolution_percentage=100
    scene.render.film_transparent=True;scene.render.image_settings.file_format='PNG'
    scene.view_settings.view_transform='Standard'
    camera_data=bpy.data.cameras.new('CAM_Comparison');camera=bpy.data.objects.new('CAM_Comparison',camera_data);scene.collection.objects.link(camera);scene.camera=camera
    camera_data.type='ORTHO';camera_data.ortho_scale=2.05
    center=Vector((0,0,.85))
    variants=[('original',original,before)]
    for target in (30000,15000):
        if target>=before:continue
        obj=original.copy();obj.data=original.data.copy();scene.collection.objects.link(obj);obj.name='SM_Character_'+str(target)
        bpy.context.view_layer.objects.active=obj
        modifier=obj.modifiers.new('Reduce triangles','DECIMATE');modifier.ratio=target/before;modifier.use_collapse_triangulate=True
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        for slot in obj.material_slots:slot.material=slot.material.copy()
        variants.append((str(target),obj,target))
    reports=[]
    for key,obj,target in variants:
        dest=output/key;dest.mkdir(parents=True,exist_ok=False)
        for _,other,_ in variants:other.hide_render=other!=obj
        for angle in (0,90,180,270):
            a=math.radians(angle);camera.location=center+Vector((3*math.sin(a),-3*math.cos(a),.1));camera.rotation_euler=(center-camera.location).to_track_quat('-Z','Y').to_euler()
            scene.render.filepath=str(dest/f'view_{angle}.png');bpy.ops.render.render(write_still=True)
        if key!='original':
            bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);bpy.context.view_layer.objects.active=obj
            # Restore production PBR material; comparison emission is never exported.
            for mat in obj.data.materials:
                tex=next(n for n in mat.node_tree.nodes if n.type=='TEX_IMAGE')
                out=next(n for n in mat.node_tree.nodes if n.type=='OUTPUT_MATERIAL')
                bsdf=mat.node_tree.nodes.new('ShaderNodeBsdfPrincipled');bsdf.inputs['Roughness'].default_value=1
                mat.node_tree.links.new(tex.outputs['Color'],bsdf.inputs['Base Color']);mat.node_tree.links.new(bsdf.outputs[0],out.inputs['Surface'])
            bpy.ops.export_scene.gltf(filepath=str(dest/'preview.glb'),use_selection=True,export_format='GLB')
            # Explicit Y-up OBJ basis, UVs stay paired with polygon loops.
            mesh=obj.data;mesh.calc_loop_triangles()
            with (dest/'model.obj').open('w') as stream:
                stream.write('mtllib model.mtl\no body\n')
                for v in mesh.vertices:
                    co=obj.matrix_world@v.co;stream.write('v %.9f %.9f %.9f\n'%(co.x,co.z,-co.y))
                for uv in mesh.uv_layers.active.data:stream.write('vt %.9f %.9f\n'%tuple(uv.uv))
                stream.write('usemtl body\n')
                for tri in mesh.loop_triangles:stream.write('f '+' '.join(f'{v+1}/{loop+1}' for v,loop in zip(tri.vertices,tri.loops))+'\n')
            (dest/'model.mtl').write_text('newmtl body\nKd 1 1 1\nKs 0 0 0\nillum 1\nmap_Kd albedo.png\n')
        mesh=obj.data
        reports.append({'id':key,'triangles':triangles(obj),'vertices':len(mesh.vertices),'materials':len(mesh.materials),'uv_layers':len(mesh.uv_layers),'target':target})
    (output/'geometry.json').write_text(json.dumps({'original_triangles':before,'variants':reports},indent=2))


if __name__=='__main__':main()
