# 知识图谱 MVP 当前验收状态（2026-11-01）

真实Neo4j→FastAPI→CDP Chrome主链路已通过：P001一跳5节点/4关系；T001一跳4/3，二跳6/7，三跳6/7；T001到C001返回两条2跳路径及一条3跳简单路径。保留真实关系方向、唯一计数、来源和模拟标记。多模态上传与not_configured状态通过，未接真实视觉识别。

完整后端回归144通过/1跳过，真实HTTP集成6通过，前端构建通过。浏览器主流程和节点交互Console无错误；断网恢复仅有预期网络错误。具体截图、Network JSON、Diff、复现方式和未验证项见[最终专项报告](acceptance/2026-11-01/acceptance_report.md)。以下为历史阶段记录，历史“未完成”描述不代表当前主链路状态。

## 当前查询接口

POST `/api/v1/graph/query`：`query_type`支持one_hop/two_hop/three_hop/path和原有基础类型；`entity_id`为起点，path需要`target_id`；`max_hops`为1～3（网络模式与类型一致），`limit`、`max_nodes`、`max_relationships`均1～100。可选`labels`、`relationship_types`仅接受枚举白名单；不接受Cypher/dataset覆盖等额外字段。

`data`包含nodes、edges（兼容）、relationships、paths、hop_count、source=neo4j、dataset_id、is_simulated、truncated。paths里的node_ids是遍历顺序，真实箭头必须按relationships.source/target显示。返回最多3跳简单路径，非仅最短路径。图谱未配置503/not_configured；查询错误按认证、连接、语句、超时分类并附diagnostic_id；非法参数422。

通用启动命令：`python scripts/start_backend_secure.py`，详见[运行说明](runtime_setup.md)。启动器认证成功后，在同一进程设置环境并启动Uvicorn，reload=False。不要单独手动启动无Neo4j环境的Uvicorn。启动器不杀进程，8003占用时需在原终端停止自己的旧后端后再试。

---

# 零售知识图谱 MVP（第三阶段）

## 状态

已实现独立Neo4j查询/导入代码、API与ECharts页面。真实集成验收未完成：本机发现Neo4j安装脚本（D:/Neo4j/...），检查未见7474/7687监听；retail_env没有neo4j驱动。端口检查在受限环境，不能单凭空结果断言系统绝无服务。没有安装软件/驱动、启动Neo4j、修改认证、调用模型或提交Git。

本阶段不接LangGraph；先完成独立查询工具，待真实集成通过后再评估Agent接入。不把宏观社零或模拟客户数据转换为商品明细，也不推断关联的因果收益。

## 数据与安全边界

独立data/graph_demo/retail_demo.json，6个节点、7条关系；Product/Category/Supplier/Store/Promotion均有稳定ID，所有节点和关系含dataset_id=retail_demo_v1、is_simulated=true。无销量、交易额、促销收益等虚构指标。数据仅是演示关系，独立存入指定Neo4j数据库/实例，不写retail.db。

节点标签RetailDemo加实体类型，复合唯一约束(dataset_id,id)。关系包括BELONGS_TO、SUPPLIES、STOCKS、FEATURES、APPLIES_TO，ID稳定。导入脚本先校验白名单与来源，再在写事务中MERGE节点/关系；重复串行导入应保持6/7数量，真实执行尚未验证。不删除旧数据；不保证并发导入或已被外部修改数据的重复关系自动清理。

读取接口只接受query_type枚举、受限格式entity_id、1–100的整数limit，不接受cypher或其他额外字段。Cypher为服务端固定模板；id、dataset、limit参数化；各关系限定同一数据集及模拟标记。按limit+1获取并标truncated，一跳最多100条关系及对应节点。未知实体返回empty和entity_found=false；实体存在但查询类型不匹配返回type_mismatch，无关系时返回根节点与空边。

session默认READ并使用execute_read，API没有写入端点。READ模式不是数据库授权替代品：运行时NEO4J_USER必须是由管理员配置的只读账户。实际只读权限目前未验证，不声称READ模式能阻止有写权限账号执行所有写操作。导入单独使用NEO4J_IMPORT_USER/PASSWORD，不复用读账户。Neo4j版本/版本授权对细粒度权限支持需按实际部署确认；本轮不更改权限。

## API与页面

- GET /api/v1/graph/entities?limit=30：真实数据库实体目录，用于选择器。
- POST /api/v1/graph/query：query_type为product_category、product_suppliers、store_products、promotion_details、one_hop；entity_id如P001，limit默认30。
- 响应source_type=graph_query、data_nature=simulated、is_simulated=true、dataset_id与nodes/edges。无配置503/not_configured；缺驱动503/driver_missing；连接/查询失败503/graph_query_failed或connection_failed，不暴露上游异常详情；非法请求422。

