# src/api/main.py
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import sqlite3
import json
import sys
import os
import math

# 🌟 核心：获取项目根目录并加入环境变量
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(BASE_DIR)

from src.agents.graph_workflow import run_agent
from src.agents.report_store import init_report_table, save_report, new_report_id

# 🌟 数据库路径：复用项目根目录的 retail.db（与 data_pipeline / tools 保持一致）
DB_PATH = os.path.join(BASE_DIR, 'retail.db')


def init_feedback_table():
    """应用启动时确保 feedback / recall_tasks 表已创建（幂等，不重复创建、不清空已有数据）"""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                feedback TEXT NOT NULL CHECK (feedback IN ('up', 'down')),
                report TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recall_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_ids TEXT NOT NULL,
                user_count INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'created',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


# 启动时初始化数据表
init_feedback_table()
init_report_table(DB_PATH)

app = FastAPI(
    title="零售消费品智能洞察 API",
    docs_url="/docs",
    swagger_js_url="https://fastly.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
    swagger_css_url="https://fastly.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
)

# 🌟 核心：允许前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🌟 限流器：基于客户端 IP，具体接口上用 @limiter.limit 声明额度
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


# 🌟 全局异常处理器：统一返回规范 JSON 结构 {status, message, data}，提升接口健壮性
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"status": "error", "message": "请求过于频繁，请稍后重试（限流 5 次/分钟）", "data": None},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": str(exc.detail), "data": None},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": f"服务器内部错误：{str(exc)}", "data": None},
    )


# ======================================================================
# 响应模型
# ======================================================================
class QueryRequest(BaseModel):
    query: str
    image_base64: str = ""


class ExecutionRecord(BaseModel):
    name: str
    input: Dict[str, Any] = Field(default_factory=dict)
    status: str
    summary: str = ""
    error: str = ""
    duration_ms: Optional[float] = None
    sql: str = ""
    source: str = ""


class ReportSection(BaseModel):
    title: str
    content: str


class Suggestion(BaseModel):
    title: str = ""
    description: str = ""
    rationale: str = ""
    evidence: str = ""
    category: str = ""
    priority: str = "普通"


class MacroPoint(BaseModel):
    date: str
    value: float
    yoy: float


class AnalyzeData(BaseModel):
    macro: List[MacroPoint] = Field(default_factory=list)
    forecast: Optional[Dict[str, Any]] = None
    churn: Optional[Dict[str, Any]] = None


class ReportResponse(BaseModel):
    report: str
    intent: str = ""
    intent_reason: str = ""
    generation_status: str = "success"
    fallback_reason: str = ""
    sections: List[ReportSection] = Field(default_factory=list)
    suggestions: List[Suggestion] = Field(default_factory=list)
    execution: List[ExecutionRecord] = Field(default_factory=list)
    data: AnalyzeData = Field(default_factory=AnalyzeData)
    kb_fragments: str = ""
    fact_check: Optional[Dict[str, Any]] = None
    report_id: str = ""
    report_persisted: bool = False


class FeedbackRequest(BaseModel):
    """用户对 AI 报告的点赞/踩反馈"""
    query: str = ""
    feedback: str = "up"
    report: str = ""


class FeedbackResponse(BaseModel):
    status: str
    message: str


class FeedbackRecord(BaseModel):
    id: int
    query: str
    feedback: str
    report: str
    created_at: str


class FeedbackListData(BaseModel):
    records: List[FeedbackRecord]
    total: int
    page: int
    page_size: int


class FeedbackListResponse(BaseModel):
    status: str
    message: str
    data: FeedbackListData


class FeedbackStatsData(BaseModel):
    total: int
    up_count: int
    down_count: int
    up_rate: float


class FeedbackStatsResponse(BaseModel):
    status: str
    message: str
    data: FeedbackStatsData


class ForecastMetrics(BaseModel):
    mae: Optional[float] = None
    rmse: Optional[float] = None
    mape: Optional[float] = None
    n: Optional[int] = None


