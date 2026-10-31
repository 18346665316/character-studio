"""Blender batch entrypoint. Canonical GLB inputs; Eevee renders; stdlib-only output."""
import argparse
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector


def frame_at(scene, time):
    frame = time * 24.0
    scene.frame_set(math.floor(frame), subframe=frame-math.floor(frame))
    bpy.context.view_layer.update()


def points(objects):
    graph = bpy.context.evaluated_depsgraph_get()
    for obj in objects:
        if obj.type != 'MESH': continue
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        try:
            for vertex in mesh.vertices:
                yield evaluated.matrix_world @ vertex.co
        finally:
            evaluated.to_mesh_clear()


def apply_usage(objects, clip, phase):
    usage=clip.get('usage') or {}
    action=usage.get('clips',{}).get(clip['name'],{})
    state=action.get('initial','inherit')
    if state=='inherit': state=usage.get('default','hand')
    for event in action.get('events',[]):
        if phase+1e-6>=event['at']: state=event['state']
    visible=[]
    for obj in objects:
        parent=obj
        mount=None
        while parent:
            if parent.name.startswith('STUDIO_WEAPON_'):
                mount=parent.name[len('STUDIO_WEAPON_'):].split('.')[0].lower()
                break
            parent=parent.parent
        obj.hide_render=mount is not None and mount!=state
        if not obj.hide_render: visible.append(obj)
    return visible


def load_clip(path):
    # Hidden custom bone shapes are not selectable; delete datablocks too so
    # helpers from a previous clip cannot leak into the next clip's bounds.
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.context.scene.render.fps = 24
    bpy.ops.import_scene.gltf(filepath=str(path))
    # The glTF importer adds hidden icospheres for bone display. These are
    # editor helpers, not asset geometry; never include them in camera bounds.
    helpers = {bone.custom_shape for obj in bpy.context.scene.objects if obj.type == 'ARMATURE' for bone in obj.pose.bones if bone.custom_shape}
    objects = [obj for obj in bpy.context.scene.objects if obj not in helpers and not obj.hide_render]
    if not any(o.type == 'MESH' for o in objects): raise RuntimeError('No imported geometry')
    # Soft, texture-driven Eevee shading. No stochastic shadows or motion blur.
    for obj in objects:
        if obj.type != 'MESH': continue
        for material in obj.data.materials:
            if not material or not material.use_nodes: continue
            for node in material.node_tree.nodes:
                if node.type == 'BSDF_PRINCIPLED':
                    node.inputs['Roughness'].default_value = 1.0
                    if 'Metallic' in node.inputs: node.inputs['Metallic'].default_value = 0.0
                    if 'Specular IOR Level' in node.inputs: node.inputs['Specular IOR Level'].default_value = 0.0
    return objects


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--frame-size',type=int,required=True)
    parser.add_argument('--view',choices=['front','side','three_quarter'],required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    source, output = Path(args.input),Path(args.output)
    clips = json.loads((source/'clips.json').read_text())
    if not clips: raise RuntimeError('No animation clips')
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = scene.render.resolution_y = args.frame_size
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '8'
    scene.render.use_file_extension = True
    scene.render.use_motion_blur = False
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    if hasattr(scene,'eevee'):
        if hasattr(scene.eevee,'taa_render_samples'): scene.eevee.taa_render_samples = 64
        if hasattr(scene.eevee,'use_taa_reprojection'): scene.eevee.use_taa_reprojection = False
    angle = {'front':0,'side':math.pi/2,'three_quarter':math.pi/4}[args.view]
    # glTF Y-up is converted by Blender to Z-up: Godot +Z front becomes Blender -Y.
    right = Vector((math.cos(angle),math.sin(angle),0))
    forward = Vector((math.sin(angle),-math.cos(angle),0))
    limits = [math.inf,math.inf,math.inf,-math.inf,-math.inf,-math.inf]
    for clip in clips:
        objects = load_clip(source/(clip['name']+'.glb'))
        for i in range(clip['frame_count']):
            frame_at(scene,i/clip['frame_count']*clip['duration_seconds'])
            visible=apply_usage(objects,clip,i/clip['frame_count'])
            for point in points(visible):
                coords = (point.dot(right),point.z,point.dot(forward))
                for axis,v in enumerate(coords):
                    limits[axis] = min(limits[axis],v)
                    limits[axis+3] = max(limits[axis+3],v)
    if not all(math.isfinite(x) for x in limits): raise RuntimeError('Invalid posed geometry bounds')
    width,height = limits[3]-limits[0],limits[4]-limits[1]
    size = max(width,height)*1.12
    print('PROJECTED_BOUNDS', limits, 'CAMERA_SIZE', size, flush=True)
    extent = max(size,limits[5]-limits[2],1e-4)
    center = right*((limits[0]+limits[3])/2)+Vector((0,0,(limits[1]+limits[4])/2))+forward*((limits[2]+limits[5])/2)
    output.mkdir(parents=True,exist_ok=True)
    for clip in clips:
        objects = load_clip(source/(clip['name']+'.glb'))
        world = bpy.data.worlds.new('Studio World')
        world.use_nodes = True
        world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.72,0.78,0.85,1)
        world.node_tree.nodes['Background'].inputs['Strength'].default_value = .7
        scene.world = world
        for name,rotation,energy in [('Key',(math.radians(30),math.radians(-25),math.radians(-30)),2.0),('Fill',(math.radians(60),0,math.radians(140)),.7)]:
            data=bpy.data.lights.new(name,'SUN');data.energy=energy;data.use_shadow=False
            light=bpy.data.objects.new(name,data);scene.collection.objects.link(light);light.rotation_euler=rotation
        data=bpy.data.cameras.new('Studio Camera');data.type='ORTHO';data.ortho_scale=size
        data.clip_start=max(extent*.001,1e-6);data.clip_end=max(extent*20,.01)
        camera=bpy.data.objects.new('Studio Camera',data);scene.collection.objects.link(camera)
        camera.location=center+forward*extent*3
        camera.rotation_euler=(center-camera.location).to_track_quat('-Z','Y').to_euler();scene.camera=camera
        for i in range(clip['frame_count']):
            frame_at(scene,i/clip['frame_count']*clip['duration_seconds'])
            apply_usage(objects,clip,i/clip['frame_count'])
            target=output/(clip['name']+f'_{i:03d}.png')
            scene.render.filepath=str(target)
            bpy.ops.render.render(write_still=True)
        metadata={**clip,'fps':clip['frame_count']/clip['duration_seconds'],'view':args.view,'renderer':'blender',
                  'camera':{'size':size,'center':list(center),'view':args.view},
                  'blender_version':bpy.app.version_string,'render_style':'eevee_soft_unshadowed','framing':'shared_batch_projected_vertices',
                  'frame_width':args.frame_size,'frame_height':args.frame_size}
        (output/(clip['name']+'_render.json')).write_text(json.dumps(metadata,indent=2))
    print('BLENDER_RENDER_COMPLETE',flush=True)

if __name__ == '__main__': main()