App仅新增“知识图谱”导航和独立KnowledgeGraph.vue。页面初始从entities接口加载节点，选择实体后查询后端关系；没有硬编码节点边或静态成功图。不同类型五种颜色、节点点击属性、来源/模拟标识、截断/空结果/错误状态。失败清空旧图；组件卸载断开观察器并dispose实例。ECharts tooltip关闭，实体属性按文本展示，不把数据库文本作为HTML执行。

## 后续真实运行步骤（本轮未执行）

1. 先确认本机Neo4j服务启动许可、隔离数据库与认证；不要覆盖现有库或假设默认密码。
2. 获准后在retail_env安装requirements-graph.txt的可选驱动。该范围尚未在本机安装验证，不影响未启用图谱时启动原API。
3. 在进程环境配置NEO4J_URI、NEO4J_DATABASE，以及只读的NEO4J_USER/NEO4J_PASSWORD；密钥不写源码、不输出。配置不是授权配置，需另核验权限。
4. 在独立导入终端提供NEO4J_IMPORT_USER/NEO4J_IMPORT_PASSWORD，运行python scripts/import_retail_graph_demo.py两次；不自动加载.env，也不在API启动时导入。检查实体6条、关系7条和ID无重复。
5. 启动现有FastAPI8003、前端Vite，进入知识图谱；加载目录、选P001查询品类/供应商或一跳，T001查询门店商品、M001查询促销关联。图中关系只说明模拟关联。
6. 明确允许集成测试写入该演示数据集后，设置ENABLE_GRAPH_INTEGRATION=true，执行python -m unittest src.tests.test_knowledge_graph -v。该测试使用导入账户写入并查询，不替代只读账户授权测试；还需验证读账户不能写入。

## 本轮验证证据

artifacts/graph_mvp/new_verified.txt：Ran7，6通过、1真实Neo4j集成跳过，0失败/错误（0.074秒）。不是7项真实集成通过。

artifacts/graph_mvp/regression.txt：Ran139，138通过、1同上跳过，0失败/错误（11.507秒）；包含原多模态及现有工作流/API等回归。驱动外网由socket guard阻断，未调用模型。test_exit.txt=0。首次受限测试未完成的new_tests.txt保留，不计通过。

前端npm run build退出0（981ms），保留>500kB chunk警告，见build.txt/build_exit.txt。git diff --check通过。

离线覆盖：数据模拟来源、稳定ID、非法查询与注入字符、限制、参数化与READ session、未知实体、截断、固定MERGE模板、API未配置/空/异常响应。Mock只用测试，未进入产品图谱返回；MERGE调用检查不等于已验证Neo4j幂等。

未验证：真实Neo4j连接、模板语法执行、权限、二次导入计数、真实前端加载节点边与点击属性。本轮未进行真实浏览器回归；多模态/流失图表/旧页面仅通过后端回归及原前端代码保留检查，不能写成浏览器验收通过。

## 文件与保护

新增src/knowledge_graph/{__init__,service}.py、src/api/knowledge_graph.py、scripts/import_retail_graph_demo.py、data/graph_demo/retail_demo.json、requirements-graph.txt、KnowledgeGraph.vue、test_knowledge_graph.py及本文档。

增量修改仅main.py的图谱路由注册、App.vue的组件/导航接入；移除这几处接入后与开发前副本逐文本一致。preservation.json与git_before/after记录保护结果；多模态组件、流失图修复、模型和历史验收证据没有覆盖。

下一步优先取得运行本机Neo4j和安装驱动的明确许可，再做真实集成与浏览器验收。在此之前，本阶段是已实现待集成验证的MVP，不是已完成真实图谱演示。


## 2026-11-01 最终验收尝试：服务恢复阻塞

本轮确认现有 FastAPI 8003、Vue 5173 正在运行，未重复启动。Neo4j 使用既有独立配置恢复失败：loopback / UnixDomainSockets.connect0 / Invalid argument: connect，随后自行停止。图谱真实 HTTP 实体接口返回503/not_configured。按要求停在恢复阶段，尚未进行多跳真实集成、浏览器交互及本轮回归，不宣称 MVP 完成。

详细证据、未验收项及安全启动步骤见 本机历史路径 `artifacts/graph_final_acceptance_20261101/acceptance_report.md`。未修改认证，未重新导入或修改图谱数据，未提交 Git。


## 知识图谱/多模态专项检查（2026-11-01）

新增安全错误分类诊断与Map投影最小修复，尚待安全启动器重启后真实查询验证，不宣称多跳验收完成。相关测试38通过/1跳过，完整回归142通过/1跳过，前端构建通过。多模态7项真实HTTP上传验证通过，不等于浏览器或视觉识别通过。详见 本机历史路径 `artifacts/graph_multimodal_acceptance_20261101/acceptance_report.md`。
