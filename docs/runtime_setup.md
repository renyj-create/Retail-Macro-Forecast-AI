# 本机运行与新克隆准备

以下命令从项目根目录运行。准备步骤与已有环境演示分开；不要对现有数据库重新导入数据。本文不包含认证值或本机绝对路径。

## Python与前端

使用Python 3.10及独立环境，首次安装：

```powershell
python -m pip install -r requirements.txt
# 使用知识图谱时额外安装
python -m pip install -r requirements-graph.txt
# 开发测试环境也可一次安装（包含上述两份）
python -m pip install -r requirements-dev.txt
```

前端使用支持Vite 8的Node.js（20.19+或22.12+，并满足包管理器的engines检查）：

```powershell
cd retail-frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

已有前端服务时不再执行启动命令。构建只执行 `npm run build`。

## 新克隆的基础业务数据

仅在没有本地数据的新环境中执行：

```powershell
python src/data_pipeline/fetch_macro.py
python src/data_pipeline/generate_mock_data.py
python src/models/train_lgbm_churn.py
```

第一步需要外部数据源。失败时不能把空数据或模拟数值当作真实宏观数据。数据与模型生成完成后，按README启动基础后端。RAG原文来自 `docs/policy.txt`，Chroma缓存按现有逻辑生成，不提交本机向量库。

## Neo4j前置条件

Neo4j服务独立于Python安装。当前实测服务器版本2026.02.2、数据库neo4j；本地演示Bolt端口17687、HTTP端口17474，仅绑定127.0.0.1。仓库不打包Neo4j数据库、认证库或本机配置。

已有环境：保持现有服务、配置、认证和6节点7关系数据，不初始化、不改密码、不导入。若服务未运行，由操作者提供现有 `NEO4J_HOME` / `NEO4J_CONF` 路径后，在普通PowerShell中运行：

```powershell
& "$env:NEO4J_HOME/bin/neo4j.ps1" console
```

上述变量必须已在当前终端设置为实际安装目录和现有独立配置目录；不提供或创建新的认证配置。

全新环境：管理员应先自行安装并配置本机Neo4j、创建数据库和认证，确认数据集用途。仓库提供 `scripts/import_retail_graph_demo.py` 和模拟JSON仅供管理员显式初始化新演示库；该脚本会写约束与数据，不属于普通启动步骤，不应在已有实例上重新执行。需要的专用进程变量为 `NEO4J_URI`、`NEO4J_DATABASE`、`NEO4J_IMPORT_USER`、`NEO4J_IMPORT_PASSWORD`；密码只在本机安全输入，不放命令行、聊天、仓库或转录。本文不自动执行导入。

## 安全启动已有图谱后端

在普通交互终端运行，不能重定向输入输出或开启密码转录：

```powershell
python scripts/start_backend_secure.py
```

默认Bolt `bolt://127.0.0.1:17687`，用户和数据库为neo4j。可在启动前设置非密钥进程变量 `NEO4J_URI`、`NEO4J_USER`、`NEO4J_DATABASE`；空值使用默认值。启动器不加载.env中的Neo4j密码，始终getpass隐藏输入；不会写入密码配置。

启动器先验证Driver连接并关闭验证Driver，再确认8003未占用，同进程设置四项Neo4j环境并以 `reload=False` 启动应用。只打印配置是否存在和安全阶段代码，不打印值或原始异常。8003占用会退出，不杀进程；如需替换，由用户在原终端停止自己的旧后端。绝不再并行启动普通Uvicorn。

此启动器默认关闭视觉调用、LangSmith追踪及文本模型调用，便于无模型费用的图谱演示。若需要文本模型，使用单独评估过的运行方案；不要误认为此启动器会保留.env中的文本Key调用能力。

`CONNECTIVITY_VERIFIED`只证明认证连接通过；之后仍可能在端口检查、导入应用或服务绑定阶段失败。按START_FAILED的stage/type/reason诊断，不需要发送密码。每次查询Driver与session由业务依赖关闭，事务超时5秒；READ模式不替代数据库账户授权。

基础功能后端可单独使用：

```powershell
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8003 --reload
```

该命令不会继承另一已退出启动器的环境。图谱未配置时503/not_configured符合契约。

## 配置模板与多模态

`.env.example`仅含空值、公共地址和开关；真实.env留在本机。当前Agent导入会加载.env，图谱读取进程环境；安全启动器会显式设置图谱变量，避免依赖偶然继承。

多模态默认关闭，合法PNG/JPEG上传返回200/not_configured，没有识别字段。输入限制5MiB、1600万像素；无自动持久化业务图片。真实视觉服务需要显式授权后才设置VISION_ENABLED、VISION_API_KEY、VISION_BASE_URL（HTTPS）、VISION_MODEL，不在本轮准备或验收中开启。

## 测试和证据

普通测试命令：

```powershell
python -m unittest discover -s src/tests -v
```

独立Driver集成测试仅在同进程已有安全认证变量且明确设置ENABLE_GRAPH_INTEGRATION=true时启用；默认跳过，不冒充通过。测试账户只读权限需另外核验，不复用导入权限来声称只读已验证。

当前归档回归采用允许loopback、拒绝外部socket的隔离运行器；普通命令本身不保证全局无外部网络，因此不要在开启模型/追踪的环境中把它当作隔离验证。没有提供自动配置认证或重跑历史证据的命令。

真实HTTP只读验证可从 `http://127.0.0.1:8003/api/v1/graph/entities` 开始，POST `/api/v1/graph/query` 如下：

```json
{"query_type":"two_hop","entity_id":"T001","limit":100}
```

页面进入知识图谱选择模拟门店一，依次查询1/2/3跳，路径选择T001到C001；图谱数值以真实响应为准。多模态进入AI Agent选择PNG/JPEG，查看预览、移除和未配置状态。

[精选验收归档](acceptance/2026-11-01/README.md)包含144通过/1跳过、真实HTTP、浏览器及构建记录。原始artifacts仍留在本机。CDP使用已有Chrome独立本机调试profile的历史运行，未引入Playwright依赖；归档不包含profile或Cookies。新环境必须独立运行验证，不能把归档结果视为本机已通过。
