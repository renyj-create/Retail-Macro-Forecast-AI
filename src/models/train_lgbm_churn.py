# src/models/train_lgbm_churn.py
import os
import pandas as pd
import numpy as np
import lightgbm as lgb
import shap
import joblib
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, classification_report, f1_score
from scipy.stats import ks_2samp

# 🌟 1. 核心：获取项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def train_churn_model():
    print("正在加载流失预测数据集...")
    csv_path = os.path.join(BASE_DIR, 'data', 'processed', 'churn_dataset.csv')

    if not os.path.exists(csv_path):
        print(f"❌ 错误：找不到文件 {csv_path}")
        return

    df = pd.read_csv(csv_path)
    df = df.fillna(0)
    df = pd.get_dummies(df, columns=['city_tier'], drop_first=True)

    drop_cols = ['user_id', 'is_churn', 'register_date']
    feature_cols = [c for c in df.columns if c not in drop_cols]
    X = df[feature_cols]
    y = df['is_churn']

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    print(f"训练集样本数: {len(X_train)}, 测试集样本数: {len(X_test)}")

    # 🌟 2. 处理类别不平衡的 LightGBM 二分类
    scale_pos_weight = (len(y_train) - sum(y_train)) / sum(y_train)

    model = lgb.LGBMClassifier(
        n_estimators=100,
        learning_rate=0.05,
        max_depth=5,
        num_leaves=31,
        scale_pos_weight=scale_pos_weight,
        random_state=42,
        n_jobs=-1
    )

    print("正在训练 LightGBM 模型...")
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        eval_metric='auc',
        callbacks=[lgb.early_stopping(stopping_rounds=10, verbose=False)]
    )

    # 🌟 3. 模型评估
    y_pred_proba = model.predict_proba(X_test)[:, 1]
    y_pred = model.predict(X_test)

    auc = roc_auc_score(y_test, y_pred_proba)
    f1 = f1_score(y_test, y_pred)
    ks_stat, p_value = ks_2samp(y_pred_proba[y_test == 1], y_pred_proba[y_test == 0])

    print("\n--- 模型评估结果 ---")
    print(f"AUC: {auc:.4f}")
    print(f"F1-Score: {f1:.4f}")
    print(f"KS: {ks_stat:.4f}")
    print("\n分类报告:")
    print(classification_report(y_test, y_pred))

    # 🌟 4. 模型可解释性 - SHAP
    print("正在生成 SHAP 可解释性分析图...")
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_test)

    # 🌟 5. 保存模型
    model_dir = os.path.join(BASE_DIR, 'src', 'models', 'saved_models')
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, 'lgbm_churn_model.pkl')
    joblib.dump(model, model_path)
    print(f"✅ 模型已保存至 {model_path}")

    # 🌟 6. 特征重要性
    importance_df = pd.DataFrame({
        'feature': feature_cols,
        'importance': model.feature_importances_
    }).sort_values(by='importance', ascending=False)

    print("\n--- 特征重要性 TOP 5 ---")
    print(importance_df.head(5))


if __name__ == "__main__":
    train_churn_model()