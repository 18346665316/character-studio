extends SceneTree
## Canonical conversion only: reuse Godot's verified FBX import and bone attachment.
## Rendering is performed by Blender, not by this bridge.
func _initialize() -> void:
    run.call_deferred()

func run() -> void:
    var output := ""
    var args := OS.get_cmdline_user_args()
    for i in range(args.size() - 1):
        if args[i] == "--output": output = args[i + 1]
    if output.is_empty():
        quit(1)
        return
    var clips := []
    for filename in DirAccess.get_files_at("res://animations"):
        if filename.get_extension().to_lower() not in ["fbx", "glb"]: continue
        var character := (load("res://animations/" + filename) as PackedScene).instantiate()
        root.add_child(character)
        var stack: Array[Node] = [character]
        var player: AnimationPlayer
        var skeleton: Skeleton3D
        while not stack.is_empty():
            var node: Node = stack.pop_back()
            if node is AnimationPlayer: player = node
            if node is Skeleton3D: skeleton = node
            stack.append_array(node.get_children())
        if player == null:
            push_error("AnimationPlayer missing")
            quit(1)
            return
        var selected := ""
        var duration := 0.0
        var helper = load("res://baker.gd").new()
        for name in player.get_animation_list():
            var clip := player.get_animation(name)
            if name != "RESET" and helper._has_motion(clip) and clip.length > duration:
                selected = name
                duration = clip.length
        helper.free()
        if selected.is_empty():
            quit(1)
            return
        for library_name in player.get_animation_library_list():
            var library := player.get_animation_library(library_name)
            for animation_name in library.get_animation_list():
                var full_name := str(library_name) + "/" + str(animation_name) if library_name != "" else str(animation_name)
                if full_name != selected: library.remove_animation(animation_name)
        var usage := {}
        if FileAccess.file_exists("res://equipment.json"):
            var config: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://equipment.json"))
            if skeleton == null or skeleton.find_bone(config.bone) < 0:
                quit(1)
                return
            var runtime = load("res://equipment_runtime.gd")
            if FileAccess.file_exists("res://equipment_usage.json"):
                usage = JSON.parse_string(FileAccess.get_file_as_string("res://equipment_usage.json"))
                if runtime.usage_setup(skeleton,config,usage).is_empty():
                    quit(1)
                    return
                # Export all mounts; Blender applies visibility per sampled frame.
            elif runtime.attach(skeleton, config) == null:
                quit(1)
                return
        await process_frame
        var heading: Dictionary = load("res://heading_runtime.gd").record(filename) if FileAccess.file_exists("res://heading_runtime.gd") else {"degrees":0.0}
        if FileAccess.file_exists("res://heading_runtime.gd"):
            character = load("res://heading_runtime.gd").wrap_model(character, float(heading.degrees))
        var state := GLTFState.new()
        var document := GLTFDocument.new()
        var result := document.append_from_scene(character, state)
        if result == OK:
            result = document.write_to_filesystem(state, output.path_join(filename.get_basename() + ".glb"))
        var timing: Dictionary = load("res://temporal_plan.gd").plan(player.get_animation(selected))
        timing.merge({"usage":usage,"name":filename.get_basename(),"heading":heading},true)
        character.queue_free()
        await process_frame
        if result != OK:
            push_error("Blender animation bridge failed: " + str(result))
            quit(1)
            return
        clips.append(timing)
    var file := FileAccess.open(output.path_join("clips.json"), FileAccess.WRITE)
    file.store_string(JSON.stringify(clips))
    file.close()
    quit(0 if not clips.is_empty() else 1)
