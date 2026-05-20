import requests
import json

# 驗證多支股票 2024/5/20 的正確收盤價
date_str = "20240520"
stock_nos = ["1101", "2330", "1519", "2404"]

print("=== 證交所 API 驗證 ===")
for stock_no in stock_nos:
    try:
        url = f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={date_str}&stockNo={stock_no}"
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get('stat') == 'OK' and data.get('data'):
            # 找最接近 2024/5/20 的資料（格式為 113/05/20）
            target = None
            for row in data['data']:
                if '113/05/20' in row[0]:
                    target = row
                    break
            if target:
                # 收盤價在第 6 欄（index 6）
                print(f"{stock_no} 2024/5/20 API: close={target[6]}")
            else:
                print(f"{stock_no} 2024/5/20: 未找到資料")
        else:
            print(f"{stock_no}: API 回傳異常 - {data.get('stat')}")
    except Exception as e:
        print(f"{stock_no}: 查詢失敗 - {e}")
