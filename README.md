# Label Platform

面向平台使用人员的操作说明见 [视觉数据集管理平台使用手册](docs/user-guide.md)。

内部视觉数据集平台，统一管理服务器目录登记、不可变数据集版本、Label Studio 人工审核和 UniTrain 训练流程。当前仓库已包含平台 API、后台任务、数据规范化/校验、真实前端，以及原有 UniTrain 源码。

## Prerequisites

- Python 3.12 or 3.13 and `uv`
- Node.js 22 and npm
- Docker with Compose v2 for PostgreSQL/Redis or the full local stack
- Label Studio 1.13.1 is configured separately; UniTrain 本地训练环境暂不要求安装

## 平台数据集导入规范

平台登记的是一个**服务器目录**，不是单独的 JSON 文件。管理员需要先在“系统管理”中把数据所在的上级目录配置为允许读取的来源根目录；登记时选择该根目录下的数据集目录，然后先执行“分析目录”，分析通过后才能登记。

平台支持以下四种来源：

| 来源 | 标注文件 | 用途 |
|------|----------|------|
| Image Directory | 无 | 只有图片、尚未标注的数据集 |
| COCO Detection | 一个 COCO JSON | 目标检测框 |
| COCO Instance Segmentation | 一个 COCO JSON | 多边形或 RLE 实例掩码 |
| Label Studio Export | 一个 JSON 或 ZIP | Label Studio 原生导出或 COCO 导出 |

YOLO TXT、YOLO OBB 和自定义 YOLO JSON 不是平台导入格式，必须先转换为下面定义的单文件 COCO 格式。平台不会读取 `labels/*.txt`，也不会把包含 `bbox_xyxy` 的自定义 JSON 自动转换成 COCO。

### 所有来源的共同要求

- 数据集必须是一个真实目录，并位于管理员配置的允许来源根目录内。前端中选择目录，不选择标注文件。
- 目录及其子目录不能包含符号链接；媒体必须是普通文件。路径必须使用 `/`，不能使用绝对路径、`..` 或反斜杠。
- 支持的图片扩展名为 `.jpg`、`.jpeg`、`.png`、`.webp`，大小写不敏感。每张图片必须能够正常解码。
- 一个数据集目录只能有**一个可识别的标注源**：一个 COCO JSON、一个 Label Studio JSON，或一个 Label Studio ZIP。多个 `train.json`、`val.json`、备份 `.json` 或 JSON 与 ZIP 并存会报 `directory contains multiple supported annotation sources`。
- JSON 必须是 UTF-8。需要保留旧标注文件时，应移出数据集目录，或使用不以 `.json` 结尾的名称，例如 `annotations.original.json.bak`。
- 图片引用必须指向所选数据集目录内实际存在的文件；同一图片路径不能重复。文件名相同但位于不同子目录是允许的。
- 分析后、登记前不要修改图片或标注。平台会校验分析指纹，内容发生变化时需要重新分析。
- 目录中的其他普通文件不会参与数据集，但会在分析结果中列为不支持文件。

### 纯图片目录

适合尚未标注的数据。图片可以直接放在根目录，也可以任意分层：

```text
dataset/
├── camera-a/
│   ├── 00001.jpg
│   └── 00002.jpg
└── camera-b/
    └── 00001.png
```

目录内不能同时存在可识别的 COCO、Label Studio JSON 或 ZIP，否则平台会按标注数据集处理。登记时必须在“初始类别”中填写至少一个非空、互不重复的类别，并选择“目标检测”或“实例分割”；纯图片数据登记后的标注数为 0。

如果目录中存在自定义 `annotations.json`，但它不是 COCO 对象或 Label Studio 任务数组，平台可能仍把目录识别为 Image Directory 并显示 0 个标注。这不表示自定义标注已成功导入。

### COCO Detection

推荐结构如下。标注文件名和所在子目录可以不同，但整个数据集目录中只能有一个 COCO JSON：

```text
dataset/
├── images/
│   ├── 00001.jpg
│   └── 00002.jpg
└── annotations.json
```

可直接导入的最小完整示例：

```json
{
  "info": {
    "description": "mouse detection dataset"
  },
  "images": [
    {
      "id": 1,
      "file_name": "images/00001.jpg",
      "width": 640,
      "height": 480
    },
    {
      "id": 2,
      "file_name": "images/00002.jpg",
      "width": 640,
      "height": 480
    }
  ],
  "annotations": [
    {
      "id": 1,
      "image_id": 1,
      "category_id": 1,
      "bbox": [305, 116, 151, 128],
      "area": 19328,
      "iscrowd": 0
    }
  ],
  "categories": [
    {
      "id": 1,
      "name": "mouse"
    }
  ]
}
```