class AnomalyPoint(BaseModel):
    date: str
    value: float


class ForecastResponse(BaseModel):
    historical_dates: List[str]
    historical_values: List[float]
    forecast_dates: List[str]
    forecast_values: List[float]
    lower_bound: List[float]
    upper_bound: List[float]
    metrics: ForecastMetrics
    anomalies: List[AnomalyPoint] = Field(default_factory=list)
    backtest: Optional[Dict[str, Any]] = None
    rolling_backtest: Optional[Dict[str, Any]] = None
    data_note: str = ""
    forecast_note: str = ""


class RecallRequest(BaseModel):
    user_ids: List[int]


# ======================================================================
# 基础接口
# ======================================================================
@app.get("/")
def read_root():
    return {"message": "欢迎使用零售消费品智能洞察 API", "docs_url": "/docs"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


# ======================================================================
# 智能问数 Agent
# ======================================================================
@app.post("/api/v1/analyze", response_model=ReportResponse)
@limiter.limit("5/minute")
async def analyze_retail_data(request: Request, body: QueryRequest):
    """
    接收自然语言提问，执行「意图识别 → 条件路由 → 真实工具调用 → 报告生成」，
    返回结构化报告、六段式小节、统一执行追踪与图表数据。
    """
    if not body.query or not body.query.strip():
        raise HTTPException(status_code=400, detail="问题内容不能为空")

    try:
        result = run_agent(body.query, body.image_base64)

        macro_payload = result.get("macro_payload") or []
        forecast_payload = result.get("forecast_payload")
        churn_payload = result.get("churn_payload")
        suggestions = result.get("suggestions") or []

        # 为来源报告建立持久化记录（唯一 report_id）
        report_id = new_report_id()
        report_persisted = False
        try:
            save_report(
                DB_PATH,
                report_id,
                body.query,
                result.get("intent", ""),
                result.get("generation_status", "success"),
                result.get("fallback_reason", ""),
                result["final_report"],
                suggestions,
            )
            report_persisted = True
        except Exception as e:
            print(f"[API] 报告持久化失败（report_id={report_id}）: {e}")

        return ReportResponse(
            report=result["final_report"],
            intent=result.get("intent", ""),
            intent_reason=result.get("intent_reason", ""),
            generation_status=result.get("generation_status", "success"),
            fallback_reason=result.get("fallback_reason", ""),
            sections=[
                ReportSection(title=s["title"], content=s["content"])
                for s in result.get("report_sections", [])
            ],
            suggestions=[Suggestion(**s) for s in suggestions],
            execution=[
                ExecutionRecord(**rec) for rec in result.get("execution_trace", [])
            ],
            data=AnalyzeData(
                macro=[MacroPoint(**p) for p in macro_payload],
                forecast=forecast_payload,
                churn=churn_payload,
            ),
            kb_fragments=result.get("kb_fragments", ""),
            fact_check=result.get("fact_check"),
            report_id=report_id,
            report_persisted=report_persisted,
        )
    except HTTPException:
        raise
    except Exception as e:
        # 异常降级机制：整个 Agent 流程异常时标记为 failed
        return ReportResponse(
            report=f"系统繁忙，AI 分析服务暂时降级。错误信息: {str(e)}",
            intent="",
            intent_reason="",
            generation_status="failed",
            fallback_reason=f"系统异常：{str(e)}",
            sections=[],
            execution=[],
            data=AnalyzeData(),
        )


# ======================================================================
# 用户流失预测（真实批量推理）
# ======================================================================
@app.get("/api/v1/churn/predict")
def churn_predict(top_n: int = Query(20, ge=1, le=100)):
    """对真实（模拟）流失数据集执行 LightGBM 批量推理，返回风险分布 / 高风险用户 / 特征归因"""
    try:
        from src.models.churn_inference import predict_batch
        result = predict_batch(top_n=top_n)
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        return {"status": "ok", "message": "查询成功", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"流失预测服务暂时不可用: {str(e)}")


@app.post("/api/v1/churn/recall")
def create_recall_task(request: RecallRequest):
    """创建批量召回任务（持久化至 recall_tasks 表，真实创建后端任务记录）"""
    if not request.user_ids:
        raise HTTPException(status_code=400, detail="请至少选择一位用户")
    # 去重、限制单次上限，避免异常入参
    user_ids = list(dict.fromkeys(request.user_ids))[:500]
    if not user_ids:
        raise HTTPException(status_code=400, detail="请至少选择一位有效用户")

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            "INSERT INTO recall_tasks (user_ids, user_count, status) VALUES (?, ?, 'created')",
            (json.dumps(user_ids), len(user_ids)),
        )
        conn.commit()
        task_id = cur.lastrowid
        return {
            "status": "ok",
            "message": "召回任务已创建",
            "data": {"task_id": task_id, "user_count": len(user_ids), "status": "created"},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"召回任务创建失败: {str(e)}")
    finally:
        conn.close()


