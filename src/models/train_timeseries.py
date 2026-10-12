# src/models/train_timeseries.py
"""
社会消费品零售总额（社零）时间序列分析模块
================================================
功能：
  1. 从 SQLite 数据库 retail.db 读取宏观社零数据
  2. 使用 statsmodels 的 ARIMA 模型（order=(1,1,1)）预测未来 3 个月社零总额
  3. 计算 95% 置信区间（上下界）
  4. 历史回测：用最后 3 个月真实值评估模型，输出 MAE / RMSE / MAPE
  5. 使用 sklearn.ensemble.IsolationForest 对历史社零数据进行异常检测

说明：
  本模块被设计为「可复用核心」，run_forecast() 返回结构化 dict，
  同时供 MCP 工具（src/agents/tools.py）和 FastAPI 接口（src/api/main.py）调用。
"""

import os
import sys
import sqlite3
import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA
from sklearn.ensemble import IsolationForest

# 忽略 statsmodels 在拟合过程中的收敛类告警，保持输出整洁
warnings.filterwarnings("ignore")

# 🌟 核心：获取项目根目录，确保无论从哪里运行都能定位到 retail.db
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, 'retail.db')


def load_macro_data(db_path: str = None) -> pd.DataFrame:
    """
    从 SQLite 读取宏观社零数据，返回按日期升序排列的 DataFrame。

    参数:
        db_path: 数据库路径，默认取项目根目录下的 retail.db
    返回:
        DataFrame，含列: date(datetime), retail_sales_current, yoy_growth
    """
    if db_path is None:
        db_path = DEFAULT_DB_PATH

    conn = sqlite3.connect(db_path)
    # 只取时序建模需要的核心字段，按日期升序排列
    sql = "SELECT date, retail_sales_current, yoy_growth FROM macro_retail_sales ORDER BY date ASC"
    df = pd.read_sql(sql, conn)
    conn.close()

    df['date'] = pd.to_datetime(df['date'])
    # 剔除目标值为空的行，保证时序连续性
    df = df.dropna(subset=['retail_sales_current']).reset_index(drop=True)
    return df


def backtest_arima(df: pd.DataFrame, test_months: int = 3, order=(1, 1, 1)):
    """
    历史回测：用「前 N 个月」训练 ARIMA，预测「最后 N 个月」，与真实值对比。

    参数:
        df:         按日期升序排列的宏观数据 DataFrame
        test_months: 回测窗口长度（默认 3 个月）
        order:       ARIMA 阶数 (p, d, q)
    返回:
        metrics: dict，包含 MAE / RMSE / MAPE
        forecast: 回测期间的预测值数组
        actual:   回测期间的真实值数组
    """
    values = df['retail_sales_current'].values.astype(float)

    # 切分训练集与测试集：前 len-train_months 个月用于训练，最后 test_months 个月用于验证
    train = values[:-test_months]
    actual = values[-test_months:]

    # 在截断后的训练集上重新拟合 ARIMA，模拟「历史时点只能看到历史数据」的真实场景
    model = ARIMA(train, order=order)
    fitted = model.fit()
    forecast = fitted.forecast(steps=test_months)

    # 计算回归类指标
    mae = float(np.mean(np.abs(actual - forecast)))
    rmse = float(np.sqrt(np.mean((actual - forecast) ** 2)))
    # MAPE：分母加极小值防止除零（社零额本身不会为 0，这里仅做防御）
    mape = float(np.mean(np.abs((actual - forecast) / (np.abs(actual) + 1e-9))) * 100)

    metrics = {
        'mae': round(mae, 2),
        'rmse': round(rmse, 2),
        'mape': round(mape, 2),
    }
    return metrics, forecast, actual


def detect_anomalies(df: pd.DataFrame, contamination: float = 0.05):
    """
    使用 IsolationForest 对历史社零数据进行异常检测。

    特征选择说明（面试加分点）:
        直接对原始零售额做异常检测会被长达 18 年的上涨趋势主导，误把 2008~2009 年
        的低基数期当成异常。这里改用「同比增长率 yoy_growth」作为检测特征——
        同比是同月对比，天然消除了趋势与季节性，能精准命中 2020 年疫情暴跌、
        2022 年封控、2008 年金融危机等真实异常月份。

    原理:
        IsolationForest 通过随机切割特征空间构建隔离树，「离群点」因为容易被孤立，
        平均路径更短，从而被判定为异常（返回 -1）。

    参数:
        df: 宏观数据 DataFrame（需含 yoy_growth 列）
        contamination: 异常点占比，默认 0.05（约 5% 的月份被判为异常）
    返回:
        anomalies: list[dict]，每个元素含 'date' 与 'value'（当月社零总额）
    """
    # 优先使用「同比增速」作为检测特征（去趋势 + 去季节性）
    if 'yoy_growth' in df.columns and df['yoy_growth'].notna().any():
        signal = df['yoy_growth'].fillna(df['yoy_growth'].median()).values.reshape(-1, 1)
    else:
        # 兜底：没有同比列时，用一阶差分（环比变化）近似去趋势，prepend 保持长度对齐
        v = df['retail_sales_current'].values.astype(float)
        signal = np.diff(v, prepend=v[0]).reshape(-1, 1)

    # IsolationForest 需要二维特征矩阵
    model = IsolationForest(contamination=contamination, random_state=42, n_estimators=100)
    # 预测结果：1 = 正常，-1 = 异常
    preds = model.fit_predict(signal)

    anomalies = []
    for i, pred in enumerate(preds):
        if pred == -1:
            anomalies.append({
                'date': df['date'].iloc[i].strftime('%Y-%m'),
                'value': round(float(df['retail_sales_current'].iloc[i]), 1),
            })
    return anomalies


