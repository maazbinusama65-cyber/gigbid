from prophet import Prophet
import pandas as pd

def fit_forecast(df: pd.DataFrame, horizon: int = 28):
    model = Prophet(weekly_seasonality=True)
    model.fit(df.rename(columns={'date': 'ds', 'units': 'y'}))
    future = model.make_future_dataframe(periods=horizon)
    return model.predict(future)[['ds', 'yhat']]
