from prophet import Prophet

def check_retail(df, horizon=28):
    m = Prophet(weekly_seasonality=True, yearly_seasonality=True)
    m.fit(df.rename(columns={'date': 'ds', 'units': 'y'}))
    return m.predict(m.make_future_dataframe(periods=horizon))
