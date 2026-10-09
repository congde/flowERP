# FlowERP

FlowERP 是一个独立的电商 ERP，管理商品、客户、供应商、采购、库存、销售和财务。典型业务流程是：**采购审批与入库 → 接单与预占 → 发货 → 开票和收付款 → 对账**。

项目采用 Python + 原生 HTML/CSS/JavaScript + SQLite，一个服务同时提供页面和 API。首次使用按下面的“启动 → 登录”顺序操作；了解实现再看[项目架构](#项目架构)。

## 快速开始

准备 Python **3.10 或以上**，在本仓库根目录执行。下面的目录是示例，请改成自己的检出位置；每条命令成功后再执行下一条。启动命令会启用账号登录。

### Windows / PowerShell

```powershell
Set-Location D:\work\flowERP
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
$env:FLOWERP_AUTH_REQUIRED = "true"
.\.venv\Scripts\python.exe -X utf8 -m flowerp serve --port 8000 --runtime-dir .runtime
```

### macOS / zsh

```zsh
cd ~/work/flowERP
python3 --version
python3 -m venv .venv
./.venv/bin/python -m pip install -e .
export FLOWERP_AUTH_REQUIRED=true
./.venv/bin/python -X utf8 -m flowerp serve --port 8000 --runtime-dir .runtime
```

看到 `"event": "server_started"` 后，保持终端打开，用浏览器访问 [http://127.0.0.1:8000/](http://127.0.0.1:8000/)。如果配置了其他监听地址，以日志中的 `url` 为准。首次使用会出现“创建您的工作空间”。

按 `Ctrl+C` 停止。以后重新启动时，在仓库根目录执行对应代码块的**最后两行**即可。业务数据和账号保存在 `.runtime/flowerp.db`，继续使用同一运行目录就能保留它们。启动报错时查看[排错说明](docs/usage.md#启动排错)。

## 登录与账号

### 首次使用：创建管理员

全新数据库首次启动时，在“创建您的工作空间”页面填写组织名称、管理员账号和两次密码，点击“创建并进入系统”。**管理员密码由你设置，至少 10 位，没有通用默认密码。** 已初始化的数据库直接登录；本机本次创建的账号见下方执行记录。

| 后续登录时填写 | 内容 |
| --- | --- |
| 组织代码 | `DEFAULT`，与组织显示名称不同 |
| 管理员账号 | 初始化时填写的账号，表单默认 `admin` |
| 密码 | 初始化时自己设置的密码 |

进入系统后，管理员可在“系统与用户 → 新增用户”创建业务账号。修改密码和角色见[账号维护](docs/usage.md#账号维护)。

### 需要样例数据：使用演示账号

普通启动不会创建演示账号。新环境需要先按[演示库创建步骤](docs/usage.md#演示数据与账号)，在独立的 `.runtime/demo` 目录中创建管理员、生成数据并启动服务，再使用以下账号登录。

**本机执行记录（2026-10-09）：** 已备份原数据库，创建管理员，并执行 `mock-data --runtime-dir .runtime`，在 `.runtime/flowerp.db` 中生成以下五个账号和完整样例业务数据。管理员及五个演示账号均通过登录 API 路由验证（返回 `200`），`verify-mock-data --runtime-dir .runtime` 检查通过。此记录仅代表本机执行结果；数据库不随 Git 分发，新检出的项目仍须自行初始化。

本机按“快速开始”的命令使用 **`--runtime-dir .runtime`** 启动后即可登录，无需再次初始化。管理员账号为 `admin`，随机初始密码保存在本机 `.runtime/admin-credentials.txt`，不写入 README、不提交 Git；演示账号使用下方统一密码。本次数据生成与账号验证报告保存在 `.runtime/reports/`，操作前备份保存在 `.runtime/backups/`。

这些账号的组织代码均为 `DEFAULT`，初始密码均为 **`Mock-Only-2026!`**；该密码只用于演示账号。

| 演示账号 | 已实现的后端能力 |
| --- | --- |
| `mock-sales` | 销售制单、确认和预占 |
| `mock-buyer` | 采购制单和提交审批 |
| `mock-warehouse` | 入库、发货、采购收货与调拨；不含盘点调整权限 |
| `mock-finance` | 开立业务发票、登记收付款与核销 |
| `mock-auditor` | 业务查询、审计日志查询和对账检查；对账会生成记录 |

这些能力已用演示角色在临时数据库中验证，但尚未完成五类账号的浏览器全流程验收。当前 `mock-sales` 的销售页存在权限适配问题：页面同时读取财务发票，因该账号没有 `finance.read` 权限而加载失败。具体边界见[角色使用限制](docs/usage.md#角色使用限制)。

采购由 `mock-buyer` 制单后，切换到初始化时创建的 `admin` 账号审批。制单人不能审批自己的采购单，管理员也受此限制。

## 项目架构

**浏览器负责交互，Python 服务负责业务判断，SQLite 保存业务事实。** 所有后端模块运行在同一个进程中，默认由一个服务实例访问本地数据库。

![FlowERP 整体架构：浏览器经 HTTP 入口和客户 API 调用业务服务，再通过持久化模块读写 SQLite；HTTP 服务同时提供 web 静态资源。](docs/assets/flowerp-architecture.png)

图中箭头表示主要调用或读取方向，业务结果沿请求链返回。页面位于 [web/](web/)，[server.py](flowerp/server.py) 提供 HTTP 服务，[api.py](flowerp/api.py) 将 `/api/v1` 请求分发给业务模块，[store.py](flowerp/store.py) 管理数据库连接与事务。

| 业务模块 | 负责什么 | 主要代码 |
| --- | --- | --- |
| 主数据 | 商品、客户、供应商、仓库和库位 | [master_data.py](flowerp/master_data.py) |
| 采购 | 制单、审批、收货和入库 | [purchasing.py](flowerp/purchasing.py) |
| 库存 | 库存余额、流水、调拨和盘点 | [inventory.py](flowerp/inventory.py) |
| 销售 | 确认、预占、发货、取消和退货 | [sales.py](flowerp/sales.py) |
| 财务 | 应收应付、收付款、成本和会计分录 | [finance.py](flowerp/finance.py)、[accounting.py](flowerp/accounting.py) |
| 渠道订单 | 接收外部订单、商品映射、审单和回传任务 | [channels.py](flowerp/channels.py) |
| 对账与报表 | 业务核对、银行对账和经营报表 | [reconciliation.py](flowerp/reconciliation.py)、[cash_management.py](flowerp/cash_management.py)、[reports.py](flowerp/reports.py) |

模块共用数据库，由业务服务组织事务。例如，销售预占同时更新库存和订单；任一行缺货时整次预占回滚。可用库存不能为负，重复入库不能重复增加库存，取消订单按状态释放预占，采购须由其他有审批权限的用户批准。

数据表、模块依赖和旧版 `ERPService` 的兼容边界见[架构与数据设计](docs/architecture.md)。渠道模块提供订单处理与回传任务管理，真实平台适配和联调仍需单独完成。

## 开发与检查

读一项功能时，沿 **`web/app.js` 的请求 → `flowerp/api.py` 的路由 → 对应业务服务 → 表结构与测试** 查找。修改业务规则须包含正常和失败路径测试。

Python 运行时没有第三方依赖，前端无需 npm 构建；以下页面逻辑测试需要 Node.js。另开终端，进入仓库根目录执行对应命令。

### Windows / PowerShell

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 -m eval.harness --suite blocking
node --test tests/flowerp_boot.test.cjs tests/flowerp_inventory_filter.test.cjs tests/flowerp_purchase_recovery.test.cjs
```

### macOS / zsh

```zsh
./.venv/bin/python -X utf8 -m unittest discover -s tests -v
./.venv/bin/python -X utf8 -m eval.harness --suite blocking
node --test tests/flowerp_boot.test.cjs tests/flowerp_inventory_filter.test.cjs tests/flowerp_purchase_recovery.test.cjs
```

Python 测试检查业务与 API，blocking Eval 检查必须阻断的业务场景，Node 测试检查页面逻辑。Eval 报告默认写入 `.runtime/reports/harness-blocking.json`。自动检查通过后，仍须人工完成业务验收。

## 进一步操作

| 要做的事 | 查阅位置 |
| --- | --- |
| 创建演示库、管理账号、处理启动问题 | [使用与维护](docs/usage.md) |
| 查看数据表、事务、兼容代码和目录职责 | [架构与数据设计](docs/architecture.md) |
| 配置鉴权、备份、健康检查或容器部署 | [配置与运行维护](docs/usage.md#配置与运行维护) |
| 通过 CodexFDE 工作台组织研发 | [工作台接入](docs/usage.md#工作台接入) |

FlowERP 可独立运行。本仓库维护 ERP 业务、页面和检查；个人研发工作台与课程材料在 CodexFDE 仓库维护，两者使用各自的数据库。运行数据、凭据、日志与检查报告不入库。
