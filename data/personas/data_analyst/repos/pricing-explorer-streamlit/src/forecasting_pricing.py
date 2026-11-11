from statsmodels.tsa.holtwinters import ExponentialSmoothing

def score_pricing(series, horizon=13):
    fit = ExponentialSmoothing(series, trend='add', seasonal='add', seasonal_periods=52).fit()
    return fit.forecast(horizon)
