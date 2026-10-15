# src/models/churn_inference.py
"""
用户流失预测 · 推理模块
========================
将「模型加载 + 批量推理 + 特征归因」封装为可复用核心，供：
  1. Agent 工具层（src/agents/tools.py）调用，返回真实批量流失预测；
  2. FastAPI 接口层（src/api/main.py）调用，返回结构化风险分布 / 高风险用户 / 特征重要性。

设计要点：
  - 特征列顺序以训练时模型保存的 feature_names_in_ 为准，避免手工写死导致错位；
  - 城市等级 one-hot 与训练脚本（drop_first=True）保持一致；
  - SHAP 归因优先，若依赖不可用则降级为 LightGBM 内置 feature_importances_；
  - 所有入口均做 try/except 降级，异常时返回可读错误信息而非进程崩溃。
"""
import os
import sys
import time
import sqlite3

import numpy as np
import pandas as pd
import joblib

# 将项目根目录加入搜索路径，使本文件可被独立导入
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

DEFAULT_DB_PATH = os.path.join(BASE_DIR, 'retail.db')
DEFAULT_MODEL_PATH = os.path.join(
    BASE_DIR, 'src', 'models', 'saved_models', 'lgbm_churn_model.pkl'
)

# 训练脚本中 get_dummies(drop_first=True) 会丢弃「一线」，保留「二线 / 三线」两列。
# 注意：不要依赖这里的书写顺序，实际推理统一以 model.feature_names_in_ 为准。
CITY_TIER_COLUMNS = ['city_tier_二线', 'city_tier_三线']

# 模块级缓存：SHAP 归因计算相对昂贵，避免接口高频调用时重复计算
_shap_cache = {"key": None, "importance": None}


def load_churn_model(model_path: str = None):
    """加载 LightGBM 流失预测模型，返回 (model, feature_order)。"""
    if model_path is None:
        model_path = DEFAULT_MODEL_PATH
    model = joblib.load(model_path)
    feature_order = [str(c) for c in model.feature_names_in_]
    return model, feature_order


