# FlowERP 使用与维护

[返回 README](../README.md)

首次启动和管理员登录见 README。这里按任务查阅：[演示数据与账号](#演示数据与账号)、[账号维护](#账号维护)、[启动排错](#启动排错)、[配置与运行维护](#配置与运行维护)、[工作台接入](#工作台接入)。

## 演示数据与账号

下表中的 `mock-*` 账号由 [mock_data.py](../flowerp/mock_data.py) 的 `mock-data` 命令创建，普通启动不会自动创建。**这些演示账号的初始密码均为 `Mock-Only-2026!`，组织代码均为 `DEFAULT`，仅用于演示数据。** 已存在的同名账号不会被重新设置密码。

| 角色 | 主要权限 | 对应账号 |
| --- | --- | --- |
| `admin` 管理员 | 全部权限，包括用户管理和采购审批；仍不能审批自己创建的采购单 | 初始化时创建，默认填写 `admin`；密码自行设置 |
| `sales` 销售 | 查看主数据与库存，创建、确认、预占和取消销售单，查看报表 | `mock-sales` |
| `purchasing` 采购 | 查看主数据与库存，创建、修改和提交采购单，查看报表；不含审批权限 | `mock-buyer` |
| `warehouse` 仓库 | 查看库存，入库、发货、调拨和采购收货，查看相关单据与报表 | `mock-warehouse` |
| `finance` 财务 | 财务读写、会计期间管理，查看销售、采购和报表 | `mock-finance` |
| `auditor` 审计 | 查看业务数据与审计日志，执行对账检查并生成检查记录 | `mock-auditor` |

需要试用这些账号时，可在独立的 `.runtime/demo` 目录建立演示库。**首次按“创建管理员 → 生成样例数据 → 启用鉴权启动”的顺序执行**：若先生成样例用户，系统就会判定已初始化，无法再通过初始化入口创建管理员。以下命令会生成演示业务数据；先停止占用 `8000` 端口的原服务。`init` 会交互要求输入两次管理员密码，输入时终端不显示字符。

Windows / PowerShell（仓库根目录）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m flowerp init --runtime-dir .runtime/demo --organization FlowERP-Demo --username admin
.\.venv\Scripts\python.exe -X utf8 -m flowerp mock-data --runtime-dir .runtime/demo
$env:FLOWERP_AUTH_REQUIRED = "true"
.\.venv\Scripts\python.exe -X utf8 -m flowerp serve --port 8000 --runtime-dir .runtime/demo
```

macOS / zsh（仓库根目录）：

```zsh
./.venv/bin/python -X utf8 -m flowerp init --runtime-dir .runtime/demo --organization FlowERP-Demo --username admin
./.venv/bin/python -X utf8 -m flowerp mock-data --runtime-dir .runtime/demo
export FLOWERP_AUTH_REQUIRED=true
./.venv/bin/python -X utf8 -m flowerp serve --port 8000 --runtime-dir .runtime/demo
```

已初始化的演示库再次使用时，跳过 `init`，继续使用原管理员密码。验证采购审批时，由 `mock-buyer` 创建并提交采购单，再退出并使用 `admin` 登录审批；演示数据生成器内部的 `mock-approver` 是模拟操作者标识，不是可登录账号。角色权限定义见 [schema_v2.py](../flowerp/schema_v2.py) 的 `ROLE_PERMISSIONS`。

### 角色使用限制

角色权限、后端能力与页面可用性需要分别核对。2026-10-09 使用临时演示数据库和实际账号登录得到的角色身份，验证了销售制单、确认与预占，采购制单与提交，仓库收发货与调拨，财务开票、收款与核销，以及审计对账记录生成；这些是服务层操作验证，尚未完成各角色浏览器全流程验收。

- **销售页存在权限适配缺口。** `web/app.js` 的 `renderSales()` 同时请求销售单、退货单和财务发票。`mock-sales` 的前两个接口返回 `200`，发票接口返回 `403`（缺少 `finance.read`）；页面使用 `Promise.all`，因此加载失败。需要修正页面的跨角色数据依赖，不能把给销售账号增加全部财务读取权限当作默认处理。
- **采购与仓库有明确职责边界。** `mock-buyer` 可以制单、提交，但不能审批；`mock-warehouse` 可以收发货与调拨，没有 `inventory.adjust`，不能进行盘点调整。部分操作按钮尚未按角色隐藏，最终由服务端拒绝无权操作。
- **财务能力是业务记账。** 已验证开立业务发票、登记收付款和核销；记录一笔付款不等于已向银行发起转账。
- **审计角色并非完全只读。** 对账检查会写入 `reconciliations` 和审计记录；该角色还可更新部分预警处理状态，但没有销售、采购和财务业务写入权限。

## 账号维护

管理员在“系统与用户 → 新增用户”创建业务账号，在用户列表的“维护”中调整角色或停用账号。角色或停用状态变更后，被维护用户的其他活动会话会失效。

登录用户通过右上角用户菜单的“修改密码”输入原密码和新密码，新密码至少 10 位。当前没有忘记密码自助重置入口；已有用户的数据库不能再次初始化，`init` 也不能用于重置密码。

账号保存在服务所用运行目录的 `flowerp.db` 中。换成空目录会重新出现初始化页面；管理员密码由创建者设置，演示密码只适用于生成的 `mock-*` 账号。重新生成演示数据不会重置已存在的同名账号密码。

## 启动排错

以下端口示例使用常规运行目录 `.runtime`。如果处理的是演示库，保留原来的 `--runtime-dir .runtime/demo`；换端口时应继续使用同一业务目录。

- `python3: command not found` 或 Python 版本低于 3.10：安装 Python 3.10 或以上，重新打开终端，再检查版本。
- 找不到 `.venv` 中的 Python：确认已经在当前系统执行创建虚拟环境的命令，并使用对应系统的路径。
- `No module named flowerp`：确认当前目录是 FlowERP 仓库根目录，使用上面指定的虚拟环境 Python 重新执行 `-m pip install -e .`。
- `8000` 端口被占用：先检查是否已有 FlowERP 服务；若只是另一个应用占用了该端口，可使用下面的命令改为 `8080`，然后访问 [http://127.0.0.1:8080/](http://127.0.0.1:8080/)。

  Windows / PowerShell：

  ```powershell
  $env:FLOWERP_AUTH_REQUIRED = "true"
  .\.venv\Scripts\python.exe -X utf8 -m flowerp serve --port 8080 --runtime-dir .runtime
  ```

  macOS / zsh：

  ```zsh
  export FLOWERP_AUTH_REQUIRED=true
  ./.venv/bin/python -X utf8 -m flowerp serve --port 8080 --runtime-dir .runtime
  ```

- 同一运行目录已有活跃服务或写入租约未释放：在原终端按 `Ctrl+C` 并等待服务退出；异常退出后，等待约 30 秒再重试。切换端口不能让两个服务同时使用同一业务目录。

## 配置与运行维护

服务启动时通过 [config.py](../flowerp/config.py) 读取进程环境变量并校验；代码不会自动加载 `.env` 文件。运行目录通过 `serve --runtime-dir` 指定。

| 配置 | 默认行为与用途 |
| --- | --- |
| `FLOWERP_HOST` / `FLOWERP_PORT` | 默认 `127.0.0.1` / `8000`，控制监听地址与端口 |
| `FLOWERP_ENV` | 默认 `development`；`production` 启用生产配置校验 |
| `FLOWERP_AUTH_REQUIRED` | 开发环境默认 `false`，生产环境默认 `true`；生产模式禁止关闭鉴权 |
| `FLOWERP_ALLOWED_ORIGINS` | 允许的跨域来源，以逗号分隔；生产模式监听 `0.0.0.0` 或 `::` 时须配置 |
| `FLOWERP_DB_BUSY_TIMEOUT_MS` | 默认 `5000`，控制 SQLite 写入等待时间 |
| `FLOWERP_REQUIRE_RECENT_BACKUP` | 默认 `false`；启用后，就绪检查会要求近期有效备份 |

开发模式关闭鉴权时，无会话请求使用 `SYSTEM_PRINCIPAL`。需要验证实际用户权限和职责分离时，应启用鉴权并分别登录相应角色；页面显示一个用户不等于所有请求都经过该用户的权限控制。启用鉴权后，API 支持 Bearer 或会话 Cookie；使用 Cookie 的写请求还会验证 CSRF 令牌。

| 维护入口 | 用途 |
| --- | --- |
| `GET /api/v1/health/live` | 服务存活状态 |
| `GET /api/v1/health/ready` | 数据库、迁移、维护状态、磁盘及账务等就绪检查；未就绪返回 `503` |
| `GET /api/v1/metrics` | 文本格式的运行指标 |
| `init` | 初始化组织和管理员 |
| `backup` / `verify-backup` | 创建一致性数据库备份，检查摘要、数据库完整性及恢复结果 |
| `doctor` / `runtime-status` / `maintenance` | 查看就绪状态、运行租约，控制业务写入维护模式 |
| `demo` / `mock-data` / `verify-mock-data` | 演示与样例数据的生成或检查；写入前明确选择目标运行目录 |

管理命令通过同一 Python 入口执行。Windows 使用 `.\.venv\Scripts\python.exe -X utf8 -m flowerp --help`，macOS 使用 `./.venv/bin/python -X utf8 -m flowerp --help`；在具体子命令后追加 `--help` 查看参数。

当前分发方式是源码检出加可编辑安装，需要同时保留 `flowerp/` 和 `web/`。[deploy/Dockerfile](../deploy/Dockerfile) 也提供容器入口，构建阶段运行 Python 测试和 blocking Eval，运行阶段监听 `8000`。容器部署需持久化业务运行目录；本机数据库、凭据、日志、备份与检查报告不入库。

## 工作台接入

本仓库维护 ERP 业务模型、服务、客户 HTTP API、页面与业务检查。个人研发工作台、课程材料与研发交付治理由独立的 CodexFDE 仓库维护，FlowERP 可以单独启动和运行；工作台默认 `:8001`，本项目默认 `:8000`，两者使用各自的数据库和运行目录。

需要通过工作台组织开发时，登记本仓库的绝对路径，使用本仓库 `.venv` 中的 Python 执行 `-X utf8 -m eval.harness --suite blocking --report-path {report_path}`；候选修改在本仓库的隔离副本中执行。源码迁入记录见 [MIGRATION.json](../MIGRATION.json)。
