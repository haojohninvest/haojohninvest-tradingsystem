import pandas as pd
from datetime import date, timedelta
import logging
import os
import csv

logger = logging.getLogger(__name__)

ANOMALY_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")
ANOMALY_LOG_FILE = os.path.join(ANOMALY_LOG_DIR, "price_anomalies.csv")


def log_price_anomaly(date_str, stock_code, stock_name, close_price, prev_close, change_pct):
    os.makedirs(ANOMALY_LOG_DIR, exist_ok=True)
    file_exists = os.path.isfile(ANOMALY_LOG_FILE)
    with open(ANOMALY_LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["date", "code", "name", "close", "prev_close", "change_pct"])
        writer.writerow([date_str, stock_code, stock_name, close_price, prev_close, f"{change_pct:.2%}"])


class PriceValidator:

    @staticmethod
    def check_jump(row, prev_close=None):
        if pd.isna(row.get("close")) or row["close"] <= 0:
            return True, "OK"
        if not prev_close or prev_close <= 0:
            return True, "OK"
        prev_close_float = float(prev_close)
        change_pct = abs(row["close"] - prev_close_float) / prev_close_float
        if change_pct > 0.15:
            return False, f"jump > 15%: {prev_close} -> {row['close']} ({change_pct:.1%})"
        return True, "OK"

    @staticmethod
    def get_prev_close(stock_code, target_date):
        from apps.market_data.models import DailyPrice, Stock

        try:
            stock = Stock.objects.filter(code=stock_code).first()
            if not stock:
                return None
            prev = DailyPrice.objects.filter(
                stock=stock,
                date__lt=target_date
            ).order_by("-date").first()
            if not prev:
                return None
            days_gap = (target_date - prev.date).days
            if days_gap > 30:
                return None
            return prev.close
        except Exception:
            return None
