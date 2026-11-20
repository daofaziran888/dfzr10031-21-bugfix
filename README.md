# 数据分析实验与数据应用服务平台

面向指标口径管理、分析实验设计、OLAP查询、数据看板构建与数据API发布的数据应用平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 指标定义 | `metric_def` | 指标 | 指标编号、指标名称、计算公式 |
| 维度管理 | `dimension` | 分析维度 | 维度编号、维度名称、维度类型 |
| 数据集管理 | `dataset` | 分析数据集 | 数据集编号、数据集名称、来源类型 |
| 分析实验 | `experiment` | 实验方案 | 方案编号、实验名称、分析数据集 |
| OLAP查询 | `query_builder` | 查询模板 | 模板编号、模板名称、查询语句 |
| 数据看板 | `dashboard` | 看板配置 | 看板编号、看板名称、包含图表 |
| 图表配置 | `chart` | 图表 | 图表编号、图表名称、图表类型 |
| 数据API发布 | `data_service` | 数据服务 | 服务编号、服务名称、输出数据集 |
| 智能告警 | `alert` | 告警规则 | 规则编号、告警名称、监控指标 |
| 分析用户组 | `user_group` | 用户组 | 组编号、组名称、组描述 |
| 数据快照 | `snapshot` | 快照记录 | 快照编号、数据集名称、快照时间 |
| 任务调度 | `scheduler` | 调度任务 | 任务编号、任务名称、调度类型 |
| 缓存管理 | `cache` | 缓存配置 | 缓存编号、缓存目标、缓存策略 |
| 分析管道 | `pipeline` | 分析节点 | 节点编号、输入数据集、分析算子 |
| 分析模型 | `model` | 模型配置 | 模型编号、模型名称、模型类型 |
| 数据集市 | `data_mart` | 集市表 | 表编号、表名称、主题域 |
| 数据导出 | `export` | 导出任务 | 任务编号、导出对象、导出格式 |
| 数据审计 | `audit` | 审计记录 | 记录编号、操作类型、操作人 |
| 发布授权预检 | `publish_auth` | 数据域/分组/来源许可/签收 | 数据域编号、授权分组、汇总级别、许可起止日期、许可状态 |

## 发布授权预检（`publish_auth`）

看板已有「可见范围」字段，本模块补上多数据来源的发布授权归属核算，全部规则集中在
`backend/app/services/publish_auth.py`：

- **授权交集**：多数据域组合时，一条明细的发布权限只到该行所需全部授权的交集；组合有效
  汇总级别取各数据域有效级别的最小值，任一数据域为「无」则整体为「无」。
- **团队归属隔离**：数据域的有效级别只由域归属团队、且共享范围命中请求分组的许可链决定；
  其他团队对同一域的许可独立留痕，既不抬升也不拉低定级，不会被当成该域的全部许可。
- **双重校验**：最终判定同时检查来源许可（汇总级别、合作方允许的起止日期、撤回状态）与
  请求人分组（组内共享 / 合作方共享是否命中）。
- **撤回不隐藏**：被撤回的许可在预检结果里显式标记为阻断项；只有归属团队另一条独立有效
  许可覆盖时才放行，撤回痕迹仍随结果返回。
- **组外发布裁决**：合作方仍有共同粒度许可时，把组合页降级到双方共同许可粒度；任一数据域
  无有效许可时收回组合页，按数据域独立交付各自允许的范围。
- **消费范围与签收回查**：按授权范围计算每个用户组可接收的只读页面与汇总数据范围；签收
  记录只追加不改写，解除共享后再次申请可回查上次批准的数据层级，撤回后旧签收依据仍可查。

主要接口（前缀 `/api/publish_auth`）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/domains`、`/groups`、`/licenses`、`/signoffs` | 数据域、分组、来源许可、签收清单 |
| POST | `/precheck` | 发布授权预检，返回组合有效级别、阻断原因与建议发布方式 |
| POST | `/signoffs` | 按预检结论签收发布（降级组合页或按域独立交付） |
| POST | `/licenses/{id}/revoke` | 撤回一项来源许可 |
| POST | `/verify` | 同一账户验证撤回后能否读取，并回查旧签收依据 |
| GET | `/groups/{id}/consumption` | 用户组可接收的只读页面与汇总数据范围 |
| GET | `/groups/{id}/last_approval` | 回查上次批准的数据层级与发布方式 |

离线规则验证（无需安装依赖，标准库即可运行）：

```bash
python3 -I verify/verify_publish_auth.py        # 52 项业务规则
python3 -I verify/verify_publish_auth_http.py   # 28 项 HTTP 路由与链路
```

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。
