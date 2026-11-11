from scipy import stats

def run_clinic(a, b):
    t, p = stats.ttest_ind(a, b, equal_var=False)
    return {'t': float(t), 'p': float(p)}
