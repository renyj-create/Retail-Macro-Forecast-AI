# src/api/main.py
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List, Optional
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import sqlite3
import sys
import os

# 🌟 核心：获取项目根目录并加入环境变量
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(BASE_DIR)

from src.agents.graph_workflow import build_agent_workflow

# 🌟 反馈数据库路径：复用项目根目录的 retail.db（与 data_pipeline / tools 保持一致）
DB_PATH = os.path.join(BASE_DIR, 'retail.db')


def init_feedback_table():
    """应用启动时确保 feedback 表已创建（幂等，不重复创建、不清空已有数据）"""
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
        conn.commit()
    finally:
        conn.close()


# 启动时初始化反馈表
init_feedback_table()

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

agent_app = build_agent_workflow()

class QueryRequest(BaseModel):
    query: str
    image_base64: str = "" # 允许前端传图片

class ReportResponse(BaseModel):
    report: str
    sql: str = ""
    data_count: int = 0
    kb_fragments: str = ""
    generation_status: str = "success"
    fallback_reason: str = ""


class FeedbackRequest(BaseModel):
    """用户对 AI 报告的点赞/踩反馈"""
    query: str = ""
    feedback: str = "up"  # 'up' 好评 / 'down' 差评
    report: str = ""


class FeedbackResponse(BaseModel):
    status: str
    message: str


class FeedbackRecord(BaseModel):
    """单条反馈记录"""
    id: int
    query: str
    feedback: str
    report: str
    created_at: str


class FeedbackListData(BaseModel):
    """反馈分页数据"""
    records: List[FeedbackRecord]
    total: int
    page: int
    page_size: int


class FeedbackListResponse(BaseModel):
    status: str
    message: str
    data: FeedbackListData


class FeedbackStatsData(BaseModel):
    """反馈统计数据"""
    total: int
    up_count: int
    down_count: int
    up_rate: float


class FeedbackStatsResponse(BaseModel):
    status: str
    message: str
    data: FeedbackStatsData


class ForecastMetrics(BaseModel):
    """时序回测指标"""
    mae: float
    rmse: float
    mape: float


class AnomalyPoint(BaseModel):
    """异常月份"""
    date: str
    value: float


class ForecastResponse(BaseModel):
    """社零总额时序预测响应（结构化字段，供前端 ECharts 直接对接）"""
    historical_dates: List[str]
    historical_values: List[float]
    forecast_dates: List[str]
    forecast_values: List[float]
    lower_bound: List[float]
    upper_bound: List[float]
    metrics: ForecastMetrics
    anomalies: List[AnomalyPoint] = Field(default_factory=list)

@app.get("/")
def read_root():
    return {"message": "欢迎使用零售消费品智能洞察 API", "docs_url": "/docs"}

@app.post("/api/v1/analyze", response_model=ReportResponse)
@limiter.limit("5/minute")
async def analyze_retail_data(request: Request, body: QueryRequest):
    """接收自然语言提问，调用底层 Agent 返回结构化诊断报告（限流 5 次/分钟）"""
    try:
        result = agent_app.invoke({
            "query": body.query,
            "image_base64": body.image_base64,
            "final_report": ""
        })
        # 🌟 同时返回执行明细（SQL / 数据量 / 知识库片段）与生成状态，供前端展示
        return ReportResponse(
            report=result["final_report"],
            sql=result.get("sql_statements", ""),
            data_count=result.get("data_count", 0),
            kb_fragments=result.get("kb_fragments", ""),
            generation_status=result.get("generation_status", "success"),
            fallback_reason=result.get("fallback_reason", ""),
        )
    except Exception as e:
        # 异常降级机制（JD3 要求）：整个 Agent 流程异常时标记为 failed
        return ReportResponse(
            report=f"系统繁忙，AI 分析服务暂时降级。错误信息: {str(e)}",
            generation_status="failed",
            fallback_reason=f"系统异常：{str(e)}",
        )

@app.post("/api/v1/feedback", response_model=FeedbackResponse)
def receive_feedback(request: FeedbackRequest):
    """接收用户对 AI 报告的点赞/踩反馈，持久化到 SQLite feedback 表"""
    # 校验反馈类型，避免非法数据入库
    if request.feedback not in ("up", "down"):
        raise HTTPException(status_code=400, detail="反馈类型仅支持 up 或 down")

    conn = sqlite3.connect(DB_PATH)
    try:
        # 参数化 SQL，避免 SQL 注入
        conn.execute(
            "INSERT INTO feedback (query, feedback, report) VALUES (?, ?, ?)",
            (request.query, request.feedback, request.report),
        )
        conn.commit()
        return FeedbackResponse(status="ok", message="感谢反馈")
    except Exception as e:
        # 数据库异常时如实报错，不假装保存成功
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
    # 校验反馈类型，仅允许 up / down / 不传
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
        # 无反馈时 up_rate 返回 0，避免除零错误
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


@app.get("/api/v1/forecast", response_model=ForecastResponse)
def forecast_retail_sales():
    """读取宏观社零数据，训练 ARIMA(1,1,1) 并返回结构化预测结果（含置信区间与异常点）"""
    try:
        # 延迟导入：statsmodels 仅在真正调用时才需要，避免影响其他接口启动
        from src.models.train_timeseries import run_forecast
        result = run_forecast(steps=3, test_months=3, order=(1, 1, 1))
        return ForecastResponse(**result)
    except Exception as e:
        # 异常降级机制（JD3 要求）：返回可读的 500 错误而非进程崩溃
        raise HTTPException(status_code=500, detail=f"时序预测服务暂时不可用: {str(e)}")


@app.get("/health")
def health_check():
    return {"status": "ok"}