COCO 字段约束：

- 根对象必须包含 `images`、`annotations`、`categories` 三个数组。`images` 和 `categories` 不能为空；允许存在未标注图片，因此 `annotations` 可以为空。
- `images[].id`、`annotations[].id`、`categories[].id` 必须存在且在各自数组中唯一。类别 ID 可以从 0 或 1 开始，平台登记时会重新映射为从 1 开始的连续 ID。
- `images[].file_name` 是相对于**所选数据集根目录**的 POSIX 路径，不是相对于 JSON 文件的路径。上例必须能解析到 `dataset/images/00001.jpg`。
- `images[].width` 和 `height` 可以省略；如果提供，必须与图片解码后的真实尺寸完全一致。
- `annotations[].image_id` 和 `category_id` 必须分别引用已存在的图片和类别。
- 检测框必须使用 COCO 的 `[x, y, width, height]`，不是 `[x1, y1, x2, y2]`。四个值必须有限，`width`、`height` 必须大于 0，框不能超出图片边界。
- `area` 和 `iscrowd` 可以提供；平台会根据规范化后的几何重新生成它们。
- 类别名称必须是非空且互不重复的字符串。COCO 数据的类别来自 `categories`，前端“初始类别”和“任务类型”不会覆盖 COCO 文件中的定义。

以下路径是正确的：

```json
{"file_name": "images/00001.jpg"}
```

以下路径会失败，除非这些层级确实位于所选数据集目录内：

```json
{"file_name": "output/mouse008/detection_dataset/images/00001.jpg"}
```

目录名不强制必须叫 `images`；`image/00001.jpg` 也可以，但 JSON 中的 `file_name` 必须与磁盘上的真实目录名完全一致。

### COCO Instance Segmentation

目录要求与 COCO Detection 相同。当任意标注包含非空 `segmentation` 时，整个来源会被识别为实例分割数据集，此时每条标注都必须具有有效的实例掩码，不能混入只有 `bbox` 的检测标注。

多边形示例：

```json
{
  "id": 1,
  "image_id": 1,
  "category_id": 1,
  "bbox": [10, 20, 100, 80],
  "segmentation": [
    [10, 20, 110, 20, 110, 100, 10, 100]
  ],
  "area": 8000,
  "iscrowd": 0
}
```

`segmentation` 支持：

- COCO 多边形数组。每个多边形至少 3 个点，即至少 6 个有限数字，并且坐标数量必须为偶数。
- COCO RLE 对象：`{"size": [height, width], "counts": ...}`。`size` 必须与真实图片尺寸一致，`counts` 支持未压缩数组或压缩字符串。

掩码必须非空、尺寸正确且位于图片范围内。平台会从掩码重新计算 `bbox` 和 `area`。

### Label Studio 导出

平台支持以下导出内容：

- Label Studio 原生 JSON 任务数组。
- 包含原生 JSON 的 ZIP；优先查找 `result.json`。
- Label Studio 的 COCO JSON 对象。
- 包含 COCO JSON 的 ZIP；优先查找 `result_coco.json`。

推荐目录：

```text
dataset/
├── images/
│   ├── 00001.jpg
│   └── 00002.jpg
└── result.json
```

原生 JSON 的关键结构如下：

```json
[
  {
    "id": 1,
    "data": {
      "image": "images/00001.jpg",
      "split": "train",
      "group_key": "video-001"
    },
    "annotations": [
      {
        "result": [
          {
            "type": "rectanglelabels",
            "original_width": 640,
            "original_height": 480,
            "value": {
              "x": 10,
              "y": 20,
              "width": 25,
              "height": 30,
              "rectanglelabels": ["mouse"]
            }
          }
        ]
      }
    ]
  }
]
```

Label Studio 约束：

- 每个任务必须有 `data.image`，并能解析到导出 JSON/ZIP 所在目录下的本地图片。支持普通相对路径和 `/data/local-files/?d=...` 引用；外部 HTTP/HTTPS 图片 URL 不支持。
- ZIP 只承载标注 JSON，图片仍应作为 ZIP 外部文件放在同一个数据集目录中；ZIP 解压后总大小上限为 512 MiB。
- 支持 `rectanglelabels`、`polygonlabels`、`brushlabels`；其他结果类型会被忽略。每个受支持结果必须且只能包含一个类别标签。
- `rectanglelabels` 的 `x`、`y`、`width`、`height` 和 `polygonlabels` 的点坐标是 Label Studio 的百分比坐标。
- `original_width`、`original_height` 必须与真实图片尺寸一致。Brush RLE 的尺寸也必须匹配。
- 一个任务有多次标注时，平台使用最后一个未取消的 annotation；没有有效 annotation 的任务仍会作为未标注图片导入。
- 类别默认从有效结果中发现。完全未标注的原生导出必须在前端“初始类别”中提供类别；一旦提供，导出中的所有标签必须属于该列表。COCO 导出的类别仍以 COCO `categories` 为准。
- `data.group_key` 或 `data.episode_id` 可用于把同一序列保持在同一个数据切分中。

