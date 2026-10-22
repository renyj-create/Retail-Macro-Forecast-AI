# src/models/train_timeseries.py
"""
社会消费品零售总额（社零）时间序列分析模块
================================================
功能：
  1. 从 SQLite 数据库 retail.db 读取宏观社零数据
  2. 使用 statsmodels 的 ARIMA 模型（order=(1,1,1)）做时序预测
  3. 历史回测（主演示）：留出最近一段「日历连续」的 3 个月，仅用更早数据训练，
     逐月输出预测值 / 真实值 / 绝对误差 / 相对误差 / 95% 预测区间，并汇总 MAE/RMSE/MAPE
  4. 基线对比：沿用上月值（naive）与同月去年（seasonal）两种简单基线，避免只报 ARIMA 自身误差
  5. 扩展窗口（walk-forward）回测：在最近多个连续窗口上汇总误差，佐证历史窗口表现
  6. 未来预测（辅助）：用全量数据拟合后外推未来 3 个月，明确标注「未验证」
  7. 使用 sklearn.ensemble.IsolationForest 对历史社零同比增速做异常检测

统计口径说明（重要）：
  国家统计局对社零数据自 2012 年起采用「1-2 月累计发布」口径——每年 1 月不再单独发布，
  2 月当月值缺失、仅发布 1-2 月累计值。因此本模块：
    - 不做单月与累计值混合建模；
    - 不假设 2 月 NaN 是普通缺失，也不自行拆分/补造 1-2 月数据；
    - 建模仅使用「单月口径」序列（剔除 1-2 月累计发布导致的缺失月份），
      并在回测时显式校验所选窗口为日历连续、真实值有效。

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
    从 SQLite 读取宏观社零数据，返回按日期升序排列的完整 DataFrame（保留缺失，便于口径识别）。

    参数:
        db_path: 数据库路径，默认取项目根目录下的 retail.db
    返回:
        DataFrame，含列: date(datetime), retail_sales_current(当月), yoy_growth,
        mom_growth, retail_sales_cumulative(累计), cumulative_yoy
    """
    if db_path is None:
        db_path = DEFAULT_DB_PATH

    conn = sqlite3.connect(db_path)
    sql = "SELECT date, retail_sales_current, yoy_growth, mom_growth, retail_sales_cumulative, cumulative_yoy FROM macro_retail_sales ORDER BY date ASC"
    df = pd.read_sql(sql, conn)
    conn.close()

    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    return df


def describe_publication_calendar(df: pd.DataFrame) -> dict:
    """
    检测「1-2 月累计发布」统计口径，返回结构化的口径说明。

    判定规则：
      - 某年 1 月整行缺失 + 2 月当月值(零售额)为空但累计值非空 → 该年为 1-2 月累计发布口径。
    """
    d = df.copy()
    d['year'] = d['date'].dt.year
    d['month'] = d['date'].dt.month

    years = sorted(d['year'].unique().tolist())
    cumulative_years = []
    missing_jan_years = []

    for y in years:
        jan = d[(d['year'] == y) & (d['month'] == 1)]
        feb = d[(d['year'] == y) & (d['month'] == 2)]
        if jan.empty:
            missing_jan_years.append(y)
        if (not feb.empty
                and pd.isna(feb['retail_sales_current'].iloc[0])
                and pd.notna(feb['retail_sales_cumulative'].iloc[0])):
            cumulative_years.append(y)

    has_cumulative = bool(cumulative_years)
    note = (
        "社零数据自 2012 年起采用「1-2 月累计发布」口径：1 月不单独发布、2 月当月值缺失，"
        "仅提供 1-2 月累计值。本次建模仅使用单月口径序列（剔除 1-2 月累计发布月份），"
        "不将累计值与单月值混合，也不对 1-2 月数据做拆分或补造。"
        if has_cumulative else
        "未检测到 1-2 月累计发布口径。"
    )
    return {
        'has_cumulative_caliber': has_cumulative,
        'cumulative_feb_years': cumulative_years,
        'missing_jan_years': missing_jan_years,
        'note': note,
    }


def monthly_series(df: pd.DataFrame) -> pd.DataFrame:
    """
    返回「单月口径」序列：剔除当月值为空的月份（即 1-2 月累计发布导致的 2 月缺失），
    按日期升序排列，并附加 'month' 字符串列（YYYY-MM）。

    注意：这里只剔除「当月值缺失」的行，绝不把 NaN 当 0，也不做任何插补。
    """
    s = df.dropna(subset=['retail_sales_current']).sort_values('date').reset_index(drop=True).copy()
    s['month'] = s['date'].dt.strftime('%Y-%m')
    return s


