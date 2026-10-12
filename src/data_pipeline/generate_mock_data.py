# src/data_pipeline/generate_mock_data.py
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sqlalchemy import create_engine
import os


def generate_retail_user_data(num_users=5000, days=730):
    print(f"正在生成 {num_users} 名用户过去 {days} 天的模拟交易数据...")
    np.random.seed(42)

    # 1. 生成用户基础属性
    user_ids = np.arange(10001, 10001 + num_users)
    user_ages = np.random.randint(18, 65, size=num_users)
    user_city_tiers = np.random.choice(['一线', '二线', '三线'], size=num_users, p=[0.2, 0.4, 0.4])
    user_reg_dates = [datetime(2024, 1, 1) + timedelta(days=np.random.randint(0, 365)) for _ in range(num_users)]

    users_df = pd.DataFrame({
        'user_id': user_ids,
        'age': user_ages,
        'city_tier': user_city_tiers,
        'register_date': user_reg_dates
    })

    # 2. 生成交易流水
    categories = ['家电', '食品', '服饰', '通讯器材', '汽车']
    transactions = []

    start_date = datetime(2024, 8, 1)
    end_date = start_date + timedelta(days=days)
    cutoff_date = start_date + timedelta(days=550)  # 观察期结束（前18个月）

    for uid in user_ids:
        base_frequency = np.random.poisson(3)
        base_amount = np.random.normal(200, 50)

        # 🌟 核心修改：为30%的用户添加“流失”逻辑
        # 如果用户被判定为流失，他们在观察期（前18个月）之后，随机在某个月停止消费
        is_churn_user = np.random.choice([True, False], p=[0.3, 0.7])
        if is_churn_user:
            # 流失用户在 cutoff_date 之前或之后不久停止购买
            user_churn_date = cutoff_date + timedelta(days=np.random.randint(-60, 60))
        else:
            user_churn_date = end_date  # 不流失的用户一直买到期末

        for month in range(24):
            current_month = start_date + timedelta(days=30 * month)
            if current_month > user_churn_date:
                break  # 停止生成交易，模拟流失

            is_promo = current_month.month in [6, 11]
            freq = base_frequency * (2 if is_promo else 1)

            for _ in range(max(0, np.random.poisson(freq))):
                trans_date = current_month + timedelta(days=np.random.randint(0, 28))
                if trans_date > end_date or trans_date > user_churn_date: continue

                amount = max(10, np.random.normal(base_amount, 30))
                category = np.random.choice(categories, p=[0.2, 0.4, 0.25, 0.1, 0.05])

                transactions.append({
                    'user_id': uid,
                    'trans_date': trans_date,
                    'amount': round(amount, 2),
                    'category': category
                })

    trans_df = pd.DataFrame(transactions)
    print(f"交易流水生成完成，共 {len(trans_df)} 条记录。")

    return users_df, trans_df

def build_churn_labels(users_df, trans_df):
    """构建流失标签（核心：JD1需要的二分类目标）"""
    print("正在计算 RFM 特征并构建流失标签...")

    # 定义观察期和表现期
    # 观察期：前18个月（用于提取特征）
    # 表现期：后6个月（用于判断是否流失）
    cutoff_date = trans_df['trans_date'].max() - timedelta(days=180)

    # 1. 计算观察期内的 RFM 特征
    obs_trans = trans_df[trans_df['trans_date'] <= cutoff_date]

    # 最近一次购买时间 (Recency)
    recency = obs_trans.groupby('user_id')['trans_date'].max().reset_index()
    recency['recency_days'] = (cutoff_date - recency['trans_date']).dt.days

    # 购买频率 (Frequency) 和 消费金额 (Monetary)
    freq_monetary = obs_trans.groupby('user_id').agg(
        frequency=('trans_date', 'count'),
        monetary=('amount', 'sum'),
        avg_amount=('amount', 'mean')
    ).reset_index()

    # 合并特征
    features = pd.merge(recency[['user_id', 'recency_days']], freq_monetary, on='user_id', how='left')

    # 2. 构建流失标签 (Churn Label)
    # 如果在表现期内（后6个月）没有产生任何交易，则标记为流失 (1)，否则为未流失 (0)
    future_trans = trans_df[trans_df['trans_date'] > cutoff_date]
    active_users = future_trans['user_id'].unique()

    features['is_churn'] = features['user_id'].apply(lambda x: 0 if x in active_users else 1)

    # 补充用户基础属性
    final_df = pd.merge(features, users_df, on='user_id', how='left')

    print(f"标签构建完成，流失率：{final_df['is_churn'].mean():.2%}")
    return final_df


if __name__ == "__main__":
    # 1. 生成数据
    users_df, trans_df = generate_retail_user_data(num_users=5000, days=730)

    # 2. 构建特征与标签
    ml_dataset = build_churn_labels(users_df, trans_df)

    # 3. 保存到项目目录
    os.makedirs('data/processed', exist_ok=True)
    users_df.to_csv('data/raw/users_info.csv', index=False, encoding='utf-8-sig')
    trans_df.to_csv('data/raw/transactions.csv', index=False, encoding='utf-8-sig')
    ml_dataset.to_csv('data/processed/churn_dataset.csv', index=False, encoding='utf-8-sig')

    # 4. 存入 SQLite 数据库（为后续 Text-to-SQL 做准备）
    engine = create_engine('sqlite:///retail.db')
    users_df.to_sql('users_info', con=engine, if_exists='replace', index=False)
    trans_df.to_sql('transactions', con=engine, if_exists='replace', index=False)
    ml_dataset.to_sql('churn_dataset', con=engine, if_exists='replace', index=False)

    print("全部数据已成功保存至 CSV 和 SQLite 数据库！")