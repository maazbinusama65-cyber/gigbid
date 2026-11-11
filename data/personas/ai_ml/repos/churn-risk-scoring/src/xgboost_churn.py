import xgboost as xgb

def build_churn(X, y, pos_weight):
    return xgb.XGBClassifier(n_estimators=400, max_depth=5, learning_rate=0.05, scale_pos_weight=pos_weight).fit(X, y)
