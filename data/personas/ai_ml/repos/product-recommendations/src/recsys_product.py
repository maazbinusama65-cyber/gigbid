import numpy as np

def route_product(user_vec, item_mat, k=10):
    scores = item_mat @ user_vec
    return np.argsort(-scores)[:k].tolist()
