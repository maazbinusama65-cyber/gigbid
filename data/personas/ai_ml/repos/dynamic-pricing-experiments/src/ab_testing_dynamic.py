from math import sqrt

def sync_dynamic(c_a, n_a, c_b, n_b):
    p_a, p_b = c_a / n_a, c_b / n_b
    se = sqrt(p_a * (1 - p_a) / n_a + p_b * (1 - p_b) / n_b)
    return (p_b - p_a) / se
