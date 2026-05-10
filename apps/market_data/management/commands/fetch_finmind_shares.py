import requests
import pandas as pd
import time
from datetime import datetime
from apps.market_data.models import Stock, StockSharesHistory
import os

# FinMind API Token (從環境變數讀取)
FINMIND_TOKEN = os.getenv('FINMIND_TOKEN', '')

def get_capital_stock_from_finmind(stock_id, year, quarter, token):
    """從 FinMind 抓指定季度的 CapitalStock (股本)"""
    quarter_months = {
        1: ("01-01", "03-31"),
        2: ("04-01", "06-30"),
        3: ("07-01", "09-30"),
        4: ("10-01", "12-31")
    }
    start_m, end_m = quarter_months[quarter]
    start_date = f"{year}-{start_m}"
    end_date = f"{year}-{end_m}"
    
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanStockBalanceSheet",
        "data_id": stock_id,
        "start_date": start_date,
        "end_date": end_date,
        "token": token
    }
    
    try:
        r = requests.get(url, params=params, timeout=30)
        data = r.json()
        if "data" in data and data["data"]:
            df = pd.DataFrame(data["data"])
            capital = df[df['type'] == 'CapitalStock']
            if len(capital) > 0:
                value = float(capital.iloc[0]['value'])
                return value
    except Exception as e:
        print(f"[ERROR] FinMind {stock_id} {year}Q{quarter}: {e}")
    return None

def get_shares_with_fallback(stock_id, year, quarter, token):
    """抓股數，帶有 fallback 機制"""
    # 嘗試抓該季度
    capital = get_capital_stock_from_finmind(stock_id, year, quarter, token)
    
    # Fallback：往回推最多 12 個季度（3 年）
    fallback_count = 0
    q_year, q_quarter = year, quarter
    while capital is None and fallback_count < 12:
        # 回推到上一季
        q_quarter -= 1
        if q_quarter < 1:
            q_quarter = 4
            q_year -= 1
        capital = get_capital_stock_from_finmind(stock_id, q_year, q_quarter, token)
        fallback_count += 1
    
    if capital and capital > 0:
        shares = capital / 10  # 股本 / 面額10元 = 股數
        return int(shares), f"finmind_{q_year}Q{q_quarter}"
    
    # 最終 fallback：寫 0
    return 0, "zero_fallback"

def fetch_all_historical_shares(start_year=2016, end_year=2025):
    """抓取所有股票 2016~end_year 的每年 Q4 股本"""
    if not FINMIND_TOKEN:
        print("[ERROR] 請設定 FINMIND_TOKEN 環境變數")
        return
    
    stocks = Stock.objects.all()
    total = stocks.count()
    print(f"共 {total} 檔股票需要抓取歷史股數")
    
    records_created = 0
    records_skipped = 0
    
    for idx, stock in enumerate(stocks, 1):
        print(f"[{idx}/{total}] 處理 {stock.code} {stock.name}...", end=" ")
        
        for year in range(start_year, end_year + 1):
            # 每年只抓 Q4
            shares, source = get_shares_with_fallback(stock.code, year, 4, FINMIND_TOKEN)
            
            if shares > 0:
                # 用該年 Q4 的最後一天作為適用日期
                applicable_date = datetime(year, 12, 31).date()
                
                obj, created = StockSharesHistory.objects.update_or_create(
                    stock=stock,
                    date=applicable_date,
                    defaults={
                        'outstanding_shares': shares,
                        'source': source
                    }
                )
                if created:
                    records_created += 1
            else:
                records_skipped += 1
        
        print("OK")
        
        # Rate limit 控制：每小時 600 次，每次抓一檔一年約 1 次 request
        # 抓 2,000 檔 x 10 年 = 20,000 次，需要約 33 小時
        # 為了安全，每檔之間 sleep 0.5 秒
        time.sleep(0.5)
    
    print(f"\n完成！新增 {records_created} 筆記錄，跳過 {records_skipped} 筆（股數為 0）")

def fetch_2026_quarterly_shares():
    """抓取 2026 的 Q1 (及後續季度) 股本"""
    if not FINMIND_TOKEN:
        print("[ERROR] 請設定 FINMIND_TOKEN 環境變數")
        return
    
    stocks = Stock.objects.all()
    total = stocks.count()
    print(f"共 {total} 檔股票需要抓取 2026 Q1 股數")
    
    records_created = 0
    
    for idx, stock in enumerate(stocks, 1):
        print(f"[{idx}/{total}] 處理 {stock.code} {stock.name}...", end=" ")
        
        # 抓 2026 Q1
        shares, source = get_shares_with_fallback(stock.code, 2026, 1, FINMIND_TOKEN)
        
        if shares > 0:
            applicable_date = datetime(2026, 3, 31).date()
            obj, created = StockSharesHistory.objects.update_or_create(
                stock=stock,
                date=applicable_date,
                defaults={
                    'outstanding_shares': shares,
                    'source': source
                }
            )
            if created:
                records_created += 1
            print(f"股數: {shares:,} ({source})")
        else:
            print("股數為 0 (fallback 失敗)")
        
        time.sleep(0.5)
    
    print(f"\n完成！新增 {records_created} 筆 2026 Q1 記錄")

if __name__ == '__main__':
    import django
    django.setup()
    
    print("=== 抓取 2016~2025 歷史股數 (Q4) ===")
    fetch_all_historical_shares(2016, 2025)
    
    print("\n=== 抓取 2026 Q1 股數 ===")
    fetch_2026_quarterly_shares()
    
    print("\n全部完成！")
