@tool
extends EditorPlugin

var policy = preload("policy.gd").new()

func _enter_tree():
    add_scene_post_import_plugin(policy)

func _exit_tree():
    remove_scene_post_import_plugin(policy)
