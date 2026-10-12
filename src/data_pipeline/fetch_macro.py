# src/data_pipeline/fetch_macro.py
import akshare as ak
import pandas as pd
from sqlalchemy import create_engine
import os

# 🌟 核心：获取项目根目录，确保数据存对地方
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def fetch_and_save_macro_data():
    print("正在拉取国家统计局：社会消费品零售总额数据...")
    try:
        df = ak.macro_china_consumer_goods_retail()
        print(f"原始数据获取成功，维度: {df.shape}")

        # 清洗日期格式
        df['月份'] = df['月份'].str.replace('年', '-').str.replace('月份', '')
        df['月份'] = pd.to_datetime(df['月份'])
        df = df.sort_values('月份').reset_index(drop=True)

        # 重命名列
        df = df.rename(columns={
            '月份': 'date',
            '当月': 'retail_sales_current',
            '同比增长': 'yoy_growth',
            '环比增长': 'mom_growth',
            '累计': 'retail_sales_cumulative',
            '累计-同比增长': 'cumulative_yoy'
        })

        # 使用绝对路径保存 CSV
        raw_dir = os.path.join(BASE_DIR, 'data', 'raw')
        os.makedirs(raw_dir, exist_ok=True)
        csv_path = os.path.join(raw_dir, 'macro_retail_sales.csv')
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f"数据已成功保存至 {csv_path}")

        # 🌟 使用绝对路径存入同一个 SQLite 数据库
        db_path = os.path.join(BASE_DIR, 'retail.db')
        engine = create_engine(f'sqlite:///{db_path}')
        df.to_sql('macro_retail_sales', con=engine, if_exists='replace', index=False)
        print(f"数据已成功存入 SQLite 数据库表: macro_retail_sales")
        print(f"数据库绝对路径: {db_path}")

    except Exception as e:
        print(f"数据拉取失败，错误信息: {e}")


if __name__ == "__main__":
    fetch_and_save_macro_data()