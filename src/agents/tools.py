# src/agents/tools.py
import os
import sys
import time
import math
import sqlite3
import pandas as pd
import joblib

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 🌟 将项目根目录加入搜索路径，使本文件可被独立导入（无需依赖 graph_workflow 的 sys.path 处理）
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)


def _finite_float(value):
    """把数据库值安全转换为有限 float；对 NaN / ±Inf / None / 非数值返回 None。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def retrieve_kb(query: str, top_k: int = 5, chroma_path: str = None) -> dict:
    """
    独立 RAG 检索核心：读取 docs/policy.txt，用字符级 n-gram TF-IDF 向量化后从本地
    ChromaDB 检索 Top-K 片段，返回结构化结果（含来源文件与余弦距离）。

    供 rag_search 工具与 /api/v1/kb/search 接口共用，避免两处重复实现同一套检索逻辑。
    返回 dict:
        source : 知识库来源文件相对路径（文件缺失时为空字符串）
        hits   : [{text, distance}]，distance 为余弦距离（越小越相似，>=0.999 视为无交集被剔除）
    """
    import chromadb
    from sklearn.feature_extraction.text import TfidfVectorizer

    policy_path = os.path.join(BASE_DIR, 'docs', 'policy.txt')
    source = os.path.relpath(policy_path, BASE_DIR).replace(os.sep, '/')
    if not os.path.exists(policy_path):
        return {"source": "", "hits": []}

    with open(policy_path, 'r', encoding='utf-8') as f:
        raw = f.read()

    chunks = [c.strip() for c in raw.split('\n\n') if c.strip()]
    if not chunks:
        return {"source": source, "hits": []}

    vectorizer = TfidfVectorizer(analyzer='char', ngram_range=(2, 3))
    chunk_vectors = vectorizer.fit_transform(chunks).toarray().tolist()
    query_vector = vectorizer.transform([query]).toarray().tolist()

    if chroma_path is None:
        chroma_path = os.path.join(BASE_DIR, 'chroma_db')
    client = chromadb.PersistentClient(path=chroma_path)
    try:
        # 先删后建：语料/分词变化会导致向量维度不匹配，演示场景下每次重建以保证一致
        try:
            client.delete_collection(name="policy_docs")
        except Exception:
            pass
        collection = client.create_collection(
            name="policy_docs", metadata={"hnsw:space": "cosine"}
        )
        collection.add(
            ids=[f"chunk_{i}" for i in range(len(chunks))],
            documents=chunks,
            embeddings=chunk_vectors,
        )
        result = collection.query(
            query_embeddings=query_vector,
            n_results=min(top_k, len(chunks)),
            include=["documents", "distances"],
        )
        docs = result.get("documents", [[]])[0]
        distances = result.get("distances", [[]])[0]
    finally:
        client.close()

    hits = []
    for doc, dist in zip(docs, distances):
        if doc and dist is not None and float(dist) < 0.999:
            hits.append({"text": doc, "distance": round(float(dist), 4)})
    return {"source": source, "hits": hits}


class MCPToolServer:
    """
    统一封装所有外部工具（普通 Python 方法，进程内直接调用，非 MCP 协议）。

    每个工具在返回结果的同时，会通过 _record() 写入一条结构化执行记录，
    供 Agent 报告与前端「执行明细」面板做可追溯展示。
    """

    def __init__(self):
        self.db_path = os.path.join(BASE_DIR, 'retail.db')
        self.model_path = os.path.join(BASE_DIR, 'src', 'models', 'saved_models', 'lgbm_churn_model.pkl')
        # RAG 向量库持久化目录（测试可重定向到临时目录，避免污染真实 chroma_db）
        self.chroma_path = os.path.join(BASE_DIR, 'chroma_db')
        # 🌟 执行明细元数据：供 Agent 报告的可解释性展示使用
        self.last_sql = ""
        self.last_data_count = 0
        self.last_kb_fragments = ""
        # 🌟 统一执行追踪：list[dict]，记录工具名/输入/状态/耗时/错误/摘要
        self.execution_log = []
        # 🌟 结构化结果 payload：供前端直接渲染图表与表格（真实数据，非写死）
        self.last_macro_payload = []
        self.last_forecast_payload = None
        self.last_churn_payload = None

    # ------------------------------------------------------------------
    # 执行追踪基础设施
    # ------------------------------------------------------------------
    def reset_execution_log(self):
        self.execution_log = []
        self.last_sql = ""
        self.last_data_count = 0
        self.last_kb_fragments = ""
        self.last_macro_payload = []
        self.last_forecast_payload = None
        self.last_churn_payload = None

    def _record(self, name, status, summary, input_params=None, error="",
                duration_ms=None, sql=None, source=None):
        """写入一条工具执行记录。"""
        self.execution_log.append({
            "name": name,
            "input": input_params or {},
            "status": status,          # success / failed / not_configured
            "summary": summary,
            "error": error,
            "duration_ms": round(duration_ms, 1) if duration_ms is not None else None,
            "sql": sql or "",
            "source": source or "",
        })

    def _execution_summary(self, name):
        """返回该工具最后一次执行的记录摘要（供报告上下文使用）。"""
        for rec in reversed(self.execution_log):
            if rec["name"] == name:
                return rec
        return None

    # ------------------------------------------------------------------
    # 工具 1：宏观社零 SQL 查询
    # ------------------------------------------------------------------
    def query_macro_sqlite(self, limit: int = 12) -> tuple:
        """
        MCP Tool: 查询宏观社零数据。

        返回最近 limit 期社零额与同比增速，并附带简单趋势摘要；
        同时把结构化结果写入 last_macro_payload 供前端图表使用。
        """
        started = time.perf_counter()
        sql = (
            "SELECT date, retail_sales_current, yoy_growth "
            "FROM macro_retail_sales ORDER BY date DESC LIMIT ?"
        )
        try:
            conn = sqlite3.connect(self.db_path)
            df = pd.read_sql(sql, conn, params=(int(limit),))
            conn.close()

            if df.empty:
                self.last_sql = sql
                self.last_data_count = 0
                self.last_macro_payload = []
                self._record(
                    "query_macro_sqlite", "success",
                    "宏观社零数据查询成功，但数据库暂无数据",
                    input_params={"limit": limit},
                    duration_ms=(time.perf_counter() - started) * 1000,
                    sql=sql,
                )
                return "宏观社零数据：数据库中暂无数据。", []

            self.last_sql = sql
            # 仅保留单月同比口径下可用的行：当月社零额与同比增速都必须是有限数值。
            # 「1—2 月累计发布」口径的行（当月值/同比为空，如 2026-02）不适用于单月同比分析，
            # 予以剔除；其余有效历史数据一律保留，不做无差别删除。
            payload = []
            for _, row in df.iterrows():
                value = _finite_float(row['retail_sales_current'])
                yoy = _finite_float(row['yoy_growth'])
                if value is None or yoy is None:
                    continue
                payload.append({
                    "date": str(row['date'])[:7],
                    "value": round(value, 1),
                    "yoy": round(yoy, 2),
                })

            if not payload:
                self.last_data_count = 0
                self.last_macro_payload = []
                self._record(
                    "query_macro_sqlite", "success",
                    "宏观社零数据查询成功，但暂无符合单月同比口径的有效数据",
                    input_params={"limit": limit},
                    duration_ms=(time.perf_counter() - started) * 1000,
                    sql=sql,
                )
                return "宏观社零数据：暂无符合单月同比口径的有效数据。", []

            self.last_data_count = len(payload)
            self.last_macro_payload = payload

            latest = payload[0]
            recent_yoy = [p["yoy"] for p in payload]
            summary = (
                f"最新一期 {latest['date']} 社零总额 {latest['value']} 亿元，"
                f"同比增长 {latest['yoy']}%；近 {len(recent_yoy)} 期同比增速区间 "
                f"[{min(recent_yoy)}%, {max(recent_yoy)}%]。"
            )

            lines = ["最新宏观社零数据（按月，最新在前）："]
            for p in payload:
                lines.append(f"- {p['date']}: 当月总额 {p['value']} 亿元, 同比增长 {p['yoy']}%")
            lines.append("")
            lines.append(f"趋势摘要：{summary}")

            self._record(
                "query_macro_sqlite", "success", summary,
                input_params={"limit": limit},
                duration_ms=(time.perf_counter() - started) * 1000,
                sql=sql,
            )
            return "\n".join(lines), payload
        except Exception as e:
            self._record(
                "query_macro_sqlite", "failed", "宏观数据查询失败",
                input_params={"limit": limit}, error=str(e),
                duration_ms=(time.perf_counter() - started) * 1000, sql=sql,
            )
            return f"宏观数据查询失败: {str(e)}", []

    # ------------------------------------------------------------------
    # 工具 2：时序预测（ARIMA + 异常检测）
    # ------------------------------------------------------------------
    def forecast_timeseries(self) -> tuple:
        """
        MCP Tool: 社零总额时间序列分析（历史回测 + 基线对比 + 未来预测 + 异常检测）
        调用 src/models/train_timeseries.py 中的时序逻辑。优先返回「历史三个月回测」的
        预测值与真实值逐月对比及误差指标，未来三个月预测作为辅助单独标注、不冒充已验证结果。
        """
        started = time.perf_counter()
        try:
            from src.models.train_timeseries import run_forecast

            result = run_forecast(steps=3, test_months=3, order=(1, 1, 1))
            self.last_forecast_payload = result

            bt = result['backtest']
            metrics = bt['metrics']
            bl = bt['baselines']
            lines = [
                "===== 社零总额时间序列分析报告 =====",
                f"统计口径：{result.get('data_note', '')}",
                "",
                f"【历史回测】训练数据截止 {bt['train_end']}，回测月份 {bt['test_months']}：",
            ]
            for p in bt['points']:
                lines.append(
                    f"- {p['date']}：预测 {p['forecast']} 亿元，真实 {p['actual']} 亿元，"
                    f"绝对误差 {p['abs_error']} 亿元，相对误差 {p['rel_error_pct']}%，"
                    f"95% 区间 [{p['lower']}, {p['upper']}]"
                )
            lines.append(
                f"- ARIMA 回测指标：MAE={metrics['mae']} 亿元，RMSE={metrics['rmse']} 亿元，"
                f"MAPE={metrics['mape']}%"
            )
            lines.append(
                f"- 基线对比：沿用上月值 MAPE={bl['naive']['mape']}%，"
                f"同月去年 MAPE={bl['seasonal']['mape']}%"
            )
            lines.append("")
            lines.append("【未来 3 个月预测】（辅助，未经真实值验证，不构成准确率保证）：")
            for d, v, lo, hi in zip(
                result['forecast_dates'], result['forecast_values'],
                result['lower_bound'], result['upper_bound']
            ):
                lines.append(f"  {d}: 预测 {v} 亿元，区间 [{lo}, {hi}]")

            lines.append("")
            lines.append(f"异常检测：共标记 {len(result['anomalies'])} 个异常月份")
            for a in result['anomalies']:
                lines.append(f"  ⚠ {a['date']}: {a['value']} 亿元")

            self._record(
                "forecast_timeseries", "success",
                f"历史回测 MAPE={metrics['mape']}%（回测 {bt['test_months']}，"
                f"同月去年基线 MAPE={bl['seasonal']['mape']}%），"
                f"未来预测 {len(result['forecast_dates'])} 个月（辅助，未验证）",
                input_params={"steps": 3, "test_months": 3, "order": "(1,1,1)"},
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            return "\n".join(lines), result
        except Exception as e:
            self._record(
                "forecast_timeseries", "failed", "时序预测失败",
                input_params={"steps": 3, "test_months": 3}, error=str(e),
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            return f"时序预测失败（已优雅降级）: {str(e)}", None

    # ------------------------------------------------------------------
    # 工具 3：用户流失批量预测（真实模型推理）
    # ------------------------------------------------------------------
    def predict_churn_batch(self, top_n: int = 20) -> tuple:
        """
        MCP Tool: 对真实（模拟）流失数据集执行 LightGBM 批量推理。

        返回风险分布、高风险用户、特征归因等结构化结果，
        同时把结构化结果写入 last_churn_payload 供前端图表使用。
        """
        started = time.perf_counter()
        try:
            from src.models.churn_inference import predict_batch

            result = predict_batch(top_n=top_n)
            if "error" in result:
                self._record(
                    "predict_churn_batch", "failed", result["error"],
                    input_params={"top_n": top_n},
                    duration_ms=(time.perf_counter() - started) * 1000,
                )
                return f"流失预测失败: {result['error']}", None

            self.last_churn_payload = result

            dist = {d["level"]: d["count"] for d in result["risk_distribution"]}
            top_features = ", ".join(
                f"{f['feature']}({f['importance']})"
                for f in result["feature_importance"][:3]
            )
            summary = (
                f"共对 {result['total']} 名模拟用户执行流失预测，"
                f"风险分布：低风险 {dist.get('低风险', 0)} / 中风险 {dist.get('中风险', 0)} / "
                f"高风险 {dist.get('高风险', 0)} / 极高风险 {dist.get('极高风险', 0)}。"
                f"Top3 特征：{top_features}。"
            )

            lines = ["===== 用户流失批量预测报告（模拟数据） ====="]
            lines.append(f"样本量：{result['total']} 名用户（模拟数据，流失标签占比 {result['churn_rate'] or '未知'}）")
            lines.append("")
            lines.append("风险分布（按概率分位数划分）：")
            for d in result["risk_distribution"]:
                lines.append(f"  {d['level']}: {d['count']} 人（{d['ratio'] * 100:.1f}%）")
            lines.append("")
            lines.append("Top3 影响特征（平均绝对 SHAP 值，模型解释指标，非百分比）：")
            for f in result["feature_importance"][:3]:
                lines.append(f"  {f['feature']}: {f['importance']}")
            lines.append("")
            lines.append("高风险用户示例（Top3）：")
            for u in result["top_risk_users"][:3]:
                lines.append(
                    f"  用户{u['user_id']}（{u['city_tier']}，{u['age']}岁）："
                    f"流失概率 {u['churn_prob'] * 100:.1f}%，{u['risk_level']}"
                )

            self._record(
                "predict_churn_batch", "success", summary,
                input_params={"top_n": top_n},
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            return "\n".join(lines), result
        except Exception as e:
            self._record(
                "predict_churn_batch", "failed", "流失批量预测失败",
                input_params={"top_n": top_n}, error=str(e),
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            return f"流失预测失败: {str(e)}", None

    # ------------------------------------------------------------------
    # 工具 4：单用户流失预测（保留，特征顺序改用模型 feature_names_in_）
    # ------------------------------------------------------------------
    def predict_churn_lightgbm(self, recency_days=60, frequency=1, monetary=100.0,
                               avg_amount=100.0, age=30, city_tier="二线") -> str:
        """
        MCP Tool: 单用户流失概率预测（示例，非真实客户数据）。

        特征列顺序严格使用模型训练时保存的 feature_names_in_，
        城市等级由入参映射到 one-hot 列，避免写死顺序导致错位。
        """
        started = time.perf_counter()
        try:
            model = joblib.load(self.model_path)
            feature_order = [str(c) for c in model.feature_names_in_]

            # 城市等级 → one-hot 映射（训练脚本 drop_first=True，丢弃「一线」）
            onehot = {f"city_tier_{city_tier}": 1}
            row = {
                "recency_days": recency_days,
                "frequency": frequency,
                "monetary": monetary,
                "avg_amount": avg_amount,
                "age": age,
                "city_tier_二线": onehot.get("city_tier_二线", 0),
                "city_tier_三线": onehot.get("city_tier_三线", 0),
            }
            X_input = pd.DataFrame([[row.get(c, 0) for c in feature_order]], columns=feature_order)
            prob = float(model.predict_proba(X_input)[0][1])
            summary = (
                f"示例用户（{recency_days} 天未购买，频次 {frequency}，城市 {city_tier}）"
                f"流失概率 {prob:.2%}"
            )
            self._record(
                "predict_churn_lightgbm", "success", summary,
                input_params={
                    "recency_days": recency_days, "frequency": frequency,
                    "monetary": monetary, "avg_amount": avg_amount,
                    "age": age, "city_tier": city_tier,
                },
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            return f"流失预测结果：基于当前特征（{recency_days} 天未购买，购买频次 {frequency} 次），模型预测该用户流失概率为 {prob:.2%}。"
        except Exception as e:
            self._record(
                "predict_churn_lightgbm", "failed", "单用户流失预测失败",
                input_params={"recency_days": recency_days, "city_tier": city_tier},
                error=str(e), duration_ms=(time.perf_counter() - started) * 1000,
            )
            return f"模型预测失败: {str(e)}"

    # ------------------------------------------------------------------
    # 工具 5：RAG 知识库检索
    # ------------------------------------------------------------------
    def rag_search(self, query: str, top_k: int = 2) -> tuple:
        """
        MCP Tool: RAG 检索企业知识库（基于 ChromaDB 本地向量检索）

        复用 retrieve_kb() 完成「读取 → 分块 → TF-IDF 向量化 → ChromaDB 检索」，
        返回真实原文片段；无匹配则明确返回「未在知识库中找到相关研报」。
        """
        started = time.perf_counter()
        try:
            result = retrieve_kb(query, top_k=top_k, chroma_path=self.chroma_path)
            if not result.get("source"):
                # 知识库文件缺失，视为「未接入」，不伪造内容
                self.last_kb_fragments = ""
                self._record(
                    "rag_search", "not_configured", "知识库文件缺失，未检索到内容",
                    input_params={"query": query, "top_k": top_k},
                    duration_ms=(time.perf_counter() - started) * 1000,
                )
                return "未在知识库中找到相关研报", ""

            hits = result.get("hits", [])
            if not hits:
                self.last_kb_fragments = ""
                self._record(
                    "rag_search", "success", "知识库检索完成，未命中相关片段",
                    input_params={"query": query, "top_k": top_k},
                    duration_ms=(time.perf_counter() - started) * 1000,
                )
                return "未在知识库中找到相关研报", ""

            fragments = "\n\n".join(h["text"] for h in hits)
            self.last_kb_fragments = fragments
            self._record(
                "rag_search", "success", f"命中 {len(hits)} 条知识库片段",
                input_params={"query": query, "top_k": top_k},
                duration_ms=(time.perf_counter() - started) * 1000,
                source=result.get("source", ""),
            )
            return "【企业知识库检索结果】\n" + fragments, fragments
        except Exception as e:
            self._record(
                "rag_search", "failed", "知识库检索失败（已优雅降级）",
                input_params={"query": query, "top_k": top_k}, error=str(e),
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            return f"知识库检索失败（已优雅降级）: {str(e)}", ""

    # ------------------------------------------------------------------
    # 工具 6：A/B 测试统计检验（保持原样，当前未接入工作流）
    # ------------------------------------------------------------------
    def evaluate_ab_test(self, control_data, treatment_data) -> str:
        """
        MCP Tool: A/B 测试统计检验
        使用 scipy.stats 进行 Levene 方差齐性检验 + 独立样本 T 检验，
        根据方差是否齐性选择 Student's t-test 或 Welch's t-test，并计算增量提升 Uplift。

        参数:
            control_data:   对照组样本（list 或 numpy 数组）
            treatment_data: 实验组样本（list 或 numpy 数组）
        """
        started = time.perf_counter()
        try:
            import numpy as np
            from scipy import stats as sps

            control = np.asarray(control_data, dtype=float)
            treatment = np.asarray(treatment_data, dtype=float)

            # 样本量防御：过少样本无法进行可靠的统计检验
            if control.size < 2 or treatment.size < 2:
                self._record(
                    "evaluate_ab_test", "failed", "A/B 测试数据不足",
                    error="对照组与实验组各需至少 2 个样本",
                    duration_ms=(time.perf_counter() - started) * 1000,
                )
                return "❌ A/B 测试数据不足：对照组与实验组各需至少 2 个样本。"

            # 1) 描述性统计
            c_mean, c_std = float(control.mean()), float(control.std(ddof=1))
            t_mean, t_std = float(treatment.mean()), float(treatment.std(ddof=1))

            # 2) Levene 方差齐性检验（原假设：两组方差相等）
            lev_stat, lev_p = sps.levene(control, treatment)
            equal_var = lev_p >= 0.05  # p>=0.05 接受原假设 → 方差齐性

            # 3) 依据方差齐性选择检验方法
            t_stat, t_p = sps.ttest_ind(control, treatment, equal_var=equal_var)
            test_name = "Student's t-test（方差齐性）" if equal_var else "Welch's t-test（方差不齐）"

            # 4) 增量提升 Uplift：实验组相对对照组的相对提升百分比
            uplift = (t_mean - c_mean) / c_mean * 100 if c_mean != 0 else float('nan')
            significant = t_p < 0.05

            conclusion = ("✅ 两组差异统计显著（p<0.05），实验组显著优于对照组。"
                          if significant else
                          "❌ 两组差异不显著（p>=0.05），暂无法证明实验组有效。")

            report = (
                "===== A/B 测试统计检验报告 =====\n"
                f"对照组（Control）  ：样本数={control.size}, 均值={c_mean:.4f}, 标准差={c_std:.4f}\n"
                f"实验组（Treatment）：样本数={treatment.size}, 均值={t_mean:.4f}, 标准差={t_std:.4f}\n\n"
                f"【Levene 方差齐性检验】统计量={lev_stat:.4f}, p值={lev_p:.4f} → "
                f"{'方差齐性' if equal_var else '方差不齐'}（显著性阈值 0.05）\n"
                f"【{test_name}】t统计量={t_stat:.4f}, p值={t_p:.4f}\n"
                f"【增量提升 Uplift】{uplift:+.2f}%\n\n"
                f"结论：{conclusion}"
            )
            self._record(
                "evaluate_ab_test", "success",
                f"两组差异{'显著' if significant else '不显著'}（p={t_p:.4f}）",
                input_params={
                    "control_n": control.size, "treatment_n": treatment.size,
                },
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            return report
        except Exception as e:
            self._record(
                "evaluate_ab_test", "failed", "A/B 测试检验失败",
                error=str(e), duration_ms=(time.perf_counter() - started) * 1000,
            )
            return f"A/B 测试检验失败（已优雅降级）: {str(e)}"
