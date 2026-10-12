# src/agents/tools.py
import os
import sys
import sqlite3
import pandas as pd
import joblib

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 🌟 将项目根目录加入搜索路径，使本文件可被独立导入（无需依赖 graph_workflow 的 sys.path 处理）
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)


class MCPToolServer:
    """
    模拟 MCP Server，统一封装所有外部工具
    """

    def __init__(self):
        self.db_path = os.path.join(BASE_DIR, 'retail.db')
        self.model_path = os.path.join(BASE_DIR, 'src', 'models', 'saved_models', 'lgbm_churn_model.pkl')
        # 🌟 执行明细元数据：供 Agent 报告的可解释性展示使用
        self.last_sql = ""
        self.last_data_count = 0
        self.last_kb_fragments = ""

    def query_macro_sqlite(self) -> str:
        """MCP Tool: 查询宏观社零数据库"""
        try:
            conn = sqlite3.connect(self.db_path)
            sql = "SELECT date, retail_sales_current, yoy_growth FROM macro_retail_sales ORDER BY date DESC LIMIT 3"
            df = pd.read_sql(sql, conn)
            conn.close()

            # 🌟 记录执行明细：原始 SQL 与返回数据量（供前端「执行明细」面板展示）
            self.last_sql = sql
            self.last_data_count = len(df)

            result = "最新宏观社零数据：\n"
            for _, row in df.iterrows():
                result += f"- {row['date'].split()[0]}: 当月总额 {row['retail_sales_current']} 亿元, 同比增长 {row['yoy_growth']}%\n"
            return result
        except Exception as e:
            return f"宏观数据查询失败: {str(e)}"

    def predict_churn_lightgbm(self, recency_days=60, frequency=1, monetary=100.0, avg_amount=100.0, age=30) -> str:
        """MCP Tool: 调用 LightGBM 模型预测流失概率"""
        try:
            model = joblib.load(self.model_path)
            feature_cols = ['recency_days', 'frequency', 'monetary', 'avg_amount', 'age', 'city_tier_二线',
                            'city_tier_三线']
            # 模拟二线城市、未流失画像
            X_input = pd.DataFrame([[recency_days, frequency, monetary, avg_amount, age, 1, 0]], columns=feature_cols)
            prob = model.predict_proba(X_input)[0][1]
            return f"流失预测结果：基于当前特征({recency_days}天未购买，购买频次{frequency}次)，模型预测该用户流失概率为 {prob:.2%}。"
        except Exception as e:
            return f"模型预测失败: {str(e)}"

    def rag_search(self, query: str, top_k: int = 2) -> str:
        """
        MCP Tool: RAG 检索企业知识库（基于 ChromaDB 本地向量检索）

        流程:
          1. 读取本地 docs/policy.txt（政策/研报原文）
          2. 按空行分块，使用 TF-IDF 向量化（离线、无外部模型依赖）
          3. 写入本地持久化 ChromaDB（PersistentClient，余弦相似度）
          4. 对 query 做同空间向量化并检索 top_k 最相似片段
          5. 返回真实原文片段；无匹配则明确返回「未在知识库中找到相关研报」
        """
        try:
            import chromadb
            from sklearn.feature_extraction.text import TfidfVectorizer

            # 1. 读取本地知识库原文，文件缺失则视为「无知识库」
            policy_path = os.path.join(BASE_DIR, 'docs', 'policy.txt')
            if not os.path.exists(policy_path):
                self.last_kb_fragments = ""
                return "未在知识库中找到相关研报"

            with open(policy_path, 'r', encoding='utf-8') as f:
                raw = f.read()

            # 2. 按空行分块，剔除空白块
            chunks = [c.strip() for c in raw.split('\n\n') if c.strip()]
            if not chunks:
                self.last_kb_fragments = ""
                return "未在知识库中找到相关研报"

            # 3. TF-IDF 向量化：以文档块为语料拟合，query 用同一向量器变换，保证同维度同空间
            #    中文无空格分隔，采用「字符级 n-gram」分词，无需引入 jieba 等额外依赖
            vectorizer = TfidfVectorizer(analyzer='char', ngram_range=(2, 3))
            chunk_vectors = vectorizer.fit_transform(chunks).toarray().tolist()
            query_vector = vectorizer.transform([query]).toarray().tolist()

            # 4. 本地持久化向量库（先删后建，避免语料/分词变化导致向量维度不匹配）
            chroma_path = os.path.join(BASE_DIR, 'chroma_db')
            client = chromadb.PersistentClient(path=chroma_path)
            try:
                client.delete_collection(name="policy_docs")
            except Exception:
                pass  # 集合不存在时忽略
            collection = client.create_collection(
                name="policy_docs",
                metadata={"hnsw:space": "cosine"},
            )
            collection.add(
                ids=[f"chunk_{i}" for i in range(len(chunks))],
                documents=chunks,
                embeddings=chunk_vectors,
            )

            # 5. 检索 top_k 最相似片段
            result = collection.query(
                query_embeddings=query_vector,
                n_results=min(top_k, len(chunks)),
                include=["documents", "distances"],
            )
            docs = result.get("documents", [[]])[0]
            distances = result.get("distances", [[]])[0]

            # 6. 过滤低相关结果：cosine 距离 >= 0.999 视为无交集（TF-IDF 向量非负，最大距离为 1.0）
            matched = [
                d for d, dist in zip(docs, distances)
                if d and dist is not None and dist < 0.999
            ]
            if not matched:
                self.last_kb_fragments = ""
                return "未在知识库中找到相关研报"

            fragments = "\n\n".join(matched)
            self.last_kb_fragments = fragments
            return "【企业知识库检索结果】\n" + fragments
        except Exception as e:
            # 优雅降级：向量库/依赖异常时返回可读错误，不阻断 Agent 主链路
            return f"知识库检索失败（已优雅降级）: {str(e)}"

    def forecast_timeseries(self) -> str:
        """
        MCP Tool: 社零总额时序预测（ARIMA + 异常检测）
        调用 src/models/train_timeseries.py 中的时序逻辑，
        返回未来 3 个月预测值、95% 置信区间，以及历史回测 MAPE。
        """
        try:
            # 延迟导入：statsmodels 仅在真正调用时才需要，避免影响工具服务启动
            from src.models.train_timeseries import run_forecast

            result = run_forecast(steps=3, test_months=3, order=(1, 1, 1))

            metrics = result['metrics']
            lines = [
                "===== 社零总额 ARIMA 时序预测报告 =====",
                f"未来 {len(result['forecast_dates'])} 个月预测（95% 置信区间）：",
            ]
            for d, v, lo, hi in zip(
                result['forecast_dates'], result['forecast_values'],
                result['lower_bound'], result['upper_bound']
            ):
                lines.append(f"  {d}: 预测 {v} 亿元，区间 [{lo}, {hi}]")

            lines.append("")
            lines.append(
                f"历史回测指标：MAE={metrics['mae']} 亿元, "
                f"RMSE={metrics['rmse']} 亿元, MAPE={metrics['mape']}%"
            )

            lines.append("")
            lines.append(f"异常检测：共标记 {len(result['anomalies'])} 个异常月份")
            for a in result['anomalies']:
                lines.append(f"  ⚠ {a['date']}: {a['value']} 亿元")
            return "\n".join(lines)
        except Exception as e:
            # 优雅降级：模型/依赖异常时返回可读的错误信息而非抛异常
            return f"时序预测失败（已优雅降级）: {str(e)}"

    def evaluate_ab_test(self, control_data, treatment_data) -> str:
        """
        MCP Tool: A/B 测试统计检验
        使用 scipy.stats 进行 Levene 方差齐性检验 + 独立样本 T 检验，
        根据方差是否齐性选择 Student's t-test 或 Welch's t-test，并计算增量提升 Uplift。

        参数:
            control_data:   对照组样本（list 或 numpy 数组）
            treatment_data: 实验组样本（list 或 numpy 数组）
        """
        try:
            import numpy as np
            from scipy import stats as sps

            control = np.asarray(control_data, dtype=float)
            treatment = np.asarray(treatment_data, dtype=float)

            # 样本量防御：过少样本无法进行可靠的统计检验
            if control.size < 2 or treatment.size < 2:
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

            # 预先拼装结论（避免在 f-string 表达式内跨行，兼容 Python 3.10）
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
            return report
        except Exception as e:
            # 优雅降级：统计计算失败时返回可读错误
            return f"A/B 测试检验失败（已优雅降级）: {str(e)}"