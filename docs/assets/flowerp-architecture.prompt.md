# FlowERP 架构图生成说明

- 用途：README「整体架构」中的主要调用关系示意图。
- 生成方式：内置 ImageGen；2026-10-09。
- 成品：`flowerp-architecture.png`。
- 内容依据：本仓库 `server.py`、`api.py`、业务服务、`store.py` 及 README 架构说明。
- 修改架构后须同步检查图中的模块、文件名、箭头和进程边界。

## 完整生成提示词

```text
Use case: infographic-diagram
Asset type: Chinese software architecture diagram for the README of the real FlowERP repository.
Primary request: Replace a Mermaid architecture diagram with a polished, clear ImageGen raster diagram. This is technical documentation, not a marketing poster.
Canvas: wide landscape, approximately 16:9, high resolution, opaque near-white background, dark navy readable Chinese sans-serif type, restrained blue and teal accents. Flat clean boxes, subtle rounded corners, fine borders, generous whitespace, no decorative artwork.
Title (exact): "FlowERP 整体架构"
Subtitle (exact): "一个 Python 服务进程 · 共享 SQLite 数据库"
Composition: a clearly readable left-to-right principal call chain. A browser card at left, a large pale-blue outlined container in the center with FOUR internal cards arranged left-to-right, and a database cylinder outside this container at right. A separate small static-files card above the HTTP card, OUTSIDE the process container. All text must be large enough to read when the image is used across a README page.

Exact nodes and content:
1. Outside left card: "浏览器", secondary line "页面展示与业务操作".
2. Central container label: "Python 服务进程".
3. Internal card 1: "HTTP 入口", code label "server.py", short caption "请求解析与响应".
4. Internal card 2: "客户 API", code label "api.py", short caption "路由、身份与请求保护".
5. Internal card 3: "业务服务", short lines "主数据 · 库存 · 销售" and "采购 · 财务 · 渠道".
6. Internal card 4: "持久化", code label "store.py", short caption "连接、提交与回滚".
7. Outside right database: "SQLite", exact filename label ".runtime/flowerp.db".
8. Separate static-files card above internal HTTP card: "静态资源", code label "web/", small line "HTML · CSS · JavaScript".

Exactly these SIX single-direction arrows, all with visible arrowheads and clean separated routing:
Browser -> HTTP entry, label "HTTP 请求".
HTTP entry -> customer API, label "/api/v1".
Customer API -> business services, label "业务调用".
Business services -> persistence, label "事务".
Persistence -> SQLite, label "SQL".
HTTP entry -> static-files card above, label "读取静态文件". This arrow points upward from HTTP to files; do NOT make files part of the browser-to-API chain.
The FOUR internal cards must be fully inside the ONE process container; browser, static files, and database must be outside it.
Footer exact: "箭头表示主要调用或读取方向，业务结果沿请求链返回。"

Accuracy constraints: preserve every filename and Chinese label exactly; no microservices, no cloud, no message broker, no extra database, no Workbench/CodexFDE, no AI component, no framework logos, no made-up modules or numbers. Do not draw separate deployment containers around each internal module. Do not add extra arrows. No duplicated labels, no overlapping text, no tiny typography, no watermark. Prioritize legibility and accurate relationships over ornament.
```
