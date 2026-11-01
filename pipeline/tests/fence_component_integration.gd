extends SceneTree
# Consume exported polygons with real Godot physics; no generated gameplay.
var report: Dictionary={"passed":true,"engine":"","actor_shape":"CircleShape2D","checks":[],"scope":"geometry fixture physics only; art and occlusion pending"}
var modules: Dictionary={}
var world: Node2D

func _initialize() -> void:
    call_deferred("verify")

func record(ok: bool,label: String,details: Dictionary={}) -> void:
    report.checks.append({"passed":ok,"test":label,"details":details})
    if not ok:
        report.passed=false
        push_error(label+" "+str(details))

func wall(identity: String,offset: Vector2) -> StaticBody2D:
    var body:=StaticBody2D.new()
    body.position=offset;body.collision_layer=1;body.collision_mask=2
    for polygon in modules[identity].suggested_collision.polygons:
        var shape:=CollisionPolygon2D.new()
        var vertices:=PackedVector2Array()
        for point in polygon: vertices.append(Vector2(point[0],point[1]))
        shape.polygon=vertices;body.add_child(shape)
    world.add_child(body)
    return body

func actor(position: Vector2,radius: float) -> CharacterBody2D:
    var body:=CharacterBody2D.new()
    body.position=position;body.collision_layer=2;body.collision_mask=1
    body.motion_mode=CharacterBody2D.MOTION_MODE_FLOATING
    body.safe_margin=0.001
    var collider:=CollisionShape2D.new()
    var circle:=CircleShape2D.new();circle.radius=radius
    collider.shape=circle;body.add_child(collider);world.add_child(body)
    return body

func reset() -> void:
    for node in world.get_children(): node.queue_free()
    await physics_frame
    await physics_frame

func verify() -> void:
    report.engine=Engine.get_version_info().string
    var manifest: Dictionary=JSON.parse_string(FileAccess.get_file_as_string("res://assets/manifest.json"))
    var cases: Dictionary=JSON.parse_string(FileAccess.get_file_as_string("res://assets/physics_cases.json"))
    report.kit_id=manifest.id
    for module in manifest.modules: modules[module.id]=module
    world=Node2D.new();root.add_child(world)
    for item in cases.cases:
        await reset()
        for placement in item.placements: wall(placement[0],Vector2(placement[1][0],placement[1][1]))
        var player:=actor(Vector2(item.start[0],item.start[1]),float(item.radius_px))
        await physics_frame
        await physics_frame
        var motion:=Vector2(item.motion[0],item.motion[1])
        var collision:=player.move_and_collide(motion)
        record((collision!=null)==bool(item.expect_blocked),item.id,{"radius_px":item.radius_px,"start":item.start,"motion":item.motion,"end":[player.position.x,player.position.y]})
    await reset()
    wall("straight_ew",Vector2.ZERO)
    var slider:=actor(Vector2(16,20),4)
    await physics_frame
    await physics_frame
    for frame in 12:
        slider.velocity=Vector2(90,90)
        slider.move_and_slide()
        await physics_frame
    record(slider.position.x>25 and slider.position.y<=25.1,"slide_along_fence",{"end":[slider.position.x,slider.position.y],"radius_px":4})
    await reset()
    # Choosing not to instantiate the optional suggested collider leaves passage free.
    var free_actor:=actor(Vector2(32,8),4)
    await physics_frame
    await physics_frame
    record(free_actor.move_and_collide(Vector2(0,48))==null,"optional_collision_disabled")
    DirAccess.make_dir_recursive_absolute("res://qa")
    var file:=FileAccess.open("res://qa/physics_report.json",FileAccess.WRITE)
    file.store_string(JSON.stringify(report,"  "));file.close()
    print("FENCE_PHYSICS_", "PASS" if report.passed else "FAIL", " checks=",report.checks.size())
    quit(0 if report.passed else 1)