### 数据切分

平台登记时生成 `train`、`val`、`test` 切分。当前前端固定使用 `80% / 20% / 0%` 和种子 `42`，对相同内容会得到稳定结果。

- COCO 可在 `images[]` 中使用可选字段 `split: "train" | "val" | "test"` 和 `group_key`。
- Label Studio 原生导出可在 `data` 中使用 `split`，以及 `group_key` 或 `episode_id`。
- 同一个 `group_key`/`episode_id` 的图片不会被拆到不同切分；同一组内不能声明冲突的显式 `split`。
- 平台**不会**根据 `images/train/`、`images/val/` 的目录名推断切分。没有显式 `split` 时，按种子和比例重新分配。
- 平台导入不接受 `annotations/train.json` 与 `annotations/val.json` 两个 COCO 标注源。需要先合并为一个 COCO JSON，并通过 `images[].split` 保留原切分。

### 常见导入错误

| 错误 | 原因与处理 |
|------|------------|
| `directory contains multiple supported annotation sources` | 目录中有多个 COCO/Label Studio JSON 或 ZIP。只保留一个；备份不要以 `.json` 结尾。 |
| `source image file does not exist` | `file_name` 或 `data.image` 无法从所选数据集根目录解析。改成实际相对路径，例如 `images/00001.jpg`。 |
| `source directory must contain exactly one COCO annotation file` | 没有找到完整 COCO 对象，或找到多个包含 `images`、`annotations`、`categories` 的 JSON。 |
| `bbox width and height must be positive` | 把 `[x1, y1, x2, y2]` 误当成 COCO bbox，或宽高为 0/负数。转换为 `[x1, y1, x2-x1, y2-y1]`。 |
| `bbox must stay inside image bounds` | 框的坐标或宽高超过真实图片尺寸。 |
| `image ... width/height does not match the image file` | JSON 声明尺寸与图片解码后的真实尺寸不一致。修正或删除可选的宽高字段。 |
| 分析显示 `Image Directory`、标注为 0 | 标注文件不是受支持的 COCO/Label Studio 结构。先转换格式，不要直接登记。 |

## Native development

```bash
cp .env.example .env
mkdir -p var/sources var/managed
uv sync
docker compose up -d postgres redis
uv run alembic upgrade head
uv run uvicorn label_platform.api.app:create_app_from_env --factory --host 127.0.0.1 --port 8000
```

在另一个终端启动单并发后台 worker：

```bash
uv run label-platform worker
```

macOS 原生开发应使用同进程 worker，避免系统框架与 fork 冲突：

```bash
uv run label-platform worker --simple
```

Compose/Linux 部署继续使用默认 worker，以保留独立 job 子进程和超时隔离。

再启动前端：

```bash
cd web
npm ci
npm run dev
```

前端地址为 `http://127.0.0.1:5173`，Vite 将 `/api` 转发到 `127.0.0.1:8000`。平台面向部门内部使用，不设置平台登录或用户权限；所有打开平台页面的人员都可以使用数据集、审核、训练和系统管理功能。登记数据集前，先在系统管理中配置允许读取的来源根目录；平台只接受该白名单下的相对路径。

本机已安装的 Label Studio 独立环境可按以下方式启动，Local Files 根目录必须与平台 managed 根目录一致：

```bash
LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED=true \
LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT="$(pwd)/var/managed" \
  .venv-labelstudio/bin/label-studio start --host 127.0.0.1 --port 8081
```

首次登录 Label Studio 后生成个人 API Token，把它写入本机 `.env` 的 `PLATFORM_LABEL_STUDIO_API_TOKEN`。同时将 `PLATFORM_LABEL_STUDIO_MOUNT_ROOT` 设置为 `var/managed` 的绝对路径。平台通过 REST 创建独立项目、Local Files storage 和任务，不读取或修改 Label Studio SQLite。项目就绪后，平台会打开 `/projects/<id>/data` 深链接。