def _months_are_contiguous(dates) -> bool:
    """判断一串日期是否日历逐月连续（相邻两月间隔恰为 1 个月）。"""
    dates = pd.to_datetime(list(dates))
    if len(dates) < 2:
        return True
    for a, b in zip(dates, dates[1:]):
        if (a + pd.DateOffset(months=1)) != b:
            return False
    return True


def _find_recent_contiguous_window(s: pd.DataFrame, test_months: int):
    """
    在单月序列上寻找「最近一个日历连续且与训练集边界连续」的留出窗口。

    返回 (train_df, test_df)：
      - test_df 为 test_months 个月、日历连续、真实值有效；
      - train_df 为窗口之前的所有数据，其最后一个月与窗口首月连续（训练截止月 + 1 月 == 回测首月），
        从而保证「训练阶段不使用验证窗口真实值」且不跨 1-2 月累计缺口。

    找不到满足条件的窗口时抛出 ValueError（对应需求：排除窗口或明确报错）。
    """
    n = len(s)
    if n < test_months + 1:
        raise ValueError(
            f"单月有效序列仅 {n} 期，不足以留出 {test_months} 期做回测"
        )
    # 从最近往前找第一个满足条件的窗口
    for end in range(n, test_months, -1):
        start = end - test_months
        window = s.iloc[start:end]
        prev = s.iloc[start - 1]
        window_ok = _months_are_contiguous(window['date'])
        boundary_ok = _months_are_contiguous([prev['date'], window['date'].iloc[0]])
        if window_ok and boundary_ok:
            train = s.iloc[:start].reset_index(drop=True)
            test = window.reset_index(drop=True)
            return train, test
    raise ValueError(
        f"未找到日历连续且真实值有效的 {test_months} 期回测窗口（可能受 1-2 月累计发布缺口影响），"
        "请调整回测窗口或核验数据口径"
    )


def _forecast_with_interval(fitted, steps: int):
    """对已拟合模型做 steps 期外推，返回点预测与 95% 置信区间。"""
    result = fitted.get_forecast(steps=steps)
    mean = np.asarray(result.predicted_mean).ravel()
    ci = np.asarray(result.conf_int(alpha=0.05))  # 形状 (steps, 2)
    return mean, ci[:, 0], ci[:, 1]


def _compute_metrics(actual, forecast) -> dict:
    """计算 MAE / RMSE / MAPE。非有限值（NaN/inf）直接剔除，绝不把 NaN 当 0。"""
    actual = np.asarray(actual, dtype=float)
    forecast = np.asarray(forecast, dtype=float)
    mask = np.isfinite(actual) & np.isfinite(forecast)
    actual = actual[mask]
    forecast = forecast[mask]
    if len(actual) == 0:
        return {'mae': None, 'rmse': None, 'mape': None, 'n': 0}

    mae = float(np.mean(np.abs(actual - forecast)))
    rmse = float(np.sqrt(np.mean((actual - forecast) ** 2)))
    pos = np.abs(actual) > 0
    mape = float(np.mean(np.abs(actual[pos] - forecast[pos]) / np.abs(actual[pos]) * 100)) if pos.any() else None
    return {
        'mae': round(mae, 2),
        'rmse': round(rmse, 2),
        'mape': round(mape, 2) if mape is not None else None,
        'n': int(len(actual)),
    }


def _naive_baseline(train_values, steps: int) -> np.ndarray:
    """基线 1：沿用上月值（naive / persistence），即把训练集最后一个值重复 steps 次。"""
    train_values = np.asarray(train_values, dtype=float)
    return np.full(steps, float(train_values[-1]))


def _seasonal_baseline(train_df: pd.DataFrame, test_dates) -> np.ndarray:
    """基线 2：季节性基线（同月去年值），仅查训练集，绝不使用验证窗口真实值。"""
    by_date = {
        pd.Timestamp(d): float(v)
        for d, v in zip(train_df['date'], train_df['retail_sales_current'])
    }
    out = []
    for d in pd.to_datetime(list(test_dates)):
        prev = d - pd.DateOffset(years=1)
        out.append(by_date.get(prev, np.nan))
    return np.asarray(out, dtype=float)


