# src/tests/test_timeseries.py
"""
时间序列回测单元测试：覆盖时间切分、缺失值（1-2 月累计口径）、预测窗口、
误差计算、数据泄漏防护与基线模型。

全部使用合成数据，不依赖真实 retail.db，确定性可复现。
"""
import os
import sys
import unittest

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from src.models.train_timeseries import (
    describe_publication_calendar,
    monthly_series,
    backtest_arima,
    expanding_backtest,
    _compute_metrics,
    _find_recent_contiguous_window,
    _naive_baseline,
    _seasonal_baseline,
    _months_are_contiguous,
)


def make_clean_df(start='2014-01-01', periods=36, base=30000.0):
    """生成无缺失、日历连续的月度单值序列（确定性）。"""
    dates = pd.date_range(start, periods=periods, freq='MS')
    values = base + np.arange(periods) * 200.0 + 1500.0 * np.sin(np.arange(periods) * 2 * np.pi / 12)
    return pd.DataFrame({
        'date': dates,
        'retail_sales_current': np.round(values, 1),
        'yoy_growth': np.round(2.0 + 0.1 * np.sin(np.arange(periods)), 2),
        'mom_growth': np.nan,
        'retail_sales_cumulative': np.round(np.cumsum(values), 1),
        'cumulative_yoy': 2.0,
    })


def make_cumulative_df(years=(2013, 2014, 2015, 2016)):
    """模拟 2012 年起「1-2 月累计发布」口径：1 月整行缺失、2 月当月值为 NaN。"""
    rows = []
    for y in years:
        for m in range(1, 13):
            if m == 1:
                continue  # 1 月不单独发布
            d = pd.Timestamp(f'{y}-{m:02d}-01')
            cur = np.nan if m == 2 else float((y - 2013) * 10000 + m * 100)
            rows.append({
                'date': d,
                'retail_sales_current': cur,
                'yoy_growth': 1.0 if m != 2 else np.nan,
                'mom_growth': np.nan,
                'retail_sales_cumulative': float((y - 2013) * 100000 + m * 1000),
                'cumulative_yoy': 1.0,
            })
    return pd.DataFrame(rows)


class TestMetrics(unittest.TestCase):

    def test_metrics_hand_computed(self):
        m = _compute_metrics([100.0, 200.0], [110.0, 190.0])
        self.assertEqual(m['mae'], 10.0)   # (10 + 10) / 2
        self.assertEqual(m['rmse'], 10.0)  # sqrt((100 + 100) / 2)
        self.assertEqual(m['mape'], 7.5)   # (10/100 + 10/200) / 2 * 100
        self.assertEqual(m['n'], 2)

    def test_metrics_never_treat_nan_as_zero(self):
        # NaN 对被剔除，绝不当作 0 参与误差（若当作 0，MAE 会变成 105）
        m = _compute_metrics([100.0, np.nan], [110.0, 200.0])
        self.assertEqual(m['n'], 1)
        self.assertEqual(m['mae'], 10.0)
        self.assertEqual(m['mape'], 10.0)

    def test_metrics_zero_actual_excluded_from_mape(self):
        # 真实值为 0 的月份不进入 MAPE 分母，但 MAE/RMSE 仍统计
        m = _compute_metrics([0.0, 100.0], [5.0, 110.0])
        self.assertEqual(m['mae'], 7.5)
        self.assertEqual(m['mape'], 10.0)
        self.assertEqual(m['n'], 2)


class TestBaselines(unittest.TestCase):

    def test_naive_baseline_repeats_last_train_value(self):
        out = _naive_baseline(np.array([10.0, 20.0, 30.0]), 3)
        np.testing.assert_array_equal(out, np.array([30.0, 30.0, 30.0]))

    def test_seasonal_baseline_uses_same_month_last_year_only(self):
        dates = pd.date_range('2015-01-01', periods=24, freq='MS')
        values = np.arange(24, dtype=float) * 100.0 + 1000.0
        df = pd.DataFrame({'date': dates, 'retail_sales_current': values})
        # 训练集截止 2016-05，测试 2016-06 → 同月去年 = 2015-06（index 5 = 1500）
        train = df[df['date'] < pd.Timestamp('2016-06-01')]
        out = _seasonal_baseline(train, [pd.Timestamp('2016-06-01')])
        self.assertEqual(float(out[0]), 1500.0)