`PLATFORM_LABEL_STUDIO_API_TOKEN` 只认证“平台后端 -> Label Studio API”的请求，不会给浏览器创建登录 Cookie。每个新的浏览器配置仍需登录 Label Studio 一次。Label Studio Community 当前没有受支持的匿名 UI 开关；部门内部最简单的做法是使用共享账号并保留浏览器会话。若必须统一免登录，应接入现有 SSO/反向代理认证，而不是把 API Token 或共享密码暴露到前端。

UniTrain 通过独立的薄 HTTP 服务接入。它不会调用带显存清理提示的 CLI，也不会自动安装框架环境：

```bash
UNITRAIN_API_RUN_ROOT="$(pwd)/var/unitrain/runs" \
UNITRAIN_API_PUBLIC_URL=http://127.0.0.1:8090 \
  uv run unitrain-api
```

服务提供 `/runs`、日志、指标、停止和模型查询接口。真正提交训练前，仍需在 UniTrain 主机上按原项目方式准备 `.venv-yolo` 或 `.venv-rfdetr`；当前电脑无需为平台开发安装它们。平台先将 READY 版本原子物化为只读 `unitrain-coco-split-v1` 派生包，再通过 REST 提交，canonical 版本不会被训练进程修改。

## 新服务器 Compose 部署

以下流程适用于一台只授予当前用户 Docker 权限、没有 `sudo` 权限的新 Linux 服务器。命令均在仓库根目录执行。Compose 包含 PostgreSQL、Redis、平台 API、RQ worker、Web、Label Studio 和薄 UnitTrain API。

### 1. 准备配置

```bash
cp .env.example .env
openssl rand -hex 32  # 生成 PLATFORM_UNITRAIN_API_TOKEN
```

至少修改 `.env` 中的以下配置，不要提交该文件：

```dotenv
POSTGRES_DB=platform
POSTGRES_USER=platform
POSTGRES_PASSWORD=<strong-database-password>

PLATFORM_ENVIRONMENT=production

# API/worker 在 Docker 网络中访问 Label Studio 的内部地址。
PLATFORM_LABEL_STUDIO_URL=http://label-studio:8080
# 浏览器跳转地址。同一局域网访问时填写服务器 IP；有反向代理时填写 HTTPS 域名。
PLATFORM_LABEL_STUDIO_PUBLIC_URL=http://10.10.16.58:8081
PLATFORM_LABEL_STUDIO_API_TOKEN=

PLATFORM_UNITRAIN_URL=http://unitrain-api:8090
PLATFORM_UNITRAIN_API_TOKEN=<second-random-value>
UNITRAIN_API_PUBLIC_URL=http://127.0.0.1:8090

SOURCE_DATA_PATH=./var/sources
MANAGED_DATA_PATH=./var/managed
JOB_LOG_PATH=./var/logs/jobs
LABEL_STUDIO_EXPORT_PATH=./var/labelstudio/exports
LABEL_STUDIO_APP_PATH=./var/labelstudio/app
UNITRAIN_EXPORT_PATH=./var/unitrain/exports
UNITRAIN_RUN_PATH=./var/unitrain/runs
```

`PLATFORM_LABEL_STUDIO_URL` 与 `PLATFORM_LABEL_STUDIO_PUBLIC_URL` 用途不同：前者必须能从 API/worker 容器访问，后者必须能从操作者的浏览器访问。平台 Web 容器默认监听 `0.0.0.0:8080`，同一局域网可直接打开 `http://10.10.16.58:8080`，根地址会自动进入 `/datasets`。服务器 IP 变化时，应同步修改 `PLATFORM_LABEL_STUDIO_PUBLIC_URL` 并重新创建 API 和 worker 容器。

### 2. 准备持久化目录

```bash
mkdir -p \
  var/sources \
  var/managed \
  var/logs/jobs \
  var/labelstudio/app \
  var/labelstudio/exports \
  var/unitrain/exports \
  var/unitrain/runs
```

先构建平台镜像并拉取集成镜像：

```bash
docker compose --profile integrations --profile unitrain build
docker compose --profile integrations pull label-studio
```

没有 `sudo` 时，使用一次性 root 容器设置挂载目录权限。平台目录属于镜像内的 `platform` 用户，Label Studio 数据目录属于 UID/GID 1001：

```bash
docker compose run --rm --no-deps \
  --user 0:0 \
  --entrypoint sh \
  worker \
  -c 'chown -R platform:platform \
        /data/managed \
        /data/logs/jobs \
        /data/labelstudio/exports \
        /data/unitrain/exports'

docker compose --profile integrations run --rm --no-deps \
  --user 0:0 \
  --entrypoint sh \
  label-studio \
  -c 'mkdir -p /label-studio/data/media && \
      chown -R 1001:1001 /label-studio/data && \
      chmod -R u+rwX /label-studio/data'

docker compose --profile unitrain run --rm --no-deps \
  --user 0:0 \
  --entrypoint sh \
  unitrain-api \
  -c 'chown -R platform:platform /data/runs'
```

