extends SceneTree
# Real renderer acceptance of ground-depth slices; actor is a labelled test marker.
var report: Dictionary={"passed":true,"checks":[],"art_review":"pending","actor":"8x36 magenta test marker; no gameplay"}
var viewport: SubViewport
var sorted_root: Node2D
var marker: Polygon2D
var manifest: Dictionary
var images: Dictionary={}

func _initialize() -> void: call_deferred("verify")
func record(ok: bool,label: String,details: Dictionary={}) -> void:
    report.checks.append({"passed":ok,"test":label,"details":details})
    if not ok: report.passed=false;push_error(label)

func png(path: String) -> Image:
    var image:=Image.new()
    var error:=image.load_png_from_buffer(FileAccess.get_file_as_bytes("res://assets/"+path))
    record(error==OK,"load "+path)
    return image

func sample_module(identity: String,actor_y: float) -> void:
    for child in sorted_root.get_children(): child.queue_free()
    await process_frame
    var module: Dictionary={}
    for entry in manifest.modules:
        if entry.id==identity: module=entry;break
    record(not module.is_empty() and module.has("visual_layers"),identity+": layered visuals provided")
    if module.is_empty() or not module.has("visual_layers"): return
    for layer in module.visual_layers:
        var sprite:=Sprite2D.new()
        sprite.texture=ImageTexture.create_from_image(png(layer.image))
        sprite.centered=false
        sprite.position=Vector2(32+layer.sort_position_px[0],64+layer.sort_position_px[1])
        sprite.offset=Vector2(layer.image_offset_px[0],layer.image_offset_px[1])
        sprite.texture_filter=CanvasItem.TEXTURE_FILTER_NEAREST
        sorted_root.add_child(sprite)
    marker=Polygon2D.new()
    marker.polygon=PackedVector2Array([Vector2(-4,-36),Vector2(4,-36),Vector2(4,0),Vector2(-4,0)])
    marker.color=Color(1,0,1,1);marker.position=Vector2(64,64+actor_y)
    sorted_root.add_child(marker)
    await process_frame
    await RenderingServer.frame_post_draw
    images[identity+"_"+str(int(actor_y))]=viewport.get_texture().get_image()

func verify() -> void:
    DirAccess.make_dir_recursive_absolute("res://qa")
    manifest=JSON.parse_string(FileAccess.get_file_as_string("res://assets/manifest.json"))
    viewport=SubViewport.new();viewport.size=Vector2i(128,160)
    viewport.render_target_update_mode=SubViewport.UPDATE_ALWAYS
    viewport.disable_3d=true
    root.add_child(viewport)
    sorted_root=Node2D.new();sorted_root.y_sort_enabled=true;viewport.add_child(sorted_root)
    await sample_module("straight_ew",28)
    var behind: Image=images["straight_ew_28"]
    record(behind.get_pixel(64,80)!=Color(1,0,1,1),"horizontal: fence occludes marker behind",{"foot_y":28,"sample":[64,80]})
    await sample_module("straight_ew",36)
    var front: Image=images["straight_ew_36"]
    record(front.get_pixel(64,80)==Color(1,0,1,1),"horizontal: front marker occludes fence",{"foot_y":36,"sample":[64,80]})
    await sample_module("straight_ns",48)
    var vertical: Image=images["straight_ns_48"]
    record(vertical.get_pixel(64,80)==Color(1,0,1,1),"vertical: marker occludes rear depth slices",{"foot_y":48,"sample":[64,80]})
    record(vertical.get_pixel(64,102)!=Color(1,0,1,1),"vertical: nearer depth slices occlude same marker",{"foot_y":48,"sample":[64,102]})
    for key in images: images[key].save_png("res://qa/occlusion_"+key+".png")
    report.engine=Engine.get_version_info().string
    report.kit_id=manifest.id
    var file:=FileAccess.open("res://qa/visual_report.json",FileAccess.WRITE)
    file.store_string(JSON.stringify(report,"  "));file.close()
    print("FENCE_VISUAL_", "PASS" if report.passed else "FAIL", " checks=",report.checks.size())
    quit(0 if report.passed else 1)