def _finite_float(value):
    """把数据库值安全转换为有限 float；对 NaN / ±Inf / None / 非数值返回 None。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ======================================================================
# 数据总览（真实数据，供前端 KPI 卡片）
# ======================================================================
@app.get("/api/v1/overview")
def overview():
    """返回数据总览所需的真实指标：最新社零、流失标签占比、时序回测指标等"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        # 与单月同比口径一致：仅取当月值与同比都非空的最新记录，再经 _finite_float 兜底 NaN/Inf，
        # 不把「1—2 月累计发布」口径（当月值/同比为空）误当成单月数据。
        recent_rows = conn.execute(
            "SELECT date, retail_sales_current, yoy_growth FROM macro_retail_sales "
            "WHERE retail_sales_current IS NOT NULL AND yoy_growth IS NOT NULL "
            "ORDER BY date DESC LIMIT 20"
        ).fetchall()
        churn_row = conn.execute(
            "SELECT COUNT(*) AS total, AVG(is_churn) AS rate FROM churn_dataset"
        ).fetchone()
        conn.close()

        # 依次取最新一条「有效」记录；全无效时返回明确空态（不伪造 0 / 不虚构月份）
        latest_macro = {"date": "", "value": None, "yoy": None}
        for row in recent_rows:
            value = _finite_float(row["retail_sales_current"])
            yoy = _finite_float(row["yoy_growth"])
            if value is None or yoy is None:
                continue
            latest_macro = {
                "date": str(row["date"])[:7],
                "value": round(value, 1),
                "yoy": round(yoy, 2),
            }
            break
        churn_total = int(churn_row["total"]) if churn_row["total"] is not None else 0
        churn_rate = round(float(churn_row["rate"]), 4) if churn_row["rate"] is not None else 0.0

        # 时序回测指标（真实计算）
        forecast_metrics = None
        try:
            from src.models.train_timeseries import run_forecast
            f = run_forecast(steps=3, test_months=3, order=(1, 1, 1))
            forecast_metrics = f["metrics"]
        except Exception:
            forecast_metrics = None

        # 训练期评估指标（训练脚本输出，当前数据快照，非实时计算）
        model_eval = {
            "auc": 0.82,
            "ks": 0.56,
            "note": "训练期评估指标（当前数据快照，由训练脚本打印，非运行时实时计算）",
        }

        return {
            "status": "ok",
            "message": "查询成功",
            "data": {
                "latest_macro": latest_macro,
                "churn": {
                    "total": churn_total,
                    "label_rate": churn_rate,
                    "data_note": "模拟数据（RFM 规则生成），不代表真实企业客户",
                },
                "forecast_metrics": forecast_metrics,
                "model_eval": model_eval,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"数据总览查询失败: {str(e)}")


# ======================================================================
# 反馈闭环
# ======================================================================
@app.post("/api/v1/feedback", response_model=FeedbackResponse)
def receive_feedback(request: FeedbackRequest):
    """接收用户对 AI 报告的点赞/踩反馈，持久化到 SQLite feedback 表"""
    if request.feedback not in ("up", "down"):
        raise HTTPException(status_code=400, detail="反馈类型仅支持 up 或 down")

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT INTO feedback (query, feedback, report) VALUES (?, ?, ?)",
            (request.query, request.feedback, request.report),
        )
        conn.commit()
        return FeedbackResponse(status="ok", message="感谢反馈")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"反馈保存失败: {str(e)}")
    finally:
        conn.close()