这些权限保存在宿主机 bind mount 中，普通 `build`、`up`、`down` 或容器重建不会重置。只有删除 `var/`、更换路径、迁移服务器或更改容器 UID 时才需要重新执行。

### 3. 首次启动 Label Studio

先只启动依赖和 Label Studio：

```bash
docker compose up -d postgres redis
docker compose --profile integrations up -d label-studio
docker compose ps -a
docker compose logs --tail=100 label-studio
curl -fsS http://127.0.0.1:8081/health
```

如果端口只绑定服务器回环地址，在操作者电脑上建立隧道：

```bash
ssh -N \
  -L 8080:127.0.0.1:8080 \
  -L 8081:127.0.0.1:8081 \
  -L 8090:127.0.0.1:8090 \
  <server>
```

浏览器打开 `http://127.0.0.1:8081`，创建 Owner/管理员账号并生成 Legacy API Token。当前连接器不能直接使用声明为 `token_type: refresh` 的 JWT refresh token。将新 Token 写入 `.env`：

```dotenv
PLATFORM_LABEL_STUDIO_API_TOKEN=<legacy-api-token>
```

该 Token 不替代 Label Studio 网页登录。新的浏览器配置首次打开审核链接时仍需使用 Label Studio 账号登录，之后由浏览器 Cookie 保持会话。

Token 和数据库密码一旦出现在聊天、日志或工单中，应立即撤销并轮换。

### 4. 启动完整服务

Compose 会自动执行数据库迁移：

```bash
docker compose \
  --profile integrations \
  --profile unitrain \
  up -d --build

docker compose ps -a
```

平台没有管理员初始化步骤。数据库迁移完成后，所有内部使用者直接打开 Web 地址即可进入数据集页面。

修改 `.env` 后，`docker compose restart` 不会刷新容器环境变量，必须重新创建相关服务：

```bash
docker compose --profile unitrain \
  up -d --force-recreate api worker unitrain-api
```

### 5. 部署验收

确认平台实际加载的是 Docker 内部服务地址，且 Token 只检查是否存在，不输出内容：

```bash
docker compose exec -T api python -c '
from label_platform.config import Settings
s = Settings()
print("label_studio_url:", s.label_studio_url)
print("label_studio_public_url:", s.label_studio_public_url)
print("label_studio_token:", "set" if s.label_studio_api_token else "missing")
print("unitrain_url:", s.unitrain_url)
print("unitrain_token:", "set" if s.unitrain_api_token else "missing")
'

docker compose exec -T worker rq info -u redis://redis:6379/0
docker compose logs --tail=100 api worker label-studio unitrain-api
```

预期内部地址分别为 `http://label-studio:8080` 和 `http://unitrain-api:8090`，RQ 输出应显示一个监听 `dataset-operations` 的 worker。通过 SSH 隧道访问平台 `http://127.0.0.1:8080` 和 Label Studio `http://127.0.0.1:8081`。

### 6. 日常启停和更新

正常启动全部服务：

```bash
docker compose --profile integrations --profile unitrain up -d
```

只停止容器但保留容器定义：

```bash
docker compose --profile integrations --profile unitrain stop
```

停止并删除项目容器及 Compose 网络，但保留数据库卷和 `var/` 数据：

```bash
docker compose --profile integrations --profile unitrain down
```

代码更新后重建：

```bash
docker compose --profile integrations --profile unitrain up -d --build
```

查看日志和执行外部状态对账：

```bash
docker compose logs -f api worker label-studio unitrain-api
docker compose exec api label-platform reconcile
```

不要执行 `docker compose down -v`，也不要删除整个 `var/`。前者会删除 PostgreSQL/Redis 卷，后者会删除受管数据集、Label Studio 数据、导出文件和 UnitTrain 运行记录。

### 7. 镜像代理

无法直接访问 Docker Hub/GHCR 时，需要修改三类基础镜像：

- `compose.yaml`：PostgreSQL、Redis、Label Studio。
- `deploy/web.Dockerfile`：`node:22-alpine` 与 `nginx:1.27-alpine`。
- `deploy/api.Dockerfile`：`ghcr.io/astral-sh/uv:python3.13-bookworm-slim`。

以前端为例，使用可访问的镜像代理替换两个 `FROM`：

