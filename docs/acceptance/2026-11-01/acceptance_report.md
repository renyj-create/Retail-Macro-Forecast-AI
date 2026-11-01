# AI Retail Analyst 最终专项验收报告（2026-11-01）

## 结论

知识图谱真实HTTP与CDP浏览器核心功能通过，多模态上传/校验与not_configured状态通过；真实视觉识别未接入、未验收。仍有明确未验证项，见末尾，不将整份需求无条件标为全部完成。

当前安全后端由用户报告PID15948、认证和Driver连接成功；随后独立真实HTTP实体目录和多跳均返回200，证明当前服务实际可读Neo4j。不重启后端、Neo4j、Vue，不导入或修改图谱数据，无Git提交。

## 失败根因与运行环境

- 先前手动uvicorn启动未携带安全启动器的进程环境，图谱返回503/not_configured。密码只存在于启动器进程内；另一个终端的uvicorn不会继承已退出启动器的变量。not_configured在构建Driver之前返回，不是二跳Cypher执行失败。
- 更早代码的两个问题：事务tx.run传入Query对象（驱动源码明确拒绝），已改unit_of_work(timeout=5)；属性Map相加改为关系Map投影r {.*, source:...,target:...,relation:...}。本轮真实实例已执行修复后的查询成功。
- 原启动器在CONNECTIVITY_VERIFIED后会执行进程识别/停止，再导入应用/绑定端口；任一异常原来都只有START_FAILED类型。没有此前完整阶段日志，不能断言历史那次失败具体发生在哪一行。
- 本轮启动器增加stage及安全reason，改为端口占用时退出且不停止任何进程；已对实际占用8003验证安全拒绝。启动器先验证连接，设置四项环境，然后同进程uvicorn.run(app,reload=False)，没有额外worker传递问题。失败输出不含密码或原始异常文本。
- GraphService按请求创建Driver；READ session在上下文退出关闭，生成器finally关闭Driver。事务timeout=5，连接/连接池等待5秒，重试时间0。未验证真实长查询超时触发；代码配置已核对。

## 真实HTTP / Neo4j结果

live_http_evidence.json保存每次请求和完整JSON，live_http_summary.json为6项集成测试全通过、0跳过、退出0。它们通过真实8003到Neo4j，没有依赖覆盖、Mock或图谱写操作。

| 查询 | 唯一节点 | 唯一关系 | 最大跳数 | HTTP |
|---|---:|---:|---:|---:|
| 实体目录 | 6 | 0 | 不适用 | 200 |
| P001一跳 | 5 | 4 | 1 | 200 |
| T001一跳 | 4 | 3 | 1 | 200 |
| T001二跳 | 6 | 7 | 2 | 200 |
| T001三跳 | 6 | 7 | 3 | 200 |
| P001三跳 | 6 | 7 | 3 | 200 |
| T001到C001路径 | 5 | 6 | 3 | 200 |

T001一跳关联P001、P002、M001。二跳/三跳节点集为T001/P001/P002/C001/S001/M001，关系R001至R007。

路径接口返回最多3跳的全部简单路径（受2000候选及节点/关系上限约束），不是仅最短路径：
1. T001 —STOCKS→ P001 —BELONGS_TO→ C001（2跳）
2. T001 —STOCKS→ P002 —BELONGS_TO→ C001（2跳）
3. T001 ←APPLIES_TO— M001 —FEATURES→ P001 —BELONGS_TO→ C001（3跳）

断言唯一节点/关系计数、路径无重复节点/重复路径、真实R003=S001→P001、R007=M001→T001、dataset_id=retail_demo_v1及is_simulated=true均通过。未知起点/终点返回200并相应found=false；非法模式/深度0和4/白名单/Cypher额外参数/上限101均422；max_nodes=1或max_relationships=1真实结果遵守限制且truncated=true。

固定Cypher见multihop_templates.cypher。服务端仅为1/2/3固定模板，参数传递id、target、dataset、过滤白名单和limit；所有路径节点/关系检查来源和模拟标记，single去环，方向从startNode/endNode获取。没有用户任意Cypher入口。

## CDP真实浏览器

无Playwright/Puppeteer依赖；复用项目原生CDP方式，使用已安装Chrome独立headless profile，仅本机9223，明确Page.navigate到127.0.0.1:5173，没有调用Computer Use或安装依赖。该次无头真实浏览器不等于原有用户Chrome窗口的人工验收。

