from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression

def score_dynamic():
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=500, class_weight='balanced'))