```dockerfile
FROM <docker-hub-mirror>/node:22-alpine AS build
# build stage commands
FROM <docker-hub-mirror>/nginx:1.27-alpine
```

修改后单独重建 Web：

```bash
docker compose build --no-cache web
docker compose up -d web
```

### 8. 使用宿主机 GPU UnitTrain

Compose 中的薄 `unitrain-api` 不包含宿主机未提交到 Git 的 `.venv-yolo`、`.venv-rfdetr` 和 GPU 运行环境。训练环境安装在平台所在宿主机时，应让 API/worker 容器连接宿主机原生运行的 UnitTrain API，而不是启动 `unitrain-api` Compose profile。

先确认框架环境位于仓库根目录并能独立训练：

```bash
test -x .venv-yolo/bin/python && echo yolo-ready
test -x .venv-rfdetr/bin/python && echo rfdetr-ready
nvidia-smi
```

停止容器版 UnitTrain API，避免占用宿主机 `8090`：

```bash
docker compose --profile unitrain stop unitrain-api
```

设置 `.env`。`PLATFORM_UNITRAIN_MOUNT_ROOT` 必须是宿主机可见的绝对导出路径，因为平台会把该路径提交给原生 UnitTrain 进程：

```dotenv
PLATFORM_UNITRAIN_URL=http://host.docker.internal:8090
PLATFORM_UNITRAIN_MOUNT_ROOT=/absolute/path/to/label-platform/var/unitrain/exports
PLATFORM_UNITRAIN_API_TOKEN=<shared-token>

UNITRAIN_API_RUN_ROOT=/absolute/path/to/label-platform/var/unitrain/runs
UNITRAIN_API_API_TOKEN=<same-shared-token>
UNITRAIN_API_PUBLIC_URL=http://127.0.0.1:8090
UNITRAIN_API_HOST=0.0.0.0
UNITRAIN_API_PORT=8090
```

如果 `var/unitrain/runs` 曾由 Compose 容器创建，可在没有 `sudo` 的服务器上把目录归还给当前宿主机用户：

```bash
HOST_UID=$(id -u)
HOST_GID=$(id -g)
docker compose --profile unitrain run --rm --no-deps \
  --user 0:0 \
  --entrypoint sh \
  unitrain-api \
  -c "chown -R ${HOST_UID}:${HOST_GID} /data/runs"
```

从仓库根目录启动原生服务：

```bash
mkdir -p var/unitrain/runs
nohup uv run unitrain-api > var/unitrain/unitrain-api.log 2>&1 &
echo $!
```

Compose 已为平台容器配置 `host.docker.internal:host-gateway`。重新创建 API/worker 以加载新地址和宿主机路径，不要重新启动 `unitrain-api` profile：

```bash
docker compose up -d --force-recreate api worker
```

验证完整通路，命令不会输出 Token：

```bash
docker compose exec -T api python -c '
from label_platform.config import Settings
from label_platform.integrations.unitrain import create_unitrain_connector
s = Settings()
print("url:", s.unitrain_url)
print("mount_root:", s.unitrain_mount_root)
c = create_unitrain_connector(s)
print("version:", c.health())
c.close()
'
```

预期 URL 为 `http://host.docker.internal:8090`，mount root 为宿主机绝对路径。训练失败时同时查看平台 worker 和原生 UnitTrain 日志：

```bash
docker compose logs --tail=200 worker
tail -n 200 var/unitrain/unitrain-api.log
find var/unitrain/runs -maxdepth 2 -name run.log -print
```

平台正式数据集仍保存在 `var/managed/<dataset-id>/versions/vN`。提交训练时会生成只读派生包 `var/unitrain/exports/<version-id>/unitrain-coco-split-v1`，原生 UnitTrain 只读取派生包，不修改正式版本。

## Backup and restore

备份必须在同一恢复点保存 PostgreSQL 与文件目录。至少包括 `var/managed`、`var/labelstudio`、`var/unitrain` 和数据库导出；来源目录由原存储系统单独保护。

```bash
mkdir -p backups/$(date +%F)
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > backups/$(date +%F)/platform.dump
rsync -a --delete var/managed/ backups/$(date +%F)/managed/
rsync -a --delete var/labelstudio/ backups/$(date +%F)/labelstudio/
rsync -a --delete var/unitrain/ backups/$(date +%F)/unitrain/
```

恢复时先停止 API、worker、Label Studio 与 UnitTrain，恢复三个文件目录，再对空数据库执行 `pg_restore --clean --if-exists`。恢复完成后运行 `alembic upgrade head` 和 `label-platform reconcile`，确认 managed 版本校验、Label Studio 项目绑定及 UniTrain run ID 都可解析后再开放 Web 流量。备份目录不得放在被 `rsync --delete` 的源目录中。