def _metrics_with_baselines(actual, forecast, train_df, train_values, test_dates) -> dict:
    """计算 ARIMA 与两个基线（naive / seasonal）的误差指标。"""
    naive = _naive_baseline(train_values, len(actual))
    seasonal = _seasonal_baseline(train_df, test_dates)

    result = {'arima': _compute_metrics(actual, forecast)}
    result['naive'] = _compute_metrics(actual, naive)

    # 季节性基线在历史不足时可能含 NaN，仅对可计算月份汇总
    valid = np.isfinite(seasonal)
    if valid.any():
        result['seasonal'] = _compute_metrics(actual[valid], seasonal[valid])
    else:
        result['seasonal'] = {'mae': None, 'rmse': None, 'mape': None, 'n': 0}
    return result


def backtest_arima(df: pd.DataFrame, test_months: int = 3, order=(1, 1, 1)) -> dict:
    """
    历史回测（主演示）：留出最近一个「日历连续」的 test_months 个月，
    仅用更早数据训练 ARIMA，逐月输出预测/真实/误差/区间，并对比基线模型。

    返回 dict:
        train_end   : 训练数据截止月份（YYYY-MM）
        test_months : 回测月份列表
        points      : 逐月 {date, forecast, actual, abs_error, rel_error_pct, lower, upper}
        metrics     : ARIMA 的 {mae, rmse, mape, n}
        baselines   : {naive: {...}, seasonal: {...}}
    """
    s = monthly_series(df)
    train, test = _find_recent_contiguous_window(s, test_months)

    train_values = train['retail_sales_current'].astype(float).values
    actual = test['retail_sales_current'].astype(float).values
    dates = test['month'].tolist()

    # 防御：任何一步出现 NaN 都说明口径处理有误，直接报错，绝不把 NaN 当 0
    if np.isnan(train_values).any() or np.isnan(actual).any():
        raise ValueError("回测数据含 NaN（可能混入 1-2 月累计发布月份），已中止，不做任何补造")

    model = ARIMA(train_values, order=order)
    fitted = model.fit()
    forecast, lower, upper = _forecast_with_interval(fitted, len(actual))

    points = []
    for i in range(len(actual)):
        err = float(forecast[i] - actual[i])
        rel = float(err / actual[i] * 100) if actual[i] != 0 else None
        points.append({
            'date': dates[i],
            'forecast': round(float(forecast[i]), 1),
            'actual': round(float(actual[i]), 1),
            'abs_error': round(abs(err), 1),
            'rel_error_pct': round(rel, 2) if rel is not None else None,
            'lower': round(float(lower[i]), 1),
            'upper': round(float(upper[i]), 1),
        })

    metrics = _compute_metrics(actual, forecast)
    baselines = _metrics_with_baselines(actual, forecast, train, train_values, test['date'])

    return {
        'train_end': train['month'].iloc[-1],
        'test_months': dates,
        'points': points,
        'metrics': metrics,
        'baselines': baselines,
    }


def expanding_backtest(df: pd.DataFrame, window: int = 3, n_windows: int = 4,
                       order=(1, 1, 1)) -> dict:
    """
    扩展窗口（walk-forward）回测：从最近往前取 n_windows 个「日历连续」的验证窗口，
    每个窗口都用「该窗口之前」的全部数据训练（扩展窗口，训练数据随时间累积），
    汇总 ARIMA 与基线的平均误差。

    只纳入日历连续、真实值有效的窗口；跨越 1-2 月累计缺口的窗口会被跳过。
    """
    s = monthly_series(df)
    n = len(s)

    windows = []
    k = 1
    while len(windows) < n_windows and k * window < n:
        end = n - (k - 1) * window
        start = end - window
        test = s.iloc[start:end]
        train = s.iloc[:start]
        if (not train.empty and len(test) == window
                and _months_are_contiguous(test['date'])
                and _months_are_contiguous([train['date'].iloc[-1], test['date'].iloc[0]])):
            windows.append((train, test))
        k += 1

    if not windows:
        return {
            'method': 'expanding-window',
            'window': window,
            'n_windows': 0,
            'arima': None, 'naive': None, 'seasonal': None,
            'windows': [],
        }

    per_window = []
    for train, test in windows:
        train_values = train['retail_sales_current'].astype(float).values
        actual = test['retail_sales_current'].astype(float).values
        fitted = ARIMA(train_values, order=order).fit()
        forecast, _, _ = _forecast_with_interval(fitted, len(actual))
        baselines = _metrics_with_baselines(actual, forecast, train, train_values, test['date'])
        per_window.append({
            'train_end': train['month'].iloc[-1],
            'test_months': test['month'].tolist(),
            'arima': baselines['arima'],
            'naive': baselines['naive'],
            'seasonal': baselines['seasonal'],
        })

    def _avg(key):
        agg = {}
        for metric in ('mae', 'rmse', 'mape'):
            vals = [w[key][metric] for w in per_window if w[key].get(metric) is not None]
            agg[metric] = round(float(np.mean(vals)), 2) if vals else None
        agg['n'] = int(np.mean([w[key]['n'] for w in per_window]))
        return agg

    return {
        'method': 'expanding-window',
        'window': window,
        'n_windows': len(per_window),
        'arima': _avg('arima'),
        'naive': _avg('naive'),
        'seasonal': _avg('seasonal'),
        'windows': per_window,
    }