def run_forecast(steps: int = 3, test_months: int = 3, order=(1, 1, 1), db_path: str = None) -> dict:
    """
    完整时序分析流程，返回结构化结果 dict，供上层复用。

    参数:
        steps:       未来预测步长（默认 3 个月）
        test_months: 回测窗口长度（默认 3 个月）
        order:       ARIMA 阶数 (p, d, q)
        db_path:     数据库路径（默认根目录 retail.db）
    返回:
        dict:
            historical_dates  : 历史月份列表 ['YYYY-MM', ...]
            historical_values : 历史真实值列表
            forecast_dates    : 未来 3 个月列表
            forecast_values   : 预测值列表
            lower_bound       : 95% 置信区间下界
            upper_bound       : 95% 置信区间上界
            metrics           : {'mae':, 'rmse':, 'mape':}
            anomalies         : 异常月份列表 [{'date':, 'value':}, ...]
    """
    # 1. 读取数据
    df = load_macro_data(db_path)
    values = df['retail_sales_current'].values.astype(float)

    # 2. 历史回测：评估模型在历史窗口上的精度
    metrics, _, _ = backtest_arima(df, test_months=test_months, order=order)

    # 3. 全量数据训练 ARIMA，预测未来
    model = ARIMA(values, order=order)
    fitted = model.fit()

    # get_forecast 同时返回点预测与置信区间（95% 对应 alpha=0.05）
    forecast_result = fitted.get_forecast(steps=steps)
    forecast_values = np.asarray(forecast_result.predicted_mean).ravel()
    conf_int = np.asarray(forecast_result.conf_int(alpha=0.05))  # 形状 (steps, 2)
    lower_bound = conf_int[:, 0]
    upper_bound = conf_int[:, 1]

    # 4. 生成未来日期（月份粒度）
    last_date = df['date'].iloc[-1]
    forecast_dates = [
        (last_date + pd.DateOffset(months=i)).strftime('%Y-%m')
        for i in range(1, steps + 1)
    ]

    # 5. 异常检测
    anomalies = detect_anomalies(df)

    # 6. 统一封装为结构化结果，数值保留 1 位小数，便于前端 ECharts 直接对接
    return {
        'historical_dates': df['date'].dt.strftime('%Y-%m').tolist(),
        'historical_values': [round(float(v), 1) for v in values],
        'forecast_dates': forecast_dates,
        'forecast_values': [round(float(v), 1) for v in forecast_values],
        'lower_bound': [round(float(v), 1) for v in lower_bound],
        'upper_bound': [round(float(v), 1) for v in upper_bound],
        'metrics': metrics,
        'anomalies': anomalies,
    }


def print_forecast_report(result: dict):
    """将 run_forecast 的结果以中文报告形式打印到控制台。"""
    print("\n" + "=" * 56)
    print("      社会消费品零售总额 时间序列分析报告")
    print("=" * 56)

    m = result['metrics']
    print(f"\n【历史回测指标】（用最后 {len(result['forecast_dates'])} 个月真实值评估）")
    print(f"  MAE  (平均绝对误差)      : {m['mae']} 亿元")
    print(f"  RMSE (均方根误差)        : {m['rmse']} 亿元")
    print(f"  MAPE (平均绝对百分比误差) : {m['mape']}%")

    print(f"\n【未来 {len(result['forecast_dates'])} 个月预测】（95% 置信区间）")
    print(f"  {'月份':<10} {'预测值(亿元)':<14} {'下界':<12} {'上界':<12}")
    for d, v, lo, hi in zip(
        result['forecast_dates'], result['forecast_values'],
        result['lower_bound'], result['upper_bound']
    ):
        print(f"  {d:<10} {v:<14} {lo:<12} {hi:<12}")

    print(f"\n【异常检测】（IsolationForest）")
    if result['anomalies']:
        print(f"  共标记 {len(result['anomalies'])} 个异常月份：")
        for a in result['anomalies']:
            print(f"    ⚠️  {a['date']}: {a['value']} 亿元")
    else:
        print("  未检测到明显异常月份。")

    # 附最新一期真实值作为参考
    latest_date = result['historical_dates'][-1]
    latest_value = result['historical_values'][-1]
    print(f"\n【数据参考】历史最新一期：{latest_date} = {latest_value} 亿元，共 {len(result['historical_dates'])} 个月度样本。")
    print("=" * 56 + "\n")


if __name__ == "__main__":
    # 🌟 测试块：直接运行本文件即可完成「训练 + 预测 + 回测 + 异常检测」全流程
    # Windows 控制台默认 GBK 编码，这里强制 UTF-8 输出，避免中文/特殊符号打印报错
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    print("正在从 retail.db 加载宏观社零数据...")
    result = run_forecast(steps=3, test_months=3, order=(1, 1, 1))
    print_forecast_report(result)