## Verification

```bash
uv run pytest -m "not integration" -v
uv run ruff check label_platform tests
uv run mypy label_platform
cd web
npm run test:run
npm run typecheck
npm run build
```

真实 PostgreSQL/Redis 集成测试会清空目标数据库中的平台业务表，只能对一次性测试数据库执行：

```bash
docker compose up -d postgres redis
PLATFORM_INTEGRATION_DATABASE_URL=postgresql+psycopg://platform:platform-dev-password@127.0.0.1:5432/platform \
  uv run pytest -m integration tests/integration/test_register_dataset.py -v
```

该测试通过 Redis/RQ 分别执行分析和登记作业，发布 10 张图片的 `platform-coco-v1` 不可变 v1，并验证幂等重提不会创建第二个作业。

## Production requirements

必须替换 `POSTGRES_PASSWORD`，使用外部 TLS 反向代理，并按设计分别提供平台、Label Studio 与 UniTrain 内部主机名。来源目录保持只读，managed、Label Studio 导出和 UniTrain 运行目录分别持久化。不要将 `.env`、令牌或密码提交到 Git。

## Bundled UniTrain source

> 通用模型训练框架 (Universal Training Framework)

轻量级深度学习目标检测框架统一封装，一键调用 RF-DETR 和 Ultralytics。

## 特性

- 🔧 **统一接口**：一套 API 调用不同框架的训练、推理、导出功能
- 🔒 **环境隔离**：使用 uv 为每个框架创建独立虚拟环境，避免依赖冲突
- 🚀 **智能初始化**：自动检测并初始化所需的子仓库和虚拟环境
- 📊 **通用配置**：YAML 配置自动转换为各框架所需格式
- 📁 **数据转换**：以 COCO 格式为标准，自动转换为 YOLO 格式

## 快速开始

### 1. 初始化环境

```bash
# 克隆项目
git clone <repo-url>
cd unitrain

# 安装 uv (如未安装)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 一键初始化所有环境（自动克隆子仓库 + 创建虚拟环境）
./run.sh setup

# 或仅初始化特定框架
./run.sh setup --framework rfdetr
./run.sh setup --framework yolo
```

### 2. 准备数据

以下结构仅用于**绕过平台、直接调用 UniTrain**。它不是 Label Platform 的导入结构；平台导入必须遵循前面的“平台数据集导入规范”，一个目录中只能保留一个 COCO 标注 JSON。

直接使用 UniTrain 时，将数据集放入 `data/` 目录，使用 COCO 格式：

```
data/
├── images/
│   ├── train/
│   └── val/
└── annotations/
    ├── train.json
    └── val.json
```

### 3. 训练

```bash
# 使用统一配置训练（自动检查环境）
./run.sh train --config configs/rfdetr.yaml
./run.sh train --config configs/example.yaml
```

### 4. 推理

```bash
./run.sh predict --config configs/example.yaml --source image.jpg
```

### 5. 导出

```bash
./run.sh export --config configs/example.yaml --format onnx
```

### 6. 评估

```bash
# 独立评估（需指定权重路径）
./run.sh eval --config configs/rfdetr.yaml --weights outputs/.../best.pth

# 训练后自动评估（默认行为，训练完成后自动运行）
./run.sh train --config configs/rfdetr.yaml

# 跳过自动评估
./run.sh train --config configs/rfdetr.yaml --skip-eval
```

评估报告输出至 `<训练输出目录>/eval/`，包含：

| 文件 | 说明 |
|------|------|
| `eval_metrics.json` | 完整指标 JSON |
| `report.csv` / `report.md` | 表格报告 |
| `plots/per_class_mAP50.png` | 每类 mAP@50 柱状图 (含 0-1 和 0.8-1 双面板) |
| `plots/per_class_f1.png` | 每类 F1 柱状图 |
| `plots/per_class_precision.png` | 每类 Precision 柱状图 |
| `plots/per_class_recall.png` | 每类 Recall 柱状图 |
| `plots/f1_confidence_box.png` | Box F1 vs Confidence 曲线 (每类 + 平均) |
| `plots/f1_confidence_box_zoomed.png` | Box F1 放大 (Y: 0.9-1.0) |
| `plots/f1_confidence_mask.png` | Mask F1 vs Confidence (分割模型) |
| `plots/f1_confidence_mask_zoomed.png` | Mask F1 放大 |
| `plots/training_loss.png` | 训练损失曲线 |
| `plots/mAP_epochs.png` | mAP vs Epochs |
| `plots/overall_summary.png` | 总体雷达图 |

