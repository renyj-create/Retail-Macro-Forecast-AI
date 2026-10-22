# 离线评测框架说明（evaluation）

本文档说明本项目的 Agent 离线评测基础设施：目录结构、各模块职责、运行方式，以及如何在
**不调用真实大模型（DeepSeek）、不接入 LangSmith、不修改真实持久化数据**的前提下跑离线评测。

> 运行环境：conda `retail_env`（解释器 `D:\anaconda3\envs\retail_env\python.exe`，Python 3.10）。
> 本文档中的命令均在项目根目录执行，并统一加 `PYTHONPATH=.`（`src` 为无 `__init__.py` 的命名空间包）。

---

## 1. 目录结构与模块职责

```
evals/
  cases/                 # 离线评测案例（JSON，输入查询）
    macro.json           # 宏观分析案例
    churn.json           # 流失预测案例
    comprehensive.json   # 综合分析案例
  traces/                # 评测运行产物（已 gitignore，不提交）

src/evaluation/
  __init__.py            # TRACE_SCHEMA_VERSION = "1.0"
  callbacks.py           # NodeEventCollector：LangChain 回调，采集 LangGraph 的 node/graph/runnable/tool 事件
  privacy.py             # 脱敏 + 截断 + SHA-256 指纹（sanitize / redact_text / fingerprint / safe_summary）
  gates.py               # 四个确定性 gate + run_gates 汇总
  trajectory.py          # validate_trajectory：节点路径 / 工具序列 / 节点异常 / 工具状态校验
  runner.py              # OfflineBenchmarkRunner：串行执行 + 字段白名单 + trace 组装
  trace_writer.py        # write_trace：原子写 JSON trace（临时文件 + fsync + os.replace）
  cli.py                 # 离线评测 CLI 入口

src/tests/test_evaluation.py   # 评测基础设施测试（20 个，含端到端离线链路与 CLI 隔离测试）
```

各模块职责要点：

- **callbacks.py** — `NodeEventCollector(BaseCallbackHandler)` 在 LangGraph 运行时采集事件，按
  `node / graph / runnable / tool / wrapper` 分类，记录起止时间、耗时、输入输出摘要、错误类型；
  内部加锁，采集异常只记入 `errors` 不打断业务。
- **privacy.py** — 递归白名单式脱敏：邮箱、手机号、`user_id`、含 `api_key/token/secret/password`
  的字段、`image`/`base64` 字段、`query` 字段都会被替换为占位符；文本超长截断（`MAX_TEXT=3000`、
  `MAX_SUMMARY=1200`）、列表/字典超项截断（`MAX_ITEMS=40`）、递归深度上限 8；`fingerprint` 用
  SHA-256 计算 query 指纹，不落原文。
- **gates.py** — 四个确定性规则 gate（详见第 4 节）。
- **trajectory.py** — 对照三条意图规则路径校验实际节点与工具序列（详见第 4 节）。
- **runner.py** — `OfflineBenchmarkRunner` 把 `run_agent` 包进 `RunnableLambda` 并挂上回调，
  用进程内 `RLock` 串行执行，按白名单投影业务状态（`_state_projection`）与工具记录（`_tool_records`），
  最终组装一份完整的 trace；gate/trace 写入异常不影响业务结果。
- **trace_writer.py** — `write_trace` 先写临时文件、`fsync` 后 `os.replace` 原子落盘，
  `finally` 清理残留临时文件。
- **cli.py** — 离线评测入口：先关闭 LangSmith 环境变量、把 `client` 置 `None`，再导入业务模块，
  串行遍历 `evals/cases/*.json`。

---

## 2. 如何运行

### 2.1 评测基础设施测试（含端到端离线链路）

```bash
PYTHONPATH=. D:/anaconda3/envs/retail_env/python.exe src/tests/test_evaluation.py -v
```

实测结果：**20 个测试全部通过（0 失败 / 0 错误 / 0 跳过）**。

单独跑端到端离线链路（真实工作流 + 真实本地工具，不调模型）：

```bash
PYTHONPATH=. D:/anaconda3/envs/retail_env/python.exe src/tests/test_evaluation.py TestEndToEndOffline -v
```

实测结果：**1 个测试通过**（约 5 秒）。

### 2.2 既有回归测试

| 命令 | 实测结果 |
|---|---|
| `PYTHONPATH=. D:/anaconda3/envs/retail_env/python.exe src/tests/test_agent.py -v` | 5 通过 |
| `PYTHONPATH=. D:/anaconda3/envs/retail_env/python.exe src/tests/test_workflow.py -v` | 10 通过 |
| `PYTHONPATH=. D:/anaconda3/envs/retail_env/python.exe src/tests/test_api.py -v` | 8 通过 |

四者合计 **43 通过 / 0 失败 / 0 错误 / 0 跳过**。

### 2.3 离线评测 CLI

```bash
PYTHONPATH=. D:/anaconda3/envs/retail_env/python.exe -m src.evaluation.cli --cases evals/cases --traces evals/traces
```

参数：`--cases`（默认 `evals/cases`）、`--traces`（默认 `evals/traces`）、`--chroma-dir`
（默认**临时目录**，隔离 RAG 的 Chroma 持久化，不写真实 `chroma_db`）。

已实测完整运行（3 个案例）退出码 0，3 个案例 `gate` / `trajectory` 均为 `pass`、业务状态
`fallback`（`client=None` 走模板兜底）；运行前后真实 `retail.db` 与 `chroma_db` 均无写入。

- 默认：不传 `--chroma-dir` 时使用 `tempfile` 临时目录，运行结束自动清理。
- 覆盖：传 `--chroma-dir <dir>` 时使用指定目录（不自动清理）。
- 拒绝：若 `--chroma-dir` 指向项目真实 `chroma_db`，CLI 会报错并退出，不访问生产数据。

