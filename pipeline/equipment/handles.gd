extends Control
## Constant-size screen handles remain readable at any orbit distance.
var editor
func _ready() -> void:
    mouse_filter=Control.MOUSE_FILTER_IGNORE
    set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

func _process(_delta: float) -> void:
    queue_redraw()

func _draw() -> void:
    if editor==null or editor.step==2 or editor.mode!="hand": return
    var colors := [Color("fa775d"),Color("74dc91"),Color("70b9ff")]
    for i in range(editor.markers.size()):
        if (editor.step==0 and i!=0) or (editor.step==1 and i!=1): continue
        var marker: MeshInstance3D=editor.markers[i]
        if editor.viewer.camera.is_position_behind(marker.global_position): continue
        var point: Vector2=editor.viewer.camera.unproject_position(marker.global_position)
        if point.x<365: continue
        var selected: bool=i==editor.selected_point
        draw_circle(point,15 if selected else 11,Color(0.04,0.08,0.09,0.85))
        draw_arc(point,16 if selected else 12,0,TAU,40,colors[i],3 if selected else 2,true)
        draw_circle(point,4,colors[i])
        var caption: String=["握点","剑尖方向","刃面方向"][i]
        var font := ThemeDB.fallback_font
        var at := point+Vector2(21,-12-i*3)
        var size := font.get_string_size(caption,HORIZONTAL_ALIGNMENT_LEFT,-1,15)
        draw_style_box(_background(),Rect2(at+Vector2(-5,-16),size+Vector2(10,8)))
        draw_string(font,at,caption,HORIZONTAL_ALIGNMENT_LEFT,-1,15,colors[i])

func _background() -> StyleBoxFlat:
    var box := StyleBoxFlat.new()
    box.bg_color=Color(0.04,0.08,0.09,0.85)
    box.set_corner_radius_all(4)
    return box
