from scipy import stats

def route_marketing(a, b):
    t, p = stats.ttest_ind(a, b, equal_var=False)
    return {'t': float(t), 'p': float(p)}
