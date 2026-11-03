# 宋村 · Studio 交付验证

项目：`20261102-211857-adca0377`。当前试玩消费 `20261103-092303-0c9195ae`：完整院落已从项目有效清单归档，场景使用已交付的独立民居、农舍、地面、物件和临时人物。素材原样提取；Godot 端的坐标和重复摆放是临时验收布局，**不是 Studio 导出的场景布局**。

Studio 新增未选用需求“宋村 2:1 等距院墙与门洞模块”。目前现有围栏套件的视角为正交三分之四，不满足项目的2:1等距基准；Studio 的组合挑选不能保存并导出同一模块的多次实例及院落场景，因此当前未交付完整的模块化院落。等待该能力及合格素材后，再从 Studio 导出组合并验证。

WASD/方向键移动，Shift奔跑，空格跳跃，F跟随；拖动和滚轮控制镜头，1–4切换观察点，G显示网格，R全村。临时红衣人物为单一three_quarter视角；动作美术和宋代服饰未验收。

目前没有物体碰撞或院落遮挡。现有物件包的碰撞用途均为 `none`，不能声称已验证通行或物理。完整院落旧素材及旧交付保留历史，已从有效清单和试玩场景移除。

双击 `play.command`，或使用 Godot 4.6 打开 `project.godot`。若要重建：

```sh
.local/python/bin/python3 pipeline/build_song_village_demo.py --project 20261102-211857-adca0377
/Applications/Godot.app/Contents/MacOS/Godot --headless --editor --path demo/song_village --import
/Applications/Godot.app/Contents/MacOS/Godot --path demo/song_village
```

构建脚本读取最近一份 Studio 整套交付，校验总包和分包指纹与CRC。人物分包的独立 `project.godot` 不提取到父项目，Godot `.import` 元数据由本机生成；原始ZIP保留完整文件。`assets/` 为可重建的本机数据。
