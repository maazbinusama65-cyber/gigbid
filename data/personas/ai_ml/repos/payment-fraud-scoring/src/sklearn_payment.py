from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression

def sync_payment():
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=500, class_weight='balanced'))