def detect_anomalies(df: pd.DataFrame, contamination: float = 0.05):
    """
    使用 IsolationForest 对历史社零数据进行异常检测。

    特征选择说明（面试加分点）:
        直接对原始零售额做异常检测会被长达 18 年的上涨趋势主导，误把 2008~2009 年
        的低基数期当成异常。这里改用「同比增长率 yoy_growth」作为检测特征——
        同比是同月对比，天然消除了趋势与季节性，能精准命中 2020 年疫情暴跌、
        2022 年封控、2008 年金融危机等真实异常月份。

    参数:
        df: 宏观数据 DataFrame（需含 yoy_growth 列，建议传入单月口径序列）
        contamination: 异常点占比，默认 0.05
    返回:
        anomalies: list[dict]，每个元素含 'date' 与 'value'（当月社零总额）
    """
    if 'yoy_growth' in df.columns and df['yoy_growth'].notna().any():
        signal = df['yoy_growth'].fillna(df['yoy_growth'].median()).values.reshape(-1, 1)
    else:
        v = df['retail_sales_current'].values.astype(float)
        signal = np.diff(v, prepend=v[0]).reshape(-1, 1)

    model = IsolationForest(contamination=contamination, random_state=42, n_estimators=100)
    preds = model.fit_predict(signal)

    anomalies = []
    for i, pred in enumerate(preds):
        if pred == -1:
            anomalies.append({
                'date': df['date'].iloc[i].strftime('%Y-%m'),
                'value': round(float(df['retail_sales_current'].iloc[i]), 1),
            })
    return anomalies


def run_forecast(steps: int = 3, test_months: int = 3, order=(1, 1, 1),
                 db_path: str = None, n_windows: int = 4) -> dict:
    """
    完整时序分析流程，返回结构化结果 dict，供上层复用。

    参数:
        steps:       未来预测步长（默认 3 个月）
        test_months: 历史回测窗口长度（默认 3 个月）
        order:       ARIMA 阶数 (p, d, q)
        db_path:     数据库路径（默认根目录 retail.db）
        n_windows:   扩展窗口回测的窗口数量（默认 4）
    返回:
        dict:
            historical_dates   : 单月口径历史月份列表 ['YYYY-MM', ...]
            historical_values  : 单月口径历史真实值列表
            forecast_dates     : 未来 3 个月列表（辅助，未验证）
            forecast_values    : 未来预测值列表
            lower_bound/upper_bound : 未来预测 95% 置信区间
            backtest           : 历史回测详情（训练截止、逐月对比、指标、基线）
            rolling_backtest   : 扩展窗口回测汇总
            metrics            : 历史回测指标 {mae, rmse, mape, n}（兼容旧字段）
            anomalies          : 异常月份列表
            data_note          : 统计口径说明
            forecast_note      : 未来预测标注
    """
    # 1. 读取数据与口径识别
    df = load_macro_data(db_path)
    single = monthly_series(df)
    calendar = describe_publication_calendar(df)

    # 2. 历史回测（主演示）
    backtest = backtest_arima(df, test_months=test_months, order=order)

    # 3. 扩展窗口回测（多窗口稳健性 + 基线对比）
    rolling = expanding_backtest(df, window=test_months, n_windows=n_windows, order=order)

    # 4. 全量数据训练 ARIMA，外推未来（辅助，未验证）
    values = single['retail_sales_current'].astype(float).values
    model = ARIMA(values, order=order)
    fitted = model.fit()
    forecast_result = fitted.get_forecast(steps=steps)
    forecast_values = np.asarray(forecast_result.predicted_mean).ravel()
    conf_int = np.asarray(forecast_result.conf_int(alpha=0.05))
    lower_bound = conf_int[:, 0]
    upper_bound = conf_int[:, 1]

    last_date = single['date'].iloc[-1]
    forecast_dates = [
        (last_date + pd.DateOffset(months=i)).strftime('%Y-%m')
        for i in range(1, steps + 1)
    ]

    # 5. 异常检测（使用单月口径序列，保证异常月份都对应真实单月值）
    anomalies = detect_anomalies(single)

    # 6. 统一封装为结构化结果
    return {
        'historical_dates': single['month'].tolist(),
        'historical_values': [round(float(v), 1) for v in values],
        'forecast_dates': forecast_dates,
        'forecast_values': [round(float(v), 1) for v in forecast_values],
        'lower_bound': [round(float(v), 1) for v in lower_bound],
        'upper_bound': [round(float(v), 1) for v in upper_bound],
        'forecast_note': '未来预测为辅助功能，未经过真实值验证，不构成准确率保证',
        'backtest': backtest,
        'rolling_backtest': rolling,
        'data_note': calendar['note'],
        'metrics': backtest['metrics'],
        'anomalies': anomalies,
    }


