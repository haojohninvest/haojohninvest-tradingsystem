import requests
import urllib3
import pandas as pd
from io import StringIO, BytesIO
import time
from datetime import datetime
import logging
from .models import Stock, DailyPrice

# 停用 SSL 憑證警告 (因為政府網站有時憑證會異常)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

class MarketCrawler:
    """TWSE 與 OTC 爬蟲統一介面"""
    
    @staticmethod
    def fetch_twse(date_obj, max_retries=5, retry_delay=10):
        """爬取上市股票每日收盤行情"""
        date_str = date_obj.strftime('%Y%m%d')
        url = f'http://www.twse.com.tw/exchangeReport/MI_INDEX?response=csv&date={date_str}&type=ALL'
        
        for attempt in range(max_retries):
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
                r = requests.post(url, headers=headers, timeout=10, verify=False)
                if r.text == '' or len(r.text) < 1000:
                    if attempt < max_retries - 1:
                        logger.warning(f"TWSE 內容過少 ({len(r.text)} bytes)，第 {attempt + 1} 次重試...")
                        time.sleep(retry_delay)
                        continue
                    return pd.DataFrame()
                
                # 處理原始 CSV 字串
                lines = r.text.split('\n')
                # 找到有 17 個欄位且開頭不是 '=' 的行
                cleaned_lines = [i.translate({ord(c): None for c in ' '}) for i in lines if len(i.split('",')) == 17 and i[0] != '=']
                
                if not cleaned_lines:
                    if attempt < max_retries - 1:
                        logger.warning(f"TWSE 無有效資料，第 {attempt + 1} 次重試...")
                        time.sleep(retry_delay)
                        continue
                    return pd.DataFrame()
                    
                csv_data = "\n".join(cleaned_lines)
                df = pd.read_csv(StringIO(csv_data), header=0)
                
                # 清理欄位與索引
                df.rename(columns={'證券代號': 'code', '證券名稱': 'name', '開盤價': 'open', '最高價': 'high', '最低價': 'low', '收盤價': 'close', '成交股數': 'volume', '成交金額': 'trade_value'}, inplace=True)
                df = df.set_index('code')
                
                # 把字串數字轉為浮點數，若有 '--' 等符號轉為 NaN
                cols_to_numeric = ['open', 'high', 'low', 'close', 'volume', 'trade_value']
                for col in cols_to_numeric:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce')
                        
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
        """爬取上櫃股票每日收盤行情"""
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
                    if attempt < max_retries - 1:
                        logger.warning(f"OTC 找不到 header，第 {attempt + 1} 次重試...")
                        time.sleep(retry_delay)
                        continue
                    return pd.DataFrame()
                
                # 直接指定欄位名稱（避免編碼問題導致 rename 失敗）
                csv_data = content.replace("=", "")
                df = pd.read_csv(StringIO(csv_data), header=header_idx)
                
                # 用位置重新命名欄位
                # OTC 官方 CSV 欄位順序：代號,名稱,收盤,漲跌,開盤,最高,最低,成交股數,成交金額,...
                expected_cols = ['code', 'name', 'close', 'change', 'open', 'high', 'low', 'volume', 'trade_value', 'pe', 'pe_ratio', 'roa', 'roe', 'net_value', 'book_value', 'dividend', 'yield']
                actual_cols = df.columns.tolist()
                
                # 只 rename 實際存在的欄位
                rename_map = {}
                for i, col_name in enumerate(expected_cols):
                    if i < len(actual_cols):
                        rename_map[actual_cols[i]] = col_name
                
                df.rename(columns=rename_map, inplace=True)
                df = df.set_index('code')
                
                # 只保留需要的欄位
                cols_to_keep = ['name', 'open', 'high', 'low', 'close', 'volume', 'trade_value']
                df = df[[c for c in cols_to_keep if c in df.columns]]
                
                cols_to_numeric = ['open', 'high', 'low', 'close', 'volume', 'trade_value']
                for col in cols_to_numeric:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '').str.strip(), errors='coerce')
                
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
            # 使用 ignore_conflicts 避免重複抓取同一天造成錯誤
            DailyPrice.objects.bulk_create(prices_to_create, ignore_conflicts=True)
            
        print(f"爬取完成！共寫入 {len(prices_to_create)} 筆股價資料。")
