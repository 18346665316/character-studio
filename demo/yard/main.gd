extends Node2D
const PLAYER=preload("res://player.gd")
const MARKER=preload("res://marker.gd")
const SPAWN:=Vector2(544,608)
const CHECKPOINTS=[Vector2(260,345),Vector2(900,350),Vector2(820,565)]
var world: Node2D
var player: CharacterBody2D
var checked: Array[bool]=[false,false,false]
var won:=false
var counter: Label
var hint: Label
var banner: Label
var indicators: Array[Node2D]=[]
var nearest: int=-1
var textures: Dictionary={}

func data(role: String) -> Dictionary:
    return JSON.parse_string(FileAccess.get_file_as_string("res://assets/textures/"+role+"/manifest.json"))
func texture(role: String,path: String) -> Texture2D:
    var key:=role+"/"+path
    if not textures.has(key): textures[key]=load("res://assets/textures/"+key)
    return textures[key]
func sprite(role: String,path: String,position_px: Vector2,parent: Node,offset:=Vector2.ZERO,scale_factor:=1.0) -> Sprite2D:
    var node:=Sprite2D.new();node.texture=texture(role,path);node.centered=false
    node.position=position_px;node.offset=offset;node.scale=Vector2.ONE*scale_factor
    parent.add_child(node);return node
func collider(position_px: Vector2,points: Array,scale_factor:=1.0) -> void:
    var body:=StaticBody2D.new();body.position=position_px;body.collision_layer=1;body.collision_mask=2
    var shape:=CollisionPolygon2D.new();var polygon:=PackedVector2Array()
    for point in points: polygon.append(Vector2(point[0],point[1])*scale_factor)
    shape.polygon=polygon;body.add_child(shape);add_child(body)
func rectangle_blocker(rect: Rect2) -> void:
    collider(rect.position,[[0,0],[rect.size.x,0],[rect.size.x,rect.size.y],[0,rect.size.y]])

func _ready() -> void:
    setup_input()
    world=Node2D.new();world.name="DepthSortedWorld";world.y_sort_enabled=true;add_child(world)
    make_ground();make_fence();make_props();make_hud()
    player=PLAYER.new();player.position=SPAWN;world.add_child(player)
    reset_game()

func setup_input() -> void:
    var keys={"move_left":[KEY_A,KEY_LEFT],"move_right":[KEY_D,KEY_RIGHT],"move_up":[KEY_W,KEY_UP],"move_down":[KEY_S,KEY_DOWN],"sprint":[KEY_SHIFT],"interact":[KEY_E],"restart":[KEY_R]}
    for action in keys:
        if not InputMap.has_action(action):InputMap.add_action(action)
        for key in keys[action]:
            var event:=InputEventKey.new();event.physical_keycode=key;InputMap.action_add_event(action,event)

func make_ground() -> void:
    var ground:=Node2D.new();ground.z_index=-10;add_child(ground)
    var terrain:=data("terrain")
    var road_cells: Dictionary={}
    for x in range(3,15):road_cells[Vector2i(x,7)]=true
    for y in range(4,10):road_cells[Vector2i(8,y)]=true
    for y in range(12):
        for x in range(18):
            var cell:=Vector2i(x,y);var variant: Dictionary=terrain.variants[(x*13+y*7)%terrain.variants.size()]
            var path: String=variant.ground
            if road_cells.has(cell):
                var bits:=0
                for step in [[Vector2i.UP,1],[Vector2i.RIGHT,2],[Vector2i.DOWN,4],[Vector2i.LEFT,8]]:
                    if road_cells.has(cell+step[0]):bits|=step[1]
                path=variant.tiles[bits].image
            sprite("terrain",path,Vector2(x*64,y*64),ground)
    # Shoreline images supply appearance only. The demo authors its own water blocker.
    var water:=data("water")
    for y in range(3,6):
        for x in range(6,10):
            var bits:=0
            if x>6 and y>3:bits|=1
            if x<9 and y>3:bits|=2
            if x<9 and y<5:bits|=4
            if x>6 and y<5:bits|=8
            var path: String=""
            for tile in water.tiles:
                if tile.corners==bits and tile.variant==(x+y)%int(water.variants):path=tile.image;break
            sprite("water",path,Vector2(x*64,y*64),ground)
    rectangle_blocker(Rect2(420,228,184,124))
    # Invisible world limits keep the short entrance passage inside the demo.
    rectangle_blocker(Rect2(-32,-32,1216,32));rectangle_blocker(Rect2(-32,768,1216,32))
    rectangle_blocker(Rect2(-32,0,32,768));rectangle_blocker(Rect2(1152,0,32,768))

func fence_module(identity: String,cell: Vector2i,manifest: Dictionary) -> void:
    var record: Dictionary={}
    for module in manifest.modules:
        if module.id==identity:record=module;break
    for layer in record.visual_layers:
        var position_px:=Vector2(cell*64)+Vector2(layer.sort_position_px[0],layer.sort_position_px[1])
        sprite("fence",layer.image,position_px,world,Vector2(layer.image_offset_px[0],layer.image_offset_px[1]))
    for points in record.suggested_collision.polygons:collider(Vector2(cell*64),points)
