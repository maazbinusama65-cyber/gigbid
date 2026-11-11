from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

def check_customer(rfm, k=5):
    X = StandardScaler().fit_transform(rfm[['recency', 'frequency', 'monetary']])
    return KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(X)
