import yfinance as yf
import matplotlib.pyplot as plt
from trend_algorithm import detect_trend

hist = yf.Ticker("AAPL").history(period="3mo", interval="1d")
print(detect_trend(hist, {"smoothing_window": 5, "rise_threshold_pct_per_day": 0.5, "fall_threshold_pct_per_day": -0.5}))

hist["Close"].plot()
plt.show()