@app.get("/api/v1/feedback", response_model=FeedbackListResponse)
def list_feedback(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    feedback: Optional[str] = Query(None),
):
    """分页查询反馈记录（按提交时间倒序，最新在前）"""
    if feedback is not None and feedback not in ("up", "down"):
        raise HTTPException(status_code=400, detail="feedback 参数仅支持 up 或 down")

    where = ""
    params = []
    if feedback in ("up", "down"):
        where = "WHERE feedback = ?"
        params.append(feedback)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM feedback {where}", params
        ).fetchone()["c"]

        offset = (page - 1) * page_size
        rows = conn.execute(
            f"SELECT id, query, feedback, report, created_at FROM feedback {where} "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()

        records = [
            FeedbackRecord(
                id=r["id"],
                query=r["query"],
                feedback=r["feedback"],
                report=r["report"] or "",
                created_at=r["created_at"],
            )
            for r in rows
        ]
        return FeedbackListResponse(
            status="ok",
            message="查询成功",
            data=FeedbackListData(
                records=records, total=total, page=page, page_size=page_size
            ),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询反馈失败: {str(e)}")
    finally:
        conn.close()


@app.get("/api/v1/feedback/stats", response_model=FeedbackStatsResponse)
def feedback_stats():
    """反馈统计：总数 / 点赞数 / 点踩数 / 点赞率"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        total = conn.execute("SELECT COUNT(*) AS c FROM feedback").fetchone()["c"]
        up_count = conn.execute(
            "SELECT COUNT(*) AS c FROM feedback WHERE feedback = 'up'"
        ).fetchone()["c"]
        down_count = conn.execute(
            "SELECT COUNT(*) AS c FROM feedback WHERE feedback = 'down'"
        ).fetchone()["c"]
        up_rate = round(up_count / total, 4) if total > 0 else 0.0

        return FeedbackStatsResponse(
            status="ok",
            message="查询成功",
            data=FeedbackStatsData(
                total=total, up_count=up_count, down_count=down_count, up_rate=up_rate
            ),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询反馈统计失败: {str(e)}")
    finally:
        conn.close()


# ======================================================================
# 时序预测
# ======================================================================
@app.get("/api/v1/forecast", response_model=ForecastResponse)
def forecast_retail_sales():
    """读取宏观社零数据，训练 ARIMA(1,1,1) 并返回结构化预测结果（含历史回测对比、基线对比、置信区间与异常点）"""
    try:
        from src.models.train_timeseries import run_forecast
        result = run_forecast(steps=3, test_months=3, order=(1, 1, 1))
        return ForecastResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"时序预测服务暂时不可用: {str(e)}")


# ======================================================================
# 知识库检索（独立测试面板）
# ======================================================================
@app.get("/api/v1/kb/search")
def kb_search(q: str = Query(..., min_length=1), top_k: int = Query(5, ge=1, le=10)):
    """独立 RAG 检索：对用户问题执行 TF-IDF + ChromaDB 检索，返回结构化命中片段与余弦距离。"""
    try:
        from src.agents.tools import retrieve_kb
        result = retrieve_kb(q, top_k=top_k)
        hits = [
            {
                "text": h["text"],
                "distance": h["distance"],
                "score": round(1 - h["distance"], 4),
            }
            for h in result.get("hits", [])
        ]
        return {
            "status": "ok",
            "message": "查询成功",
            "data": {
                "query": q,
                "source": result.get("source", ""),
                "hit_count": len(hits),
                "hits": hits,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"知识库检索失败: {str(e)}")
