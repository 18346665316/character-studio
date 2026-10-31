extends SceneTree
## Headless structural verification; never renders or publishes an asset.

func _initialize() -> void:
    var args := OS.get_cmdline_user_args()
    if args.size() != 2:
        quit(1)
        return
    var resource := load(args[0]) as PackedScene
    if resource == null:
        quit(1)
        return
    var scene := resource.instantiate()
    var result := {"mesh_names": [], "triangles": 0, "skeleton_bones": 0, "bone_names": [], "skinned_meshes": 0, "animations": [], "textured_surfaces": 0, "surfaces": 0}
    var stack: Array[Node] = [scene]
    while not stack.is_empty():
        var node: Node = stack.pop_back()
        if node is Skeleton3D:
            result.skeleton_bones += node.get_bone_count()
            for bone in range(node.get_bone_count()):
                result.bone_names.append(str(node.get_bone_name(bone)))
        if node is MeshInstance3D and node.mesh != null:
            result.mesh_names.append(str(node.name))
            if node.skin != null:
                result.skinned_meshes += 1
            for surface in range(node.mesh.get_surface_count()):
                result.surfaces += 1
                var material: Material = node.get_active_material(surface)
                if material is BaseMaterial3D and material.albedo_texture != null:
                    result.textured_surfaces += 1
                var arrays: Array = node.mesh.surface_get_arrays(surface)
                var indices: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
                result.triangles += int(indices.size() / 3) if not indices.is_empty() else int(arrays[Mesh.ARRAY_VERTEX].size() / 3)
        if node is AnimationPlayer:
            for name in node.get_animation_list():
                var clip: Animation = node.get_animation(name)
                var changing := 0
                for track in range(clip.get_track_count()):
                    if clip.track_get_type(track) not in [Animation.TYPE_POSITION_3D, Animation.TYPE_ROTATION_3D, Animation.TYPE_SCALE_3D, Animation.TYPE_BLEND_SHAPE, Animation.TYPE_VALUE]:
                        continue
                    if clip.track_get_key_count(track) < 2:
                        continue
                    var first: Variant = clip.track_get_key_value(track, 0)
                    for key in range(1, clip.track_get_key_count(track)):
                        if clip.track_get_key_value(track, key) != first:
                            changing += 1
                            break
                result.animations.append({"name": str(name), "length": clip.length, "changing_tracks": changing})
        stack.append_array(node.get_children())
    scene.free()
    var output := FileAccess.open(args[1], FileAccess.WRITE)
    if output == null:
        quit(1)
        return
    output.store_string(JSON.stringify(result, "  "))
    output.close()
    quit(0)