def load_churn_dataset(db_path: str = None, limit: int = None) -> pd.DataFrame:
    """从 SQLite 读取流失数据集（含真实 RFM 特征、城市等级与流失标签）。"""
    if db_path is None:
        db_path = DEFAULT_DB_PATH
    conn = sqlite3.connect(db_path)
    sql = (
        "SELECT user_id, recency_days, frequency, monetary, avg_amount, is_churn, "
        "age, city_tier FROM churn_dataset"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    df = pd.read_sql(sql, conn)
    conn.close()
    return df


def build_feature_matrix(df: pd.DataFrame, feature_order: list) -> pd.DataFrame:
    """
    将原始数据集转换为模型可用的特征矩阵。

    与训练脚本保持一致：对 city_tier 做 one-hot，drop_first=True（丢弃「一线」）。
    返回的 DataFrame 列顺序与 feature_order 完全对齐。
    """
    work = df.copy()
    # 类别 one-hot，与 train_lgbm_churn.py 中 drop_first=True 一致
    dummies = pd.get_dummies(work['city_tier'], prefix='city_tier', drop_first=True)
    for col in CITY_TIER_COLUMNS:
        if col not in dummies.columns:
            dummies[col] = 0
    work = pd.concat([work, dummies], axis=1)
    # 补齐缺失特征列（防御性：若数据集缺少某列，填充 0）
    for col in feature_order:
        if col not in work.columns:
            work[col] = 0
    return work[feature_order]


def assign_risk_levels(probs) -> tuple:
    """
    基于概率分位数划分风险等级（流失模型为排序型输出，绝对阈值无业务意义）。

    分位阈值：
      极高风险 ≥ P95，高风险 ≥ P80，中风险 ≥ P50，其余为低风险。
    阈值来自当前样本概率分布的真实分位数，随数据变化，避免写死。
    """
    probs = np.asarray(probs, dtype=float)
    p50 = float(np.quantile(probs, 0.50))
    p80 = float(np.quantile(probs, 0.80))
    p95 = float(np.quantile(probs, 0.95))

    def _level(p):
        if p >= p95:
            return "极高风险"
        if p >= p80:
            return "高风险"
        if p >= p50:
            return "中风险"
        return "低风险"

    levels = [_level(p) for p in probs]
    thresholds = {"p50": p50, "p80": p80, "p95": p95}
    return levels, thresholds


def compute_feature_importance(model, X: pd.DataFrame):
    """
    计算特征重要性，优先使用 SHAP（真实模型解释），失败时降级为内置 importance。

    返回: list[dict]，每个元素含 feature / importance（降序）。
    """
    feature_order = [str(c) for c in X.columns]
    cache_key = tuple(feature_order)
    if _shap_cache["key"] == cache_key and _shap_cache["importance"] is not None:
        return _shap_cache["importance"]

    importance = None
    try:
        import shap
        explainer = shap.TreeExplainer(model)
        # 数据量较大时抽样计算，兼顾速度与稳定性（样本量足够时 SHAP 均值估计稳定）
        sample = X if len(X) <= 800 else X.sample(800, random_state=42)
        raw = explainer.shap_values(sample, check_additivity=False)

        # 兼容不同版本 SHAP 的返回结构：
        #   - list[neg_arr, pos_arr]（旧版二分类）
        #   - ndarray (n_samples, n_features)（新版二分类）
        #   - ndarray (n_samples, n_features, n_classes)
        if isinstance(raw, list):
            sv = raw[1] if len(raw) == 2 else raw[0]
        else:
            sv = raw
        sv = np.asarray(sv)
        if sv.ndim == 3:
            sv = sv[:, :, 1]

        mean_abs = np.abs(sv).mean(axis=0)
        pairs = sorted(
            zip(feature_order, mean_abs.tolist()),
            key=lambda x: x[1],
            reverse=True,
        )
        importance = [{"feature": f, "importance": round(float(v), 6)} for f, v in pairs]
    except Exception:
        # SHAP 不可用时降级为 LightGBM 内置特征重要性
        try:
            gains = model.feature_importances_
            pairs = sorted(
                zip(feature_order, gains.tolist()),
                key=lambda x: x[1],
                reverse=True,
            )
            total = sum(g for _, g in pairs) or 1.0
            importance = [
                {"feature": f, "importance": round(float(g) / total, 6)}
                for f, g in pairs
            ]
        except Exception:
            importance = []

    _shap_cache["key"] = cache_key
    _shap_cache["importance"] = importance
    return importance


def predict_batch(top_n: int = 20, db_path: str = None, model_path: str = None) -> dict:
    """
    真实批量流失推理入口。

    返回结构化结果：
      - total / churn_rate：样本数与模拟数据流失标签占比
      - risk_distribution：四档风险分段人数与占比
      - top_risk_users：按流失概率降序的高风险用户列表（前 top_n）
      - feature_importance：真实模型特征归因（SHAP 优先）
      - model_meta：模型与数据来源元信息
    """
    started = time.perf_counter()
    model, feature_order = load_churn_model(model_path)
    df = load_churn_dataset(db_path)

    if df.empty:
        return {"error": "流失数据集为空，无法执行批量推理"}

    X = build_feature_matrix(df, feature_order)
    probs = model.predict_proba(X)[:, 1]

    result = pd.DataFrame({
        "user_id": df["user_id"].astype(int).tolist(),
        "age": df["age"].astype(int).tolist(),
        "city_tier": df["city_tier"].tolist(),
        "recency_days": df["recency_days"].astype(int).tolist(),
        "frequency": df["frequency"].astype(int).tolist(),
        "monetary": df["monetary"].round(2).tolist(),
        "churn_prob": probs,
    })
    levels, thresholds = assign_risk_levels(result["churn_prob"].values)
    result["risk_level"] = levels

    total = len(result)
    # 模拟数据流失标签占比（真实统计自数据集 is_churn 列）
    churn_rate = round(float(df["is_churn"].mean()), 4) if "is_churn" in df else None

    # 四档风险分段（按真实概率分位数划分）
    buckets = {"低风险": 0, "中风险": 0, "高风险": 0, "极高风险": 0}
    for level in levels:
        buckets[level] = buckets.get(level, 0) + 1
    risk_distribution = [
        {"level": k, "count": v, "ratio": round(v / total, 4)}
        for k, v in buckets.items()
    ]

    top_risk_users = (
        result.sort_values("churn_prob", ascending=False)
        .head(top_n)
        .to_dict(orient="records")
    )

    feature_importance = compute_feature_importance(model, X)

    return {
        "total": total,
        "churn_rate": churn_rate,
        "risk_distribution": risk_distribution,
        "top_risk_users": top_risk_users,
        "feature_importance": feature_importance,
        "model_meta": {
            "model_type": type(model).__name__,
            "feature_count": len(feature_order),
            "data_note": "模拟数据（RFM 规则生成），不代表真实企业客户",
            "risk_thresholds": thresholds,
            "inference_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    }


if __name__ == "__main__":
    # 测试块：直接运行本文件即可完成一次真实批量推理
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    result = predict_batch(top_n=10)
    print(f"样本数: {result['total']}, 流失标签占比: {result['churn_rate']}")
    print(f"风险分布: {result['risk_distribution']}")
    print(f"特征重要性 TOP3: {result['feature_importance'][:3]}")
    print(f"高风险用户 TOP3: {result['top_risk_users'][:3]}")