func make_fence() -> void:
    var manifest:=data("fence")
    for x in range(2,16):
        fence_module("straight_ew",Vector2i(x,2),manifest)
        fence_module("opening_ew" if x==8 else "straight_ew",Vector2i(x,10),manifest)
    for y in range(3,10):
        fence_module("straight_ns",Vector2i(1,y),manifest);fence_module("straight_ns",Vector2i(16,y),manifest)
    for item in [["corner_es",Vector2i(1,2)],["corner_sw",Vector2i(16,2)],["corner_ne",Vector2i(1,10)],["corner_wn",Vector2i(16,10)]]:
        fence_module(item[0],item[1],manifest)

func prop(role: String,position_px: Vector2,size_factor: float,block: bool) -> Node2D:
    var manifest:=data(role)
    var visual:=sprite(role,manifest.image,position_px,world,Vector2(manifest.sprite_offset_px[0],manifest.sprite_offset_px[1]),size_factor)
    if block:
        # Gameplay-owned footprint calibration; no mutation of the Studio package.
        var width: float=manifest.normalization.content_px[0]*.82*size_factor
        var depth: float=manifest.normalization.content_px[1]*.27*size_factor
        var points: Array=[]
        for i in range(16):points.append([cos(i*TAU/16)*width/2,-depth/2+sin(i*TAU/16)*depth/2])
        collider(position_px,points)
    return visual
func indicator(position_px: Vector2,color: Color,radius: float) -> Node2D:
    var node:=MARKER.new();node.position=position_px;node.tint=color;node.radius=radius;node.z_index=-2;add_child(node);return node
func make_props() -> void:
    for point in [Vector2(340,520),Vector2(725,360),Vector2(950,560)]:prop("rock",point,.43,true)
    for point in [Vector2(200,250),Vector2(320,220),Vector2(960,240),Vector2(1015,445),Vector2(185,575),Vector2(680,590)]:prop("bush",point,.4,false)
    for point in CHECKPOINTS:
        prop("crate",point,.32,true)
        indicators.append(indicator(point+Vector2(0,12),Color("e9c76a"),24))
    indicator(SPAWN,Color("a5dbd1"),30)

func make_hud() -> void:
    var layer:=CanvasLayer.new();layer.layer=10;add_child(layer)
    var top:=ColorRect.new();top.color=Color("1c302c");top.size=Vector2(1152,68);top.mouse_filter=Control.MOUSE_FILTER_IGNORE;layer.add_child(top)
    var title:=Label.new();title.text="小庭院巡查";title.position=Vector2(26,8);title.add_theme_font_size_override("font_size",25);layer.add_child(title)
    counter=Label.new();counter.name="ObjectiveCounter";counter.position=Vector2(26,39);counter.add_theme_font_size_override("font_size",14);layer.add_child(counter)
    var controls:=Label.new();controls.text="WASD / 方向键移动    Shift 跑步    E 检查木箱    R 重新开始";controls.position=Vector2(590,25);controls.add_theme_font_size_override("font_size",15);layer.add_child(controls)
    var bottom:=ColorRect.new();bottom.position=Vector2(0,724);bottom.size=Vector2(1152,44);bottom.color=Color("1c302c");layer.add_child(bottom)
    hint=Label.new();hint.name="InteractionHint";hint.position=Vector2(26,733);hint.add_theme_font_size_override("font_size",17);layer.add_child(hint)
    banner=Label.new();banner.position=Vector2(318,78);banner.add_theme_font_size_override("font_size",23);banner.modulate=Color("fff2b0");layer.add_child(banner)

func reset_game() -> void:
    checked=[false,false,false];won=false;player.position=SPAWN;player.enabled=true;nearest=-1
    for node in indicators:node.tint=Color("e9c76a");node.solid=false;node.queue_redraw()
    banner.text="检查三只木箱，然后返回入口圆环";refresh_counter()
func refresh_counter() -> void:
    counter.text="木箱检查：%d / 3   ·   Studio 现有素材接入演示"%checked.count(true)
func _physics_process(_delta: float) -> void:
    if Input.is_action_just_pressed("restart"):reset_game()
    nearest=-1
    if won:hint.text="巡查完成！按 R 再玩一次。";return
    var closest:=65.0
    for i in range(CHECKPOINTS.size()):
        var distance:=player.position.distance_to(CHECKPOINTS[i])
        if not checked[i] and distance<closest:nearest=i;closest=distance
    hint.text="靠近带金色圆环的木箱，按 E 检查。" if nearest<0 else "按 E 检查木箱 %d"%(nearest+1)
    if Input.is_action_just_pressed("interact") and nearest>=0:
        checked[nearest]=true;indicators[nearest].tint=Color("a5dbb0");indicators[nearest].solid=true;indicators[nearest].queue_redraw();refresh_counter()
    if checked.count(true)==3:
        hint.text="三只木箱都已检查，返回下方青色入口圆环。"
        if player.position.distance_to(SPAWN)<30:
            won=true;player.enabled=false;banner.text="巡查完成 · 所有木箱已确认";refresh_counter()
