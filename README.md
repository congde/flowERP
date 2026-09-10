# FlowERP

独立的电商 ERP 客户项目，包含主数据、库存、销售、采购、财务、渠道订单与客户界面。个人研发工作台和课程材料在 CodexFDE 仓库维护，工作台登记本仓库目录后组织调研、受控修改与验收。

首次启动（PowerShell，仓库根目录）：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\python.exe -X utf8 -m flowerp serve --port 8000 --runtime-dir .runtime
```

打开 `http://127.0.0.1:8000/`。首次运行使用空业务数据库；旧工作台、旧客户数据库和账号不会被复制。页面提供初始化入口。本地默认模式用于开发，正式部署须配置鉴权与环境参数。

```powershell
.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.venv\Scripts\python.exe -X utf8 -m eval.harness --suite blocking
node --test tests/flowerp_boot.test.cjs tests/flowerp_inventory_filter.test.cjs tests/flowerp_purchase_recovery.test.cjs
```

工作台项目目录应登记为此仓库的绝对路径；Eval 命令使用此仓库 `.venv` 的 Python，参数为 `-X utf8 -m eval.harness --suite blocking --report-path {report_path}`。候选执行目录必须为本仓库的隔离副本。

`MIGRATION.json` 记录迁入源码的来源与摘要。迁入时拆除了客户页面中的课程任务面板及对应工作台 API，保留 19 项 ERP 阻断检查。旧课程参考实现仍留在 CodexFDE，之后的独立产品开发以本仓库为准。当前分发方式为源码检出加可编辑安装。
