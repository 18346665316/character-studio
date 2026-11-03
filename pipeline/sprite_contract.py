"""Shared sprite anchor and convex collision annotation validation."""
import math

def number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value)>100000:
        raise ValueError('坐标必须是有限数字，绝对值不超过100000')
    return value


def point(value):
    if not isinstance(value, list) or len(value)!=2: raise ValueError('需要二维坐标')
    return [number(v) for v in value]


def polygons(values):
    if not isinstance(values, list) or len(values)>32: raise ValueError('碰撞区域最多32个')
    result=[]
    for poly in values:
        if not isinstance(poly,list) or not 3<=len(poly)<=64: raise ValueError('多边形需要3–64个顶点')
        poly=[point(p) for p in poly]
        # Convex polygons keep both editor and engine collision semantics clear.
        crosses=[]
        for i in range(len(poly)):
            a,b,c=poly[i-2],poly[i-1],poly[i]
            crosses.append((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))
        area=sum(poly[i-1][0]*p[1]-p[0]*poly[i-1][1] for i,p in enumerate(poly))
        if abs(area)<.01 or not (all(v>0 for v in crosses) or all(v<0 for v in crosses)):
            raise ValueError('请使用不自交的严格凸多边形；复杂形状可拆成多个区域')
        # Reject star polygons whose local turn signs alone look consistent.
        for i,a in enumerate(poly):
            b=poly[(i+1)%len(poly)]
            side=[(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
                  for j,c in enumerate(poly) if j not in (i,(i+1)%len(poly))]
            if not (all(v>0 for v in side) or all(v<0 for v in side)):
                raise ValueError('多边形必须为不自交凸多边形')
        result.append(poly)
    return result


def title(value):
    if not isinstance(value,str) or not 1<=len(value.strip())<=80: raise ValueError('名称需要1–80字')
    return value.strip()


def settings(data):
    scale=data.get('world_scale',1)
    if type(scale) not in (int,float) or not math.isfinite(scale) or not .01<=scale<=100:
        raise ValueError('场景比例须在0.01–100之间')
    behavior=data.get('behavior')
    if behavior not in ('blocking','opening','passable'): raise ValueError('未知通行类型')
    shapes=polygons(data.get('polygons',[]))
    if behavior=='passable' and shapes: raise ValueError('可通过素材应清空碰撞')
    if behavior!='passable' and not shapes: raise ValueError('阻挡或开口素材需要碰撞区域')
    if behavior=='opening' and len(shapes)<2: raise ValueError('开口素材需要至少两块碰撞区域')
    return dict(title=title(data.get('title')),anchor=point(data.get('anchor')),behavior=behavior,polygons=shapes,world_scale=scale)
