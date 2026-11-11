import statsmodels.formula.api as smf

def handle_employee(df):
    return smf.logit('left ~ tenure + salary_band + manager_changes', data=df).fit(disp=False).summary()
