import requests
import urllib3
import pandas as pd
from io import StringIO, BytesIO
import time
from datetime import datetime
import logging
from .validators import PriceValidator
from .models import Stock, DailyPrice

# 停用 SSL 憑證警告 (因為政府網站有時憑證會異常)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

class MarketCrawler:
    """TWSE 與 OTC 爬蟲統一介面"""
    
    @staticmethod
    def fetch_twse(date_obj, max_retries=5, retry_delay=10):
        """爬取上市股票每日收盤行情（修正版：HTTPS + 支援除權息日欄位偏移）"""
        date_str = date_obj.strftime('%Y%m%d')
        # PATCH: HTTPS（證交所已強制 HTTPS）
        url = f'https://www.twse.com.tw/exchangeReport/MI_INDEX?response=csv&date={date_str}&type=ALL'
        
        for attempt in range(max_retries):
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
                r = requests.get(url, headers=headers, timeout=10, verify=False)
                if r.text == '' or len(r.text) < 1000:
                    if attempt < max_retries - 1:
                        logger.warning(f"TWSE 內容過少 ({len(r.text)} bytes)，第 {attempt + 1} 次重試...")
                        time.sleep(retry_delay)
                        continue
                    return pd.DataFrame()
                
                # 處理原始 CSV 字串
                lines = r.text.split('\n')
                
                # PATCH: 找到 header 行（包含 '證券代號'）
                header_idx = None
                for i, line in enumerate(lines):
                    if '證券代號' in line or 'code' in line.lower():
                        header_idx = i
                        break
                
                if header_idx is None:
                    print(f"⚠️ No header found in TWSE response for {date_str}. Returning empty DataFrame.")
                    return pd.DataFrame()
                
                # PATCH: 截取 header 之後的內容，重新組成 CSV，避免 pandas 行數錯位
                csv_lines = lines[header_idx:]
                csv_text = '\n'.join(csv_lines)
                df = pd.read_csv(StringIO(csv_text), header=0)
                
                # PATCH: 動態找到需要的欄位位置
                col_map = {}
                twse_col_names = {
                    '證券代號': 'code',
                    '證券名稱': 'name',
                    '成交股數': 'volume',
                    '成交金額': 'trade_value',
                    '開盤價': 'open',
                    '最高價': 'high',
                    '最低價': 'low',
                    '收盤價': 'close',
                }
                
                for col in df.columns:
                    for twse_name, eng_name in twse_col_names.items():
                        if twse_name in str(col):
                            col_map[col] = eng_name
                            break
                
                if len(col_map) < 8:
                    print(f"⚠️ TWSE columns insufficient ({len(col_map)} < 8). Missing: {set(twse_col_names.values()) - set(col_map.values())}")
                    return pd.DataFrame()
                
                df.rename(columns=col_map, inplace=True)
                df = df.set_index('code')
                
                # 把字串數字轉為浮點數
                cols_to_numeric = ['open', 'high', 'low', 'close', 'volume', 'trade_value']
                for col in cols_to_numeric:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce')
                
                # 移除 NaN 過多的行（可能是權證等無效資料）
                df = df.dropna(subset=['close', 'volume'], how='any')
                
                df['market'] = 'twse'
                return df
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"TWSE 爬取失敗，第 {attempt + 1} 次重試：{e}")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"TWSE crawler error on {date_str} after {max_retries} attempts: {e}")
                    return pd.DataFrame()

    @staticmethod
    def fetch_otc(date_obj, max_retries=5, retry_delay=10):
        """爬取上櫃股票每日收盤行情（修正版：支援除權息日欄位偏移）"""
        year = date_obj.year - 1911
        date_str = f"{year}/{date_obj.month:02d}/{date_obj.day:02d}"
        url = f'https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php?l=zh-tw&o=csv&d={date_str}&se=AL&s=0,asc,0'
        
        for attempt in range(max_retries):
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
                r = requests.get(url, headers=headers, timeout=10, verify=False)
                
                # OTC 網站使用 Big5/MS950 編碼
                content = r.content.decode('big5', errors='ignore')
                
                if content == '' or len(content) < 1000:
                    if attempt < max_retries - 1:
                        logger.warning(f"OTC 內容過少 ({len(content)} bytes)，第 {attempt + 1} 次重試...")
                        time.sleep(retry_delay)
                        continue
                    return pd.DataFrame()
                
                lines = content.split('\n')
                # 尋找 header 所在行 (包含 '代號' 的那行)
                header_idx = next((i for i, l in enumerate(lines) if '代號' in l or 'code' in l.lower()), -1)
                
                if header_idx == -1:
                    print(f"⚠️ OTC header not found for {date_str}. Returning empty DataFrame.")
                    return pd.DataFrame()
                
                # PATCH: 直接讓 pandas 用 header 行解析
                csv_data = content.replace("=", "")
                df = pd.read_csv(StringIO(csv_data), header=header_idx)
                
                # PATCH: 動態找到需要的欄位位置（不再硬編碼）
                col_map = {}
                otc_col_names = {
                    '代號': 'code',
                    '名稱': 'name',
                    '收盤': 'close',
                    '開盤': 'open',
                    '最高': 'high',
                    '最低': 'low',
                    '成交股數': 'volume',
                    '成交金額': 'trade_value',
                }
                
                for col in df.columns:
                    for otc_name, eng_name in otc_col_names.items():
                        if otc_name in str(col):
                            col_map[col] = eng_name
                            break
                
                if len(col_map) < 8:
                    print(f"⚠️ OTC columns insufficient ({len(col_map)} < 8). Missing: {set(otc_col_names.values()) - set(col_map.values())}")
                    return pd.DataFrame()
                
                df.rename(columns=col_map, inplace=True)
                df = df.set_index('code')
                
                # 只保留需要的欄位
                cols_to_keep = ['name', 'open', 'high', 'low', 'close', 'volume', 'trade_value']
                df = df[[c for c in cols_to_keep if c in df.columns]]
                
                cols_to_numeric = ['open', 'high', 'low', 'close', 'volume', 'trade_value']
                for col in cols_to_numeric:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '').str.strip(), errors='coerce')
                
                # PATCH: 移除 NaN 過多的行
                df = df.dropna(subset=['close', 'volume'], how='any')
                
                df['market'] = 'otc'
                return df
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"OTC 爬取失敗，第 {attempt + 1} 次重試：{e}")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"OTC crawler error on {date_str} after {max_retries} attempts: {e}")
                    return pd.DataFrame()

    @classmethod
    def run_daily_crawl(cls, target_date=None):
        """執行每日爬取，並將資料寫入 DB"""
        if target_date is None:
            target_date = datetime.today().date()
            
        print(f"開始爬取 {target_date} 股市資料...")
        
        twse_df = cls.fetch_twse(target_date)
        time.sleep(3)  # 避免被封鎖
        otc_df = cls.fetch_otc(target_date)
        
        if twse_df.empty and otc_df.empty:
            print(f"{target_date} 無交易資料 (可能是假日)。")
            return
        
        MIN_TWSE_ROWS = 500
        MIN_OTC_ROWS = 300
        
        if not twse_df.empty and len(twse_df) < MIN_TWSE_ROWS:
            print(f"警告：TWSE 僅 {len(twse_df)} 筆 (< {MIN_TWSE_ROWS})，疑似不完整，捨棄")
            twse_df = pd.DataFrame()
        if not otc_df.empty and len(otc_df) < MIN_OTC_ROWS:
            print(f"警告：OTC 僅 {len(otc_df)} 筆 (< {MIN_OTC_ROWS})，疑似不完整，捨棄")
            otc_df = pd.DataFrame()
        
        if twse_df.empty and otc_df.empty:
            print(f"{target_date} 無有效資料 (TWSE 或 OTC 筆數不足)。")
            return
            
        # 合併上市櫃
        df_all = pd.concat([twse_df, otc_df])
        
        # 只保留有 4 碼數字的普通股 (過濾掉權證、債券等)
        df_all = df_all[df_all.index.astype(str).str.match(r'^\d{4}$')]
        
        stocks_to_create = []
        prices_to_create = []
        
        # 取得資料庫現有股票清單，減少 DB 查詢
        existing_stocks = {s.code: s for s in Stock.objects.all()}
        
        for code, row in df_all.iterrows():
            code = str(code).strip()
            
            # 建立或更新 Stock
            if code not in existing_stocks:
                stock = Stock(
                    code=code,
                    name=str(row.get('name', '')).strip(),
                    market=row.get('market', 'twse')
                )
                stocks_to_create.append(stock)
                existing_stocks[code] = stock
            else:
                stock = existing_stocks[code]
                
            # 準備 DailyPrice
            if pd.notna(row.get('close')):
                # PATCH: Layer 1 即時檢驗
                row_dict = {
                    'open': row.get('open'),
                    'high': row.get('high'),
                    'low': row.get('low'),
                    'close': row.get('close'),
                    'volume': row.get('volume'),
                }
                prev_close = PriceValidator.get_prev_close(code, target_date)
                is_valid, reason = PriceValidator.validate_row(row_dict, prev_close)
                if not is_valid:
                    logger.warning(f"[{target_date}] {code} 驗證失敗: {reason}，跳過寫入")
                    continue
                
                price = DailyPrice(
                    stock=stock,
                    date=target_date,
                    open=row['open'] if pd.notna(row['open']) else None,
                    high=row['high'] if pd.notna(row['high']) else None,
                    low=row['low'] if pd.notna(row['low']) else None,
                    close=row['close'] if pd.notna(row['close']) else None,
                    volume=row['volume'] if pd.notna(row['volume']) else None,
                    trade_value=row['trade_value'] if pd.notna(row['trade_value']) else None,
                )
                prices_to_create.append(price)

        # 批次寫入資料庫
        if stocks_to_create:
            Stock.objects.bulk_create(stocks_to_create, ignore_conflicts=True)
            # 重新從資料庫讀取一次，以取得最新的 ID
            existing_stocks = {s.code: s for s in Stock.objects.filter(code__in=df_all.index.unique().astype(str))}
            
            # 將剛才建立的 price 物件重新綁定具有 ID 的 stock 物件
            for price in prices_to_create:
                price.stock = existing_stocks.get(price.stock.code)
            
        if prices_to_create:
            # 過濾掉找不到對應股票的股價資料 (理論上不會發生)
            prices_to_create = [p for p in prices_to_create if p.stock and p.stock.id]
            # 先刪除該日期舊資料，再寫入新資料（每次都完整覆蓋）
            DailyPrice.objects.filter(date=target_date).delete()
            DailyPrice.objects.bulk_create(prices_to_create)
            
        print(f"爬取完成！共寫入 {len(prices_to_create)} 筆股價資料。")
