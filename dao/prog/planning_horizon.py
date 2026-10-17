"""Keep prices and forecasts on the same physical interval grid."""
import pandas as pd


def align_weather_prices(weather, prices):
    """Match exact starts on quarter-hour/hour grids; exclude missing prices."""
    left = weather.drop(columns=['da_ex', 'da_cons', 'da_prod'], errors='ignore').copy()
    right = prices[['time', 'da_ex', 'da_cons', 'da_prod']].copy()
    left['tijd'] = pd.to_datetime(left['tijd'])
    right['price_time'] = pd.to_datetime(right.pop('time'))
    if right['price_time'].duplicated().any():
        raise ValueError('Duplicate price timestamps')
    # The incoming frame also has a DatetimeIndex named tijd in live DAO.
    left = left.reset_index(drop=True)
    aligned = left.merge(right, left_on='tijd', right_on='price_time', how='inner', validate='one_to_one')
    return aligned.drop(columns='price_time').dropna(subset=['da_ex','da_cons','da_prod']).sort_values('tijd').reset_index(drop=True)