- 实体真实加载、T001一/二/三跳选择和真实POST、路径选择与高亮通过；final-browser/graph-*.png及browser_network.json包含请求和响应，关系表与图中方向一致。
- 节点真实鼠标点击：C001属性显示名称、ID、类型、dataset、is_simulated；interactions/checks.json保存文本。
- 执行节点拖动并保存前后截图；滚轮缩放值1→1.1；适应画布/重置/800px窗口截图已保存。拖动仅以鼠标事件和截图验证，未量化布局坐标差。
- PNG/JPEG实际本地文件选择与解码预览、移除、相同文件再次选择、上传后200/not_configured通过；错误格式及>5MiB前端拒绝，损坏PNG上传422、>1600万像素上传413；最后合法上传恢复。
- recovery中真实浏览器断网导致ERR_INTERNET_DISCONNECTED，图片及图谱均展示错误，联网重新上传/查询恢复。没有伪造HTTP503。503分支的独立浏览器故障注入未做。
- 首页、数据分析宏观预测、流失预警真实请求/表格、AI Agent表单、多模态、报告列表及现有报告查看、知识库页面已打开并截图。未新提交文本Agent分析任务，也未验收其全部业务链路或新报告生成。
- final-browser/browser_console.json与interactions/browser_console.json均[]；recovery仅有2条预期断网Network错误，无JS异常。首次恢复过程中失败和ECharts异常证据保留，不计最终通过。

## 本轮必要修复与Diff

1. scripts/start_backend_secure.py：失败阶段、仅安全错误码、取消进程终止，8003占用时拒绝；原始本机Diff保留在artifacts；通用启动器见scripts/start_backend_secure.py。
2. retail-frontend/src/components/KnowledgeGraph.vue：空节点结果直接chart.clear，避免创建空force系列导致ECharts坐标异常；原始本机Diff保留在artifacts。最终正常流程和断网恢复均无该异常。
3. docs/knowledge_graph_mvp.md：更新当前接口、结果和验收边界；与本报告链接。

src/knowledge_graph/service.py、src/api/knowledge_graph.py、src/tests/test_graph_multihop.py本轮未再次修改，沿用前轮最小修复；前轮Diff在artifacts/graph_multimodal_acceptance_20261101，事务超时修复在graph_final_acceptance_20261101留有副本。

## 测试/构建

| 检查 | 总数 | 通过 | 失败/错误 | 跳过 | 退出码 |
|---|---:|---:|---:|---:|---:|
| 完整后端回归 | 145 | 144 | 0 | 1 | 0 |
| 真实HTTP集成测试 | 6 | 6 | 0 | 0 | 0 |
| 启动器占用端口安全检查 | 1 | 1 | 0 | 0 | 0 |
| 前端npm run build | 不适用 | 通过 | 0 | 0 | 0 |

完整回归中的1个跳过是需要测试进程单独提供认证环境的直接Driver测试；本轮不复制运行后端的密码，真实数据库集成由独立HTTP测试验证。不能把该跳过项记为通过。前端保留大包体积警告。相关图谱和多模态测试包含在完整145项中。

## 图片与日志边界

产品代码使用内存bytes/BytesIO，multipart UploadFile可能由Starlette临时spool，finally关闭文件；应用没有将上传图片持久写入业务文件或数据库的代码。浏览器使用blob URL并在移除/卸载回收。本目录fixtures为验收人为生成并保存的素材，与服务自动持久化不同。

当前视觉client未配置，响应没有识别字段；未调用模型或Base64发送。源码检查没有打印Base64/图片内容。原启动器的普通终端服务日志未重定向，本轮没有从运行进程抽取日志/密码，也未为收集日志重启；因此没有完整后端原始日志归档，不能断言所有第三方日志绝无内容泄露。错误分类日志代码只记录diagnostic_id、异常类型、Neo4j代码及函数行号，不记录异常原文/参数/locals。

## 尚未验证 / 限制

- 真实视觉识别（明确未接入）；多模态真实HTTP503分支、真实查询超时、数据库账户只读权限、含外部数据集的污染隔离实验、完整原始后端终端日志。
- 全部文本Agent业务任务及新报告生成；本轮仅验收其页面和既有报告查看。
- 当前路径起点=终点没有专门零跳路径策略；候选2000以上的截断选择不保证全局最短路径优先。当前6/7数据无截断。
- 启动器历史START_FAILED具体堆栈没有证据，不推断已确认根因。

## 演示与复现

保持现有Neo4j与前端。未来若需安全启动：先由用户在原终端停止自己的旧后端，普通PowerShell运行已有start_backend_secure.py，密码只隐藏输入。端口占用会安全退出，不自动杀进程。无需导入数据或改认证。

本目录为只读归档。完整复现环境与命令见 [运行说明](../../runtime_setup.md)；本机原始CDP脚本与诊断历史仍保留在被忽略的artifacts目录，未打包浏览器profile。不得将历史结果当作新环境已运行的结果。


## 归档整理说明

本报告由最终验收报告复制后调整路径，未重新执行验收。原始日志、截图均保持原字节；manifest.json记录来源相对路径和SHA256。运行时目录、Cookie、数据库及大尺寸生成素材不在本归档中。
