# 多模态MVP当前状态

上传与not_configured浏览器验收已通过，真实视觉识别尚未接入。详见[精选验收](../acceptance/2026-11-01/README.md)和[运行说明](../runtime_setup.md)。以下为第二阶段历史记录，其中测试数量和“未进行浏览器验收”描述仅对应历史阶段；原始证据留在本机，不要求整体提交。

# 独立多模态 MVP（第二阶段）

## 已实现与边界

新增独立上传分析链路，不改现有 LangGraph 路由、不接 Neo4j、不修改历史报告表。视觉适配器支持显式配置的 OpenAI 兼容图片接口，但没有选定或验证任何真实视觉模型。所有本轮模型测试均为离线模拟，无真实模型调用或模型费用验证。

默认不启用视觉调用。未配置时前端显示“未配置”，后端返回 not_configured，绝不产生识别字段。Mock 只能通过 Python 测试依赖注入使用；没有公开 mock 参数或启用模拟识别的环境开关。模拟结果状态为 mock、is_mock=true、data_nature=simulated。测试中的 FakeReal 和 SDK mock 仅验证非 Mock 分支协议，不代表真实服务成功。

报告始终使用确定性模板，report_status=template，不调用现有报告模型；失败/未配置时 report_status=unavailable。成功识别也仅代表结构和校验流程完成，不证明截图真实或识别准确。校验问题时 status=needs_review。没有借图片生成数据库事实、预测或经营推断。

## API 契约

POST /api/v1/multimodal/analyze，multipart/form-data：file 为单张图片，question 为1–2000字符的非空问题。

响应包含 task_id、status、error_code、message、document_type、provider、is_mock、fields、issues、evidence、report、report_status。

fields 含 name、raw_text、unit、normalized_value、normalized_unit、validation_status。为避免浮点精度损失，规范化数值以十进制字符串返回，缺失或非法值为 null，不填0。支持经营报表的 date、revenue、profit、margin_pct、transactions；date/revenue 必填。未知字段、重复字段和未知文档类型标为待核实，不自动猜测。

- 日期要求有效 YYYY-MM-DD。
- 金额要求独立单位元/万元/亿元，转为元；不假定美元等币种等价。
- 百分比要求单位%，范围[-100,100]；不会将0.2自动猜成20%。
- 交易量要求非负整数，单位笔。
- 当前数字文本支持普通十进制（不含千分位、货币符号或内联单位）；不支持的格式标为问题，不静默删字符或猜值。
- NaN/Inf、非法日期、缺失及非法单位均不得通过字段校验。模型输出必须为严格 JSON，额外置信度等未定义字段不接受，不能冒充准确率。

输入错误使用HTTP 413/415/422及稳定错误代码；模型未配置、模型超时、服务失败和非法输出为HTTP 200的显式领域状态，客户端必须检查 status，不能仅看HTTP 200。内部异常路径和上游错误正文不会作为新接口错误消息返回。

证据 source_type=image_extraction；data_nature 为 user_uploaded_unverified 或 simulated。source_sha256 是清除元数据并重新编码后的图片哈希，用于关联该次识别输入，不是原始文件身份或真实性证明。证据与报告不自动持久化。

## 图片安全

支持PNG/JPEG，校验实际格式与扩展名一致性，5MiB文件、1600万像素上限；拒绝损坏图片、动画及格式伪装。verify后重新打开并完整解码，处理方向、清除元数据、统一RGB PNG输出，清洗后仍不得超5MiB。透明区域统一合成白底（有专门测试）；转码可能改变图片编码与色彩表现，不用于原始文件取证。

ASGI中间件在multipart解析前逐块计数：总请求体上限5MiB+64KiB（包括表单边界和问题等开销），超限时立即拒绝，不继续读取剩余体；即使没有Content-Length也生效。接口对文件另作64KiB分块累计限制。请求体在上限内存缓冲，不落原始文件；FastAPI multipart解析可能使用临时spool，由请求生命周期清理，接口finally关闭上传对象。不建立上传目录或保存原图。

图片内容只作不可信识别数据，不可触发工具、SQL或Cypher。当前是单张截图、同步请求MVP，尚无任务队列、用户级访问控制或全局并发预算。生产部署仍需反向代理限制、请求限流、解码资源隔离、敏感截图授权与隐私策略；本轮未声称完成恶意文件全面防御或视觉提示注入可靠性验证。

## 配置和运行

本轮在 retail_env Python3.10 中安装并验证 Pillow12.3.0、python-multipart0.0.32；复用现有OpenAI3.28.0、FastAPI0.143.0、Pydantic2.14.0。requirements.txt只新增这两个必需包约束，未安装Neo4j或额外服务。

从项目根目录：

```powershell
& python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8003
```

另一个终端：

```powershell
cd retail-frontend
npm run dev
```

打开Vite显示的本机地址，进入“智能问数 Agent”，使用新增“经营报表截图分析”卡片选择PNG/JPEG、预览、填写问题并提交。默认展示未配置状态，现有文本分析入口保持原协议。移除图片会撤销本机预览URL；报告以文本展示，不执行识别结果中的HTML。

真实识别需要在后端进程环境中配置 VISION_ENABLED=true、VISION_API_KEY、VISION_BASE_URL（HTTPS）及 VISION_MODEL。独立于 DEEPSEEK_*，不能假定文本模型支持图像。具体服务授权、模型能力、费用和数据处理政策尚未验证。未获确认前不要启用真实调用；密钥只从环境读取，不写源码、不打印、不经前端传入。模型适配器关闭自动重试、设置30秒超时及输出Token上限，但这不等于账户级费用控制。

Mock演示使用下面的测试；不要把测试输出展示为真实模型识别。

```powershell
& python -m unittest src.tests.test_multimodal -v
& python -m unittest discover -s src/tests -v
cd retail-frontend
npm run build
```

普通完整回归会使用现有配置；本轮实际回归额外用socket guard阻断外部网络并允许Windows事件循环必需的loopback。没有读取或输出现有密钥，未改变认证设置。

## 实测结果

- 新增26个测试：全部通过，5.282s，new_tests_complete.txt；覆盖PNG/JPEG、格式不符、损坏、文件/像素上限、元数据清除、日期/数值/单位、缺失字段、模型未配置/超时/服务异常/非法输出、Mock标识、SDK请求构造、chunked请求提前拒绝及主应用兼容。
- 最终全套132项（原106+新增26）：全部通过，22.039s，regression_complete.txt；运行时阻断外网。
- 前端 npm run build：通过，17.51s，frontend_build.txt；有chunk超过500kB警告，未做无关拆包。
- 首次新增测试失败源于当前FastAPI的_IncludedRouter无path属性，已改为检查OpenAPI路径，保留new_tests.txt。首次回归guard禁止所有socket连接，误伤Windows事件循环，21 errors；改为允许loopback后通过，保留regression.txt及后续日志。
- 未进行浏览器人工交互验收、真实视觉服务验证或真实识别准确率评估，未声称这些项目通过。

## 文件与改动保护

新增：src/multimodal/{__init__,schemas,image_validation,vision_client,service}.py、src/api/multimodal.py、src/tests/test_multimodal.py、retail-frontend/src/components/MultimodalAnalysis.vue。

增量修改：src/api/main.py 只注册路由/中间件；App.vue 只导入/插入独立卡片；requirements.txt新增两项。原文件备份、原Git diff和状态保留在本目录。preservation.json确认移除本次接入语句后，main.py/App.vue与原备份文本完全一致；没有覆盖原有修改。未提交Git，未重置、清理用户文件或修改coding_agent_eval历史记录。