### 7. 进入框架环境（高级用法）

```bash
# 进入 RF-DETR 虚拟环境，可直接使用框架 API
./run.sh shell --framework rfdetr

# 进入 YOLO 虚拟环境
./run.sh shell --framework yolo
```

## 配置示例

```yaml
# configs/example.yaml
framework: ultralytics  # 或 rfdetr
model: yolo11n          # ultralytics: yolo11n/yolo26n/..., rfdetr: nano/small/medium/large
task: detect            # detect | segment | obb

data:
  path: data/
  format: coco          # 自动转换为框架所需格式

train:
  epochs: 100
  imgsz: 640
  batch: 16
  device: 0             # GPU 选择：0 (单GPU) | "0,1" (多GPU) | "cpu"

export:
  format: onnx          # onnx, tensorrt, etc.
```

## GPU 选择

UniTrain 支持灵活的 GPU 设备选择：

### 单 GPU 训练

```yaml
train:
  device: 0              # 使用 GPU 0
```

### 多 GPU 训练

```yaml
train:
  device: "0,1"          # 使用 GPU 0 和 1（需要用字符串格式）
  batch: 8               # 每个 GPU 的 batch size
```

### CPU 训练

```yaml
train:
  device: "cpu"          # 使用 CPU（测试用）
```

### 使用环境变量（替代方法）

```bash
# 指定使用 GPU 1
CUDA_VISIBLE_DEVICES=1 ./run.sh train --config configs/rfdetr.yaml

# 使用多个 GPU
CUDA_VISIBLE_DEVICES=0,1,2,3 ./run.sh train --config configs/example.yaml
```

更多 GPU 配置示例请参考：[configs/example.yaml](configs/example.yaml) 末尾的 GPU 配置参考部分

## 支持的框架

| 框架 | 模型 | 任务 |
|------|------|------|
| Ultralytics | YOLO11 (n/s/m/l/x), YOLO26 (n/s/m/l/x), YOLOE | 检测、分割、OBB、开放词汇 |
| RF-DETR | Nano/Small/Medium/Base/Large/Seg | 检测、分割 |

### YOLO26 模型列表

| 任务 | 模型名 | 配置示例 |
|------|---------|----------|
| 目标检测 | `yolo26n/s/m/l/x` | `model: yolo26n` |
| 实例分割 | `yolo26n-seg` … `yolo26x-seg` | `model: yolo26n-seg`, `task: segment` |
| 旋转框 (OBB) | `yolo26n-obb` … `yolo26x-obb` | `model: yolo26n-obb`, `task: obb` |

## 数据格式

推荐使用 **COCO 格式** 作为统一数据格式：

- RF-DETR：原生支持 COCO
- Ultralytics：自动转换为 YOLO 格式
- **OBB 任务**：数据需预先为 YOLO OBB 格式 (`class_id x1 y1 x2 y2 x3 y3 x4 y4`)，设置 `task: obb` 时自动跳过 COCO 转换

转换命令：
```bash
python -m unitrain.data_converter --input data/coco --output data/yolo --task detect
python -m unitrain.data_converter --input data/coco --output data/yolo --task segment
```

## 项目结构

```
unitrain/
├── run.sh                # 统一运行脚本（推荐入口）
├── vendors/              # Git 子模块（自动初始化）
│   ├── rf-detr/
│   └── ultralytics/
├── envs/                 # 各框架依赖配置
├── configs/              # 示例配置文件
├── unitrain/             # 核心封装代码
│   ├── config_gen.py     # 配置生成器
│   ├── eval_report.py    # 统一评估报告 (11 种图表 + 多格式输出)
│   ├── data_converter.py # 数据格式转换
│   ├── utils.py          # 通用工具函数
│   └── runners/          # 框架 Runner
│       ├── base.py       # BaseRunner 抽象基类
│       ├── rfdetr.py     # RFDETRRunner
│       ├── ultralytics.py# UltralyticsRunner
│       └── _scripts/     # 框架 venv 中执行的脚本
│           ├── rfdetr_eval.py   # RF-DETR 评估
│           ├── yolo_eval.py     # YOLO 评估
│           ├── rfdetr_train.py  # RF-DETR 训练
│           ├── yolo_train.py    # YOLO 训练
│           └── weight_utils.py  # 权重路径解析
├── cli/                  # CLI 入口脚本
│   ├── train.py          # 训练入口 (训练后自动评估)
│   ├── eval.py           # 评估入口
│   ├── predict.py        # 推理入口
│   └── export.py         # 导出入口
```
