# 等距资产接入验证

独立 Godot 4 项目，用于验证 Studio 素材的 2:1 地格、占地中心锚点和 Y 排序，不属于 Studio 的地图或游戏生产功能。

项目根目录执行：

```
.local/python/bin/python3 pipeline/build_isometric_demo.py
/Applications/Godot.app/Contents/MacOS/Godot --headless --editor --path demo/isometric --import
/Applications/Godot.app/Contents/MacOS/Godot --path demo/isometric
```

默认复用已生成草地纹理；石头、木箱为明确标注的程序几何样本，不代表 AI 生成效果。接入真实等距素材：

```
.local/python/bin/python3 pipeline/build_isometric_demo.py --rock <等距石头包ID> --crate <等距木箱包ID>
```

不调用生图服务，不把已有斜俯视物件改标签冒充等距素材。原包保持不变。生成资源位于被 Git 忽略的 assets/，需本机保留源素材包。

方向键移动青色测试标记，F 切换占地建议，R 重置。青色标记仅为排序测试图形。这里由游戏主动启用导出的碰撞建议，生产包仍默认关闭。投影角度、落地锚点和实际美术遮挡仍需人工验收。
