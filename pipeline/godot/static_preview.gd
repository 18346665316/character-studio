extends Node3D

func _ready() -> void:
    var args := OS.get_cmdline_user_args()
    var model := (load("res://model.glb") as PackedScene).instantiate() as Node3D
    add_child(model)
    var camera := Camera3D.new()
    camera.projection = Camera3D.PROJECTION_ORTHOGONAL
    camera.size = 2.1
    camera.position = Vector3(0, 0.85, 4)
    camera.near = 0.01
    add_child(camera)
    camera.make_current()
    var stack: Array[Node] = [model]
    while not stack.is_empty():
        var node: Node = stack.pop_back()
        if node is MeshInstance3D and node.mesh != null:
            for surface in range(node.mesh.get_surface_count()):
                var material: Material = node.get_active_material(surface)
                if material is BaseMaterial3D:
                    var flat := material.duplicate() as BaseMaterial3D
                    flat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
                    node.set_surface_override_material(surface, flat)
        stack.append_array(node.get_children())
    var environment := WorldEnvironment.new()
    environment.environment = Environment.new()
    environment.environment.background_mode = Environment.BG_COLOR
    environment.environment.background_color = Color(0.9, 0.92, 0.94)
    add_child(environment)
    for i in range(8):
        model.rotation.y = float(i) * TAU / 8.0
        await get_tree().process_frame
        await RenderingServer.frame_post_draw
        var error := get_viewport().get_texture().get_image().save_png(args[0].path_join("view_%02d.png" % i))
        if error != OK:
            get_tree().quit(1)
            return
    get_tree().quit(0)
