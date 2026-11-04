# 安装与服务配置

[返回项目首页](../README.md)

## 先运行现有样例

无需配置素材生产环境。安装 Godot 4，用编辑器导入并运行 [人物样例](../examples/characters/chenbo/project.godot)。本项目此次使用 Godot 4.6.2 验证。

## 启动本地工作台

在仓库根目录运行：

```bash
python3 -m venv .local/python
.local/python/bin/python3 -m pip install Pillow numpy
./studio panel
```

`studio` 启动脚本固定使用 `.local/python/bin/python3`。打开终端返回的本机地址；端口由当前服务决定。此环境用于启动工作台和静态素材的基础处理，不包含全部人物重建、绑定和渲染依赖。

## 配置图片服务

AI 制作会向所选服务商发送描述和参考图，并按服务商规则产生费用。导入已有图片的工作流不需要发起生图请求。

### Google Cloud Vertex AI

安装认证依赖：

```bash
.local/python/bin/python3 -m pip install -r pipeline/requirements-google-images.txt
```

在仓库根目录创建 `.env`：

```dotenv
STUDIO_IMAGE_PROVIDER=google_cloud
STUDIO_GOOGLE_IMAGE_MODEL=gemini-2.5-flash-image
GCP_PROJECT_ID=your-google-cloud-project
GCP_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=.local/auth/google-cloud/service-account.json
```

相对凭据路径以仓库根目录为准。也支持 Application Default Credentials；留空凭据文件路径时仍需设置项目。Google Cloud 项目需要开通 Vertex AI 与账单，并有相应调用权限。模型可用区域及配额以服务商为准。

### 兼容图片接口

```dotenv
STUDIO_IMAGE_PROVIDER=openai_compatible
STUDIO_IMAGE_BASE_URL=https://your-image-service.example/v1
STUDIO_IMAGE_API_KEY=your-key
```

也支持 `OPENAI_API_KEY`；`STUDIO_IMAGE_API_KEY` 优先。当前适配器包含同步与特定异步图片接口处理，名称为“兼容接口”不代表所有服务均可直接使用。确认所选服务的模型、图片生成及参考图编辑接口与 `pipeline/terrain_images.py` 实现匹配；默认模型配置及历史接口说明见[技术参考](technical-reference.md#地面与道路套件首版)。

配置可在 Studio 设置中切换。`.env` 会为新任务重新读取；终端环境变量优先，修改后需重启。正在运行的任务继续使用原配置。不要提交 `.env`、服务账号或浏览器会话；这些本机目录默认被 Git 忽略。

## 人物制作的额外要求

- **查看已有二维成果：** Godot 4 即可，样例包含纹理和逐帧时序。
- **渲染人物：** 需要 Godot；Blender 是另一种可选渲染后端。默认 Godot 路径为 macOS 的 `/Applications/Godot.app/Contents/MacOS/Godot`，其他安装位置通过 `GODOT_BIN` 指定；Blender 可通过 `BLENDER_BIN` 指定。
- **从原画重建：** 使用 `vendor/TripoSR` 及对应 Python 依赖和模型权重。若未初始化子模块，先运行 `git submodule update --init --recursive`，再按第三方说明配置；基础工作台安装命令不包含这部分。
- **绑定与取得动作：** Mixamo 需要浏览器登录，以及人工摆点和绑定检查。现有绑定可供后续动作继续使用。

人物命令和分阶段要求见[技术参考](technical-reference.md#使用)。通用制作方法见[定位与总流程](production-workflow.md)。