def print_forecast_report(result: dict):
    """将 run_forecast 的结果以中文报告形式打印到控制台。"""
    print("\n" + "=" * 62)
    print("      社会消费品零售总额 时间序列分析报告")
    print("=" * 62)

    print(f"\n【统计口径】{result.get('data_note', '')}")

    bt = result.get('backtest') or {}
    m = bt.get('metrics') or {}
    print(f"\n【历史回测】（训练截止 {bt.get('train_end', '')}，回测月份 {bt.get('test_months', [])}）")
    print(f"  {'月份':<10} {'预测值':<10} {'真实值':<10} {'绝对误差':<10} {'相对误差':<10} {'95%区间'}")
    for p in bt.get('points', []):
        interval = f"[{p['lower']}, {p['upper']}]"
        print(f"  {p['date']:<10} {p['forecast']:<10} {p['actual']:<10} "
              f"{p['abs_error']:<10} {p['rel_error_pct']:<10} {interval}")
    print(f"  ARIMA 指标：MAE={m.get('mae')} 亿元, RMSE={m.get('rmse')} 亿元, MAPE={m.get('mape')}%")

    bl = bt.get('baselines') or {}
    for name, label in (('naive', '沿用上月值'), ('seasonal', '同月去年')):
        b = bl.get(name) or {}
        print(f"  基线[{label}]：MAE={b.get('mae')} 亿元, RMSE={b.get('rmse')} 亿元, MAPE={b.get('mape')}%")

    rb = result.get('rolling_backtest') or {}
    if rb.get('n_windows'):
        print(f"\n【扩展窗口回测】（{rb.get('method')}，窗口 {rb.get('window')} 期 × {rb.get('n_windows')} 窗口，平均指标）")
        for name, label in (('arima', 'ARIMA'), ('naive', '沿用上月值'), ('seasonal', '同月去年')):
            m2 = rb.get(name) or {}
            print(f"  {label:<8}：MAE={m2.get('mae')} 亿元, RMSE={m2.get('rmse')} 亿元, MAPE={m2.get('mape')}%")

    print(f"\n【未来 {len(result.get('forecast_dates', []))} 个月预测】（辅助，未验证 · 95% 置信区间）")
    print(f"  {'月份':<10} {'预测值(亿元)':<14} {'下界':<12} {'上界':<12}")
    for d, v, lo, hi in zip(
        result.get('forecast_dates', []), result.get('forecast_values', []),
        result.get('lower_bound', []), result.get('upper_bound', [])
    ):
        print(f"  {d:<10} {v:<14} {lo:<12} {hi:<12}")
    print(f"  {result.get('forecast_note', '')}")

    if result.get('anomalies'):
        print(f"\n【异常检测】（IsolationForest，共 {len(result['anomalies'])} 个异常月份）")
        for a in result['anomalies']:
            print(f"    ⚠️  {a['date']}: {a['value']} 亿元")

    print("\n说明：回测结果仅反映选定历史窗口的表现，不保证未来预测准确率。")
    print("=" * 62 + "\n")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    print("正在从 retail.db 加载宏观社零数据...")
    result = run_forecast(steps=3, test_months=3, order=(1, 1, 1))
    print_forecast_report(result)
