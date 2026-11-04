# HTTP API 与数据格式

本页聚焦项目、普通静态物件和模块验证。字段与枚举已对照 `9b57029`；其他类别先查对应路由及校验器。不手工伪造素材清单或ZIP。

## 连接与调用

服务从仓库 `.local/panel/server.json` 的 `url` 发现；文件可能陈旧，GET确认。服务监听127.0.0.1。POST使用JSON和该服务返回的 `X-Studio-Token`。token不能硬编码或打印到报告。项目和场景写入使用各自当前 `revision`，过期应重新读取，不能盲目修改数字重试。

辅助脚本（`SKILL_DIR` 替换为此skill目录，`REPO`为Studio仓库）：

```bash
python3 "$SKILL_DIR/scripts/studio_api.py" --root "$REPO" get /api/projects/state --out projects.json
python3 "$SKILL_DIR/scripts/studio_api.py" --root "$REPO" post /api/projects/change --data request.json --journal calls.jsonl --out response.json
python3 "$SKILL_DIR/scripts/studio_api.py" --root "$REPO" download '/api/module-scenes/export?scene=SCENE_ID' --out sample.zip
```

`--out`文件必须不存在；预先检查，防止已提交请求后无法写结果。脚本一调用仅发一次指定POST，日志意图记录请求SHA-256而非大图/凭据，保存服务结果或不确定错误。日志只是证据，不能当远程幂等键；看到旧意图或提交中断时先核对任务。GET查询可以再次执行，POST不能机械重跑。

## 项目

`GET /api/projects/state?project=ID`：返回 `token, projects, selected, current, tasks, production, assets, candidates, templates, kinds` 等。`selected`是项目；`current`按需求ID映射当前素材；未指定project时selected为空。

`POST /api/projects/change` 返回项目对象。常用请求：

```json
{"action":"create","title":"器物套件","baseline":{"view":"isometric_2_1","cell_px":128,"character_height_px":96,"style":"柔和手绘、大块面、轮廓清楚","palette":"旧木褐与暖赭土","lighting":"左上柔光"}}
```

已有项目只需添加需求：

```json
{"action":"import_items","project":"PROJECT_ID","revision":0,"items":[{"kind":"prop","title":"矮木凳","description":"单个完整矮木凳，厚座面、四条粗短腿，无靠背"}]}
```

`kind`: `character, ground, road, water, shore, transition, building, prop, component`。每次导入1–200项，项目最多200项，同类型同名跳过；此接口不启动生成。项目/需求名称1–60字，描述最多2000字。

其他常用action：`edit_item`需 `item,title,description`；`baseline`需完整 `baseline`（未给字段会按默认值填充）；`set_asset`需 `item,asset`，用有效同类素材ID显式选入，不复制文件。普通新任务成功会更新对应当前成果，失败保留已有成果；另存版本后经API操作需显式set_asset，不假设浏览器自动关联逻辑在API中运行。

`POST /api/projects/generate`：`{project,revision,item}`，按需求快速生成。物件默认custom/256/无碰撞；它不自动附加选定的画风图片。要传参考走下节。

## 普通物件

`GET /api/props/state`：`kits,jobs,kinds,token,image_api_configured,image_provider,image_model`。任务是最近最多60项；更旧任务本地只读查看 `.local/props/jobs/ID/job.json`，不能将“不在列表”视为不存在。

`POST /api/props/generate`：

```json
{"kind":"custom","mode":"ai","title":"矮木凳","description":"具体结构与用途","size":256,"projection":"isometric_2_1","collision_usage":"none","reference":"BASE64_BYTES_WITHOUT_DATA_URL_PREFIX","studio_context":{"project":"PROJECT_ID","item":"ITEM_ID","baseline_revision":1}}
```

`kind`: `rock,crate,bush,custom`；`size`:128或256；`mode`:ai或import。参考可省略；import以 `image` 提供原图base64，不发AI请求；透明PNG保持alpha，不透明导入只支持可识别背景。图像至少32px、不超过400万像素和8MB；参考图片遵循当前后端 `terrain.decode_image` 的限制。不要在描述里再次手动拼接项目基准，后端inherit会添加。

`studio_context`必须与项目、需求和基准版本对应，后端继承风格并记录任务关联；直接调用Python prepare不会自动完成这两步。GET状态或本地job查看任务进度。一次返回queued不代表图片已完成。`POST /api/props/generate {"resume":"JOB_ID"}`是显式继续，可能产生新费用，见恢复参考。

资源：`GET /api/props/job-image?id=JOB_ID`原图；`/api/props/job-log?id=JOB_ID`请求日志；`/prop-asset/KIT_ID/{sprite.png,preview.png,cutout.png,anchor_collision.png,kit.zip}`成果。不要默认HTTP静态预览已验证全部文件；包读取/下载校验才是对应完整性证据。

## 素材设置与不可变版本

`GET /api/props/settings?kit=ID`返回 `{settings,sha256}`，sha256为源ZIP指纹。

`POST /api/props/annotate`，返回新manifest：

```json
{"source_kit":"KIT_ID","source_sha256":"SOURCE_ZIP_SHA256","title":"矮木凳","anchor":[128,210],"world_scale":0.1,"behavior":"passable","polygons":[]}
```

`anchor`是源图像素坐标；`polygons`是相对锚点的局部源像素坐标，X右Y下；`world_scale`为0.01–100。场景渲染时原图、锚点、碰撞统一乘同一个比例，实例position不再乘。

`behavior`: `passable`要求空碰撞；`blocking`至少1块；`opening`至少2块保留开口。每块3–64点、严格凸且不自交，最多32块。占地应按落地部分人工标注，不以整个图像轮廓代替。读取公共 `module_settings` 或settings接口，不仅凭旧 `suggested_collision.polygon`判断。

常见manifest：`schema=studio.static-prop/0.1`, `id,title,view,canvas_px,image,anchor_px,provenance,processing,normalization,suggested_collision,validation,files_sha256`，标注版本另有 `module_settings`。原图/成品/回执/提示词都随包保存。`files_sha256`和ZIP由后端生成校验，不直接编辑。

## 模块场景与导出

`GET /api/module-scenes/state?scene=ID` 返回 `selected,scenes,token`；`/api/module-scenes/library`返回可选资产；场景 `schema=studio.module-scene/1`。

`POST /api/module-scenes/change`：

- `action:create,title` → 新场景。
- `action:adopt,scene,revision,family,kit` → 引用来源版本。family普通为prop/terrain/transition/character；建筑通过后端适配。transition必须指定 `corners,variant`，从库返回的tiles选择，不能猜测编号视觉含义。
- `action:module,scene,revision,module` 加上述素材设置 → 另存库版本并更新此模块，图片保持原字节。
- `action:layout,scene,revision,instances,spawn` → **整份替换布局**。读取后合并现有内容再提交；`instances:[{id,module,position:[x,y]}]`，ID唯一且module必须存在，最多2000实例。

模块存 `source:{family,id,sha256,...selectors},image,canvas_px,title,anchor,behavior,polygons,world_scale,layer`；实例使用场景坐标。普通对象按脚底Y排序，不自动处理所有复杂遮挡。

`GET /api/module-scenes/export?scene=ID` 下载ZIP，含scene.json、images、来源包、Godot运行器。解压新目录，运行Godot 4的project.godot；原包不能被覆盖。运行器有移动、简化碰撞参照，没有自动导航或完整玩法。API脚本摆放不等于已验证鼠标工作流。