class TestBacktest(unittest.TestCase):

    def test_backtest_points_and_metrics(self):
        df = make_clean_df(periods=36)
        bt = backtest_arima(df, test_months=3)
        self.assertEqual(len(bt['points']), 3)
        self.assertEqual(len(bt['test_months']), 3)
        for p in bt['points']:
            self.assertEqual(
                set(p.keys()),
                {'date', 'forecast', 'actual', 'abs_error', 'rel_error_pct', 'lower', 'upper'},
            )
            self.assertTrue(np.isfinite(p['forecast']))
            self.assertTrue(np.isfinite(p['actual']))
        self.assertIsNotNone(bt['metrics']['mape'])
        self.assertIn('naive', bt['baselines'])
        self.assertIn('seasonal', bt['baselines'])

    def test_backtest_no_data_leakage(self):
        df = make_clean_df(periods=36)
        bt = backtest_arima(df, test_months=3)
        # 训练截止月必须严格早于首个回测月（YYYY-MM 字符串可直接比较）
        self.assertLess(bt['train_end'], bt['test_months'][0])
        # 回测窗口内部必须日历连续
        self.assertTrue(_months_are_contiguous(bt['test_months']))

    def test_backtest_window_is_contiguous(self):
        df = make_clean_df(periods=36)
        s = monthly_series(df)
        train, test = _find_recent_contiguous_window(s, 3)
        self.assertEqual(len(test), 3)
        self.assertTrue(_months_are_contiguous(test['date']))
        # 训练截止月 + 1 个月 == 回测首月（边界连续）
        self.assertEqual(
            (train['date'].iloc[-1] + pd.DateOffset(months=1)),
            test['date'].iloc[0],
        )


class TestMissingValuesAndCaliber(unittest.TestCase):

    def test_describe_publication_calendar_detects_cumulative(self):
        df = make_cumulative_df()
        info = describe_publication_calendar(df)
        self.assertTrue(info['has_cumulative_caliber'])
        self.assertEqual(info['cumulative_feb_years'], [2013, 2014, 2015, 2016])
        self.assertEqual(info['missing_jan_years'], [2013, 2014, 2015, 2016])

    def test_monthly_series_drops_feb_nan_without_imputation(self):
        df = make_cumulative_df()
        s = monthly_series(df)
        # 每个 2 月当月值为 NaN，应被剔除且不做任何补造
        self.assertFalse(s['retail_sales_current'].isna().any())
        # 4 年 × 10 个月（3~12 月） = 40 期
        self.assertEqual(len(s), 40)

    def test_contiguous_window_skips_feb_gap(self):
        df = make_cumulative_df()
        s = monthly_series(df)
        train, test = _find_recent_contiguous_window(s, 3)
        # 找到的窗口必须日历连续且不含 1-2 月累计缺口
        self.assertTrue(_months_are_contiguous(test['date']))
        self.assertFalse(test['retail_sales_current'].isna().any())
        self.assertEqual(test['month'].tolist(), ['2016-10', '2016-11', '2016-12'])
        self.assertEqual(train['month'].iloc[-1], '2016-09')


class TestExpandingBacktest(unittest.TestCase):

    def test_expanding_backtest_runs_and_aggregates(self):
        df = make_clean_df(periods=48)
        rb = expanding_backtest(df, window=3, n_windows=3)
        self.assertEqual(rb['n_windows'], 3)
        self.assertEqual(rb['method'], 'expanding-window')
        self.assertIsNotNone(rb['arima']['mape'])
        self.assertIsNotNone(rb['naive']['mape'])
        self.assertIsNotNone(rb['seasonal']['mape'])
        for w in rb['windows']:
            self.assertTrue(_months_are_contiguous(w['test_months']))


if __name__ == "__main__":
    unittest.main()
