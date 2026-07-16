# Label Platform

内部视觉数据集平台，统一管理服务器目录登记、不可变数据集版本、Label Studio 人工审核和 UniTrain 训练流程。当前仓库已包含平台 API、后台任务、数据规范化/校验、真实前端，以及原有 UniTrain 源码。

## Prerequisites

- Python 3.12 or 3.13 and `uv`
- Node.js 22 and npm
- Docker with Compose v2 for PostgreSQL/Redis or the full local stack
- Label Studio 1.13.1 is configured separately; UniTrain 本地训练环境暂不要求安装

## Native development

```bash
cp .env.example .env
mkdir -p var/sources var/managed
uv sync
docker compose up -d postgres redis
uv run alembic upgrade head
uv run label-platform create-admin --email admin@example.test --name Administrator
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

前端地址为 `http://127.0.0.1:5173`，Vite 将 `/api` 转发到 `127.0.0.1:8000`。管理员登录后先在系统管理中配置允许读取的来源根目录；平台只接受该白名单下的相对路径。

本机已安装的 Label Studio 独立环境可按以下方式启动，Local Files 根目录必须与平台 managed 根目录一致：

```bash
LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED=true \
LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT="$(pwd)/var/managed" \
  .venv-labelstudio/bin/label-studio start --host 127.0.0.1 --port 8081
```

首次登录 Label Studio 后生成个人 API Token，把它写入本机 `.env` 的 `PLATFORM_LABEL_STUDIO_API_TOKEN`。同时将 `PLATFORM_LABEL_STUDIO_MOUNT_ROOT` 设置为 `var/managed` 的绝对路径。平台通过 REST 创建独立项目、Local Files storage 和任务，不读取或修改 Label Studio SQLite。项目就绪后，平台会打开 `/projects/<id>/data` 深链接。

UniTrain 通过独立的薄 HTTP 服务接入。它不会调用带显存清理提示的 CLI，也不会自动安装框架环境：

```bash
UNITRAIN_API_RUN_ROOT="$(pwd)/var/unitrain/runs" \
UNITRAIN_API_PUBLIC_URL=http://127.0.0.1:8090 \
  uv run unitrain-api
```

服务提供 `/runs`、日志、指标、停止和模型查询接口。真正提交训练前，仍需在 UniTrain 主机上按原项目方式准备 `.venv-yolo` 或 `.venv-rfdetr`；当前电脑无需为平台开发安装它们。平台先将 READY 版本原子物化为只读 `unitrain-coco-split-v1` 派生包，再通过 REST 提交，canonical 版本不会被训练进程修改。

## Compose stack

```bash
cp .env.example .env
mkdir -p var/sources var/managed
docker compose up --build -d
docker compose exec api label-platform create-admin --email admin@example.test --name Administrator
```

访问 `http://127.0.0.1:8080`。Compose 包含 PostgreSQL 16、Redis 7、API、一个 RQ worker 和 Nginx 静态前端。`var/sources` 在 API/worker 中只读，`var/managed` 读写。在 Linux 主机上若容器无法写入 managed 目录，将该目录所有者设置为镜像内 `platform` 用户（UID/GID 999）。

可选的薄 UniTrain API 服务可用 `docker compose --profile unitrain up --build -d` 启动；该镜像同样不预装 YOLO/RF-DETR 训练环境。实际训练主机配置完成后，将 `PLATFORM_UNITRAIN_URL` 和共享的 `UNITRAIN_EXPORT_PATH` 指向该服务即可。

Label Studio 容器可用 `docker compose --profile integrations up -d label-studio` 启动。完成首次登录并创建 API Token 后，仍需把 Token 配置到平台环境变量。生产环境应使用独立内部主机名和 TLS 反向代理，不共用平台会话 Cookie。

常用运维命令：

```bash
docker compose ps
docker compose logs -f api worker
docker compose exec api alembic upgrade head
docker compose down
```

建议每 5 分钟从受管的 cron/systemd timer 执行一次外部状态对账：

```bash
uv run label-platform reconcile
```

命令只处理非终态审核会话和训练 run。某个外部服务离线时保留本地最后状态，并在输出中报告错误，下一次执行可继续对账。

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

必须替换 `POSTGRES_PASSWORD` 和 `PLATFORM_SESSION_SECRET`，启用 `PLATFORM_SECURE_COOKIES=true`，使用外部 TLS 反向代理，并按设计分别提供平台、Label Studio 与 UniTrain 内部主机名。来源目录保持只读，managed、Label Studio 导出和 UniTrain 运行目录分别持久化。不要将 `.env`、令牌或密码提交到 Git。

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

将数据集放入 `data/` 目录，使用 COCO 格式：

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
