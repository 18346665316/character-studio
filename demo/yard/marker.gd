extends Node2D
var tint:=Color("e6c16e")
var radius:=22.0
var solid:=false
func _draw() -> void:
    draw_circle(Vector2.ZERO,radius,Color(tint,.12))
    draw_arc(Vector2.ZERO,radius,0,TAU,40,tint,2,true)
    if solid:
        draw_line(Vector2(-7,0),Vector2(-1,6),tint,3,true)
        draw_line(Vector2(-1,6),Vector2(9,-7),tint,3,true)
    else:
        draw_circle(Vector2.ZERO,3,tint)
