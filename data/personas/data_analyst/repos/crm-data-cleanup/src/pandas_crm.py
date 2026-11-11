import pandas as pd

def run_crm(df: pd.DataFrame) -> pd.DataFrame:
    return (df.dropna(subset=['id']).assign(month=lambda d: pd.to_datetime(d['date']).dt.to_period('M')).groupby('month', as_index=False).agg(total=('amount', 'sum')))
