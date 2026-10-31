extends SceneTree

func _initialize() -> void:
    run.call_deferred()

func run() -> void:
    var request: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://heading_request.json"))
    var results := {}
    for filename in request.files:
        var model = load(str(request.directory) + "/" + filename).instantiate()
        root.add_child(model)
        var players = model.find_children("*", "AnimationPlayer", true, false)
        var skeletons = model.find_children("*", "Skeleton3D", true, false)
        var record := {"degrees":0.0,"estimated_degrees":0.0,"status":"needs_review","reason":"缺少可识别骨骼"}
        if not players.is_empty() and not skeletons.is_empty():
            record = load("res://heading_runtime.gd").estimate(players[0], skeletons[0])
        results[filename] = record
        model.free()
    var file := FileAccess.open("res://heading_estimates.json", FileAccess.WRITE)
    file.store_string(JSON.stringify(results,"  "))
    file.close()
    quit()

