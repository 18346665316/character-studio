@tool
extends EditorScenePostImportPlugin

# Runs before Godot's animation optimizer, for every imported scene format.
# Absolute optimizer tolerances can erase compensating hip motion on small rigs.
func _pre_process(scene: Node):
    var subresources: Dictionary = get_option_value("_subresources")
    var nodes: Dictionary = subresources.get("nodes", {})
    var pending: Array[Node] = [scene]
    while not pending.is_empty():
        var node: Node = pending.pop_back()
        pending.append_array(node.get_children())
        if node is AnimationPlayer:
            var key = str(node.get_meta("import_id", "PATH:" + str(scene.get_path_to(node))))
            var settings: Dictionary = nodes.get(key, {})
            settings["optimizer/enabled"] = false
            settings["compression/enabled"] = false
            nodes[key] = settings
    subresources["nodes"] = nodes
