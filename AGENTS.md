# FlowERP 独立客户项目

本仓库只维护 ERP 业务模型、服务、客户 HTTP API、页面与业务检查。个人研发工作台、课程讲义与交付治理在 CodexFDE 仓库维护，不得复制到此仓库。

- `flowerp/`：业务服务、持久化与 HTTP API。启动入口为 `python -X utf8 -m flowerp serve`。
- `web/`：客户页面，业务事实来自 `/api/v1`。
- `tests/`、`eval/`：业务与接口检查，不能以测试通过代替人工业务验收。
- 使用本仓库 `.venv` 和可编辑安装，无第三方运行时依赖。运行数据库、密钥、日志与检查报告不入库。
- 可用库存不得为负，预占原子化；同一入库幂等键只生效一次；订单状态遵守状态机，取消释放预占；采购须人工审批后入库。
- 修改业务规则须包含正常和失败路径测试。保留幂等、鉴权、审计和人工职责分离。
- 检查命令：`python -X utf8 -m unittest discover -s tests -v`；`python -X utf8 -m eval.harness --suite blocking`；`node --test tests/flowerp_boot.test.cjs tests/flowerp_inventory_filter.test.cjs tests/flowerp_purchase_recovery.test.cjs`。