---

## 3. `evals/cases/` 各案例用途

| 案例文件 | case_id | 查询 | 预期意图 / 工具路径 |
|---|---|---|---|
| `macro.json` | `macro-smoke-001` | 分析最近社零数据走势并说明预测情况 | 宏观分析 → `query_macro_sqlite` + `forecast_timeseries` |
| `churn.json` | `churn-smoke-001` | 分析用户流失预测结果和风险分布 | 流失预测 → `predict_churn_batch` |
| `comprehensive.json` | `comprehensive-smoke-001` | 结合宏观零售数据和用户流失情况给出运营建议 | 综合分析 → 三个工具全部执行 |

---

## 4. Gate、trajectory、trace 分别检查什么

### 4.1 Gate（`run_gates`，四个子检查）

- `report_structure_gate` — 报告必须包含六个标题（`【核心结论】`…`【结果限制与不确定性】`），
  各出现一次且顺序正确；缺失/重复/乱序判 fail。
- `required_state_gate` — 必要业务字段（`intent`、`generation_status`、`final_report`、
  `report_sections`、`execution_trace`）存在；状态取值合法；`fallback` 必须带降级原因，
  `success` 携带降级原因判 warning。
- `payload_anchor_gate` — 结构化 payload 的关键锚点（宏观最新值、预测首个值、流失总数）是否
  出现在报告原文；基于格式化字符串的保守检查，仅作 advisory（缺失判 warning，不判 fail）。
- `tool_failure_disclosure_gate` — 工具失败时报告是否出现失败/缺失披露措辞；关键词规则仅提示，
  语义真实性需人工或 Judge 判断。

`run_gates` 汇总：任一 fail → fail；否则任一 warning → warning；否则 pass。

### 4.2 Trajectory（`validate_trajectory`）

- 节点路径与意图规则一致（宏观/流失/综合三条固定路径）。
- 工具调用序列与意图规则一致，且不出现未知工具。
- 重复节点事件检测（去重）。
- 节点异常按节点 `run_id` 去重统计。
- 工具失败/未配置状态汇总（与业务降级状态联动，判 warning）。

### 4.3 Trace（`write_trace` + runner 组装）

- 结构：`schema_version`、`run_id`（uuid4）、`case_id`（脱敏）、起止时间、耗时。
- 业务侧：`generation_status`、`fallback_reason`、报告摘要（限长）、状态白名单投影。
- 输入侧：query 只存 SHA-256 指纹 + 长度，`image_base64` 只存 `[OMITTED]`，**不落 query/图片原文**。
- 运行侧：`node_events` / `runtime_events` / `tool_calls`（字段白名单 + 脱敏 + 截断）。
- 评测侧：`evaluations.gate` / `evaluations.trajectory` / `evaluations.judge`（占位
  `not_implemented`）/ `evaluations.human_calibration`（占位）+ `instrumentation_errors`。
- 写入：`evals/traces/<run_id>.json`（目录已 gitignore），原子写入。

---

## 5. 无副作用离线评测：不调用大模型/LangSmith、不写真实持久化数据

离线评测做到“无外发、无污染”依赖以下机制（均已实现并在测试中验证）：

1. **不调大模型**：把 `graph_workflow.client` 置 `None`，`_llm_chat` 直接抛错走规则降级 + 模板兜底，
   全程不发起 `chat.completions.create`。
2. **不接 LangSmith**：导入业务模块前把 `LANGSMITH_TRACING=false`、`LANGCHAIN_TRACING_V2=false`、
   key 置空（`test_evaluation.py` 与 `cli.py` 均如此）。`.env` 的追踪开关已设为 `false`，默认关闭。
3. **不写真实 Chroma**：把 `mcp_server.chroma_path` 重定向到隔离目录——`TestEndToEndOffline`、
   `test_workflow`、`test_api` 用临时目录；`cli.py` 默认用临时目录，`--chroma-dir` 可显式指定，
   且指向真实 `chroma_db` 时会拒绝运行。
4. **不写真实 SQLite**：`test_api` 的 recall 用例把 `main.DB_PATH` patch 到临时库。
5. **trace 写临时目录**：测试用 `tempfile.TemporaryDirectory`，正式 CLI 写 `evals/traces/`（gitignore）。

已验证的“无副作用”端到端命令即第 2.1 节的 `TestEndToEndOffline`：真实 `run_agent` + 真实本地
工具（SQL / ARIMA / LightGBM / RAG，RAG 走临时 Chroma）+ `client=None`，仅不调真实模型 API。
实测运行前后 `retail.db` 与 `chroma_db` 均无新增写入。

---

## 6. 当前限制

1. **Mock 覆盖范围**：`test_evaluation.py` 中 `TestOfflineRunner` / `TestGates` /
   `TestCallbackCollector` 的业务节点用 `patch.object` 替换或使用合成迷你图，只有
   `TestEndToEndOffline` 走真实工作流 + 真实工具。故除端到端用例外，其余断言属于
   “评测基础设施真实、业务节点 Mock”的验证，非真实业务链路验证。
2. **进程内串行锁**：`OfflineBenchmarkRunner` 用 `threading.RLock` 串行化，并发测试验证的是
   “多线程同时提交时结果与文件互不串扰”，并非无锁并行正确性；跨进程无锁保护。
3. **Judge 尚未实现**：`evaluations.judge` 与 `evaluations.human_calibration` 均为
   `not_implemented` 占位，无语义质量门禁。
4. **“无网络外连”的验证级别**：导入业务模块不触发网络是用 socket 拦截（拦截
   `getaddrinfo` / `create_connection`）验证的（关闭态 0 次外连），运行期因 `client=None`
   无 LLM 调用；未做报文级抓包。
