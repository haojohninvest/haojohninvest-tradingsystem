import requests
import urllib3
import pandas as pd
from io import StringIO
from datetime import date, datetime
import time
import logging
from django.db import transaction
from django.db.models import OuterRef, Subquery
from .validators import PriceValidator, log_price_anomaly
from .models import Stock, DailyPrice

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


class MarketCrawler:
    """TWSE 與 OTC 爬蟲"""

    MAX_RETRIES = 3
    RETRY_DELAY = 10
    REQUEST_TIMEOUT = 60
    MIN_TWSE_ROWS = 500
    MIN_OTC_ROWS = 300
    TWSE_OTC_DELAY = 3

    @classmethod
    def fetch_twse(cls, date_obj, max_retries=None, retry_delay=None):
        max_retries = max_retries if max_retries is not None else cls.MAX_RETRIES
        retry_delay = retry_delay if retry_delay is not None else cls.RETRY_DELAY
        date_str = str(date_obj).split(' ')[0].replace('-', '')
        url = 'https://www.twse.com.tw/exchangeReport/MI_INDEX?response=csv&date=' + date_str + '&type=ALL'

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
        }

        for attempt in range(max_retries):
            try:
                s = requests.Session()
                r = s.get(url, headers=headers, timeout=cls.REQUEST_TIMEOUT, verify=False)
                if r.status_code != 200:
                    logger.warning('TWSE HTTP %s, attempt %s' % (r.status_code, attempt + 1))
                    time.sleep(retry_delay)
                    continue

                text = r.text
                if len(text) < 1000:
                    logger.warning('TWSE content too short (%s bytes), attempt %s' % (len(text), attempt + 1))
                    time.sleep(retry_delay)
                    continue

                lines = text.split('\n')
                filtered = []
                for i in lines:
                    if len(i.split('",')) == 17 and i[0] != '=':
                        filtered.append(i.translate({ord(c): None for c in ' '}))

                if len(filtered) < 10:
                    logger.warning('TWSE filtered only %s lines, attempt %s' % (len(filtered), attempt + 1))
                    time.sleep(retry_delay)
                    continue

                csv_text = '\n'.join(filtered)
                df = pd.read_csv(StringIO(csv_text), header=0)
                df = df.set_index('證券代號')

                numeric_cols = ['成交股數', '成交金額', '開盤價', '最高價', '最低價', '收盤價']
                for col in numeric_cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce')

                rename_map = {
                    '證券名稱': 'name',
                    '成交股數': 'volume',
                    '成交金額': 'trade_value',
                    '開盤價': 'open',
                    '最高價': 'high',
                    '最低價': 'low',
                    '收盤價': 'close',
                }
                df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

                df = df.dropna(subset=['close', 'volume'], how='any')
                df['market'] = 'twse'
                return df

            except Exception as e:
                logger.warning('TWSE error attempt %s: %s' % (attempt + 1, e))
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    logger.error('TWSE failed after %s attempts: %s' % (max_retries, e))
                    return pd.DataFrame()

        return pd.DataFrame()

    @classmethod
    def fetch_otc(cls, date_obj, max_retries=None, retry_delay=None):
        max_retries = max_retries if max_retries is not None else cls.MAX_RETRIES
        retry_delay = retry_delay if retry_delay is not None else cls.RETRY_DELAY
        a = str(date_obj).split(' ')[0]
        year = int(a.split('-')[0]) - 1911
        month = a.split('-')[1]
        day = a.split('-')[2]
        date_str = str(year) + '/' + month + '/' + day
        url = 'https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php?l=zh-tw&o=csv&d=' + date_str + '&se=AL&s=0,asc,0'

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
        }

        for attempt in range(max_retries):
            try:
                s = requests.Session()
                r = s.post(url, headers=headers, timeout=cls.REQUEST_TIMEOUT, verify=False)
                if r.status_code != 200:
                    logger.warning('OTC HTTP %s, attempt %s' % (r.status_code, attempt + 1))
                    time.sleep(retry_delay)
                    continue

                text = r.content.decode('big5', errors='ignore')
                if len(text) < 1000:
                    logger.warning('OTC content too short (%s bytes), attempt %s' % (len(text), attempt + 1))
                    time.sleep(retry_delay)
                    continue

                lines = text.split('\n')

                header_idx = None
                for i, line in enumerate(lines):
                    if '代號' in line:
                        header_idx = i
                        break

                if header_idx is None:
                    logger.warning('OTC header not found, attempt %s' % (attempt + 1))
                    time.sleep(retry_delay)
                    continue

                data_lines = [lines[header_idx].replace('=', '')]
                for line in lines[header_idx + 1:]:
                    if line.strip() and line[0] != '=':
                        data_lines.append(line.replace('=', ''))

                if len(data_lines) < 2:
                    logger.warning('OTC no data lines, attempt %s' % (attempt + 1))
                    time.sleep(retry_delay)
                    continue

                csv_text = '\n'.join(data_lines)
                df = pd.read_csv(StringIO(csv_text), header=0)

                df.columns = df.columns.str.strip()
                rename_map = {}
                for col in df.columns:
                    col_lower = col.lower().strip()
                    if 'code' in col_lower or '代號' in col:
                        rename_map[col] = 'code'
                    elif 'name' in col_lower or '名稱' in col:
                        rename_map[col] = 'name'
                    elif col in ('收盤', 'close'):
                        rename_map[col] = 'close'
                    elif col in ('開盤', 'open'):
                        rename_map[col] = 'open'
                    elif col in ('最高', 'high'):
                        rename_map[col] = 'high'
                    elif col in ('最低', 'low'):
                        rename_map[col] = 'low'
                    elif '成交量' in col or '成交股數' in col or 'volume' in col_lower:
                        rename_map[col] = 'volume'
                    elif '成交金額' in col or 'trade_value' in col_lower:
                        rename_map[col] = 'trade_value'

                if len(rename_map) < 8:
                    logger.warning('OTC column mapping insufficient (' + str(len(rename_map)) + ' < 8)')
                    time.sleep(retry_delay)
                    continue

                df = df.rename(columns=rename_map)

                for col in ['open', 'high', 'low', 'close', 'volume', 'trade_value']:
                    if col in df.columns:
                        df[col] = df[col].astype(str).str.replace(',', '').str.strip()
                        df[col] = pd.to_numeric(df[col], errors='coerce')

                df = df.set_index('code')
                df = df[df.index.astype(str).str.match(r'^\d{4}$')]
                df = df.dropna(subset=['close', 'volume'], how='any')
                df['market'] = 'otc'
                return df

            except Exception as e:
                logger.warning('OTC error attempt %s: %s' % (attempt + 1, e))
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    logger.error('OTC failed after %s attempts: %s' % (max_retries, e))
                    return pd.DataFrame()

        return pd.DataFrame()

    @staticmethod
    def get_prev_close_map(codes, target_date):
        cleaned_codes = sorted({str(code).strip() for code in codes if str(code).strip()})
        if not cleaned_codes:
            return {}

        prev_close_subquery = DailyPrice.objects.filter(
            stock=OuterRef('pk'),
            date__lt=target_date,
        ).order_by('-date').values('close')[:1]

        rows = Stock.objects.filter(
            code__in=cleaned_codes
        ).annotate(
            prev_close=Subquery(prev_close_subquery)
        ).values_list('code', 'prev_close')

        return {
            str(code).strip(): prev_close
            for code, prev_close in rows
            if prev_close is not None
        }

    @classmethod
    def run_daily_crawl(cls, target_date=None, market='all'):
        if target_date is None:
            target_date = datetime.today().date()

        result = {
            'status': 'fail',
            'date': target_date,
            'market': market,
            'companies': 0,
            'twse_count': 0,
            'otc_count': 0,
            'reason': '',
        }

        print('開始爬取 %s 股市資料 (market=%s)...' % (target_date, market))

        twse_df = pd.DataFrame()
        otc_df = pd.DataFrame()

        if market in ('all', 'twse'):
            twse_df = cls.fetch_twse(target_date)
            result['twse_count'] = len(twse_df)
        if market in ('all', 'otc'):
            if market in ('all',):
                time.sleep(cls.TWSE_OTC_DELAY)
            otc_df = cls.fetch_otc(target_date)
            result['otc_count'] = len(otc_df)

        if twse_df.empty and otc_df.empty:
            print('%s 無交易資料 (可能是假日).' % target_date)
            result['reason'] = '無交易資料(可能是休市日)'
            return result

        twse_dropped = False
        otc_dropped = False
        if not twse_df.empty and len(twse_df) < cls.MIN_TWSE_ROWS:
            print('警告: TWSE 僅 %s 筆 (< %s), 疑似不完整, 捨棄' % (len(twse_df), cls.MIN_TWSE_ROWS))
            twse_df = pd.DataFrame()
            twse_dropped = True
        if not otc_df.empty and len(otc_df) < cls.MIN_OTC_ROWS:
            print('警告: OTC 僅 %s 筆 (< %s), 疑似不完整, 捨棄' % (len(otc_df), cls.MIN_OTC_ROWS))
            otc_df = pd.DataFrame()
            otc_dropped = True

        if twse_df.empty and otc_df.empty:
            print('%s 無有效資料 (TWSE 或 OTC 筆數不足).' % target_date)
            result['reason'] = '筆數不足(可能為半日交易或資料不完整)'
            if twse_dropped and otc_dropped:
                result['reason'] = 'TWSE+OTC筆數不足'
            elif twse_dropped:
                result['reason'] = 'TWSE筆數不足'
            elif otc_dropped:
                result['reason'] = 'OTC筆數不足'
            return result

        dfs = []
        if not twse_df.empty:
            dfs.append(twse_df)
        if not otc_df.empty:
            dfs.append(otc_df)
        df_all = pd.concat(dfs)
        df_all = df_all[df_all.index.astype(str).str.match(r'^\d{4}$')]

        crawled_codes = [str(code).strip() for code in df_all.index.unique().astype(str)]
        prev_close_map = cls.get_prev_close_map(crawled_codes, target_date)

        stocks_to_create = []
        prices_to_create = []
        existing_stocks = {
            s.code: s
            for s in Stock.objects.filter(code__in=crawled_codes)
        }

        for code, row in df_all.iterrows():
            code = str(code).strip()

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

            if pd.notna(row.get('close')):
                row_dict = {
                    'open': row.get('open'),
                    'high': row.get('high'),
                    'low': row.get('low'),
                    'close': row.get('close'),
                    'volume': row.get('volume'),
                }
                prev_close = prev_close_map.get(code)
                is_ok, reason = PriceValidator.check_jump(row_dict, prev_close)
                if not is_ok:
                    if prev_close is None:
                        anomaly_reason = '無前交易日收盤價'
                    elif prev_close <= 0:
                        anomaly_reason = '前收盤價<=0'
                    else:
                        anomaly_reason = '漲跌幅>15%%'
                    log_price_anomaly(date.today().isoformat(), str(target_date), code, str(row.get('name', '')).strip(), row['close'], float(prev_close) if prev_close and prev_close > 0 else 0, (row['close'] - float(prev_close)) / float(prev_close) if prev_close and prev_close > 0 else 0, anomaly_reason)
                    logger.warning('[%s] %s 價格異常 (仍寫入): %s' % (target_date, code, reason))

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

        if prices_to_create:
            with transaction.atomic():
                markets_to_replace = sorted(set(df_all['market'].dropna().astype(str)))

                if stocks_to_create:
                    Stock.objects.bulk_create(stocks_to_create, ignore_conflicts=True)

                existing_stocks = {
                    s.code: s
                    for s in Stock.objects.filter(code__in=crawled_codes)
                }

                for price in prices_to_create:
                    price.stock = existing_stocks.get(price.stock.code)

                prices_to_create = [p for p in prices_to_create if p.stock and p.stock.id]

                if prices_to_create:
                    DailyPrice.objects.filter(
                        date=target_date,
                        stock__market__in=markets_to_replace,
                    ).delete()
                    DailyPrice.objects.bulk_create(prices_to_create)

        result['status'] = 'success'
        result['companies'] = len(prices_to_create)

        if twse_dropped or otc_dropped:
            result['status'] = 'partial'
            parts = []
            if twse_dropped:
                parts.append('TWSE筆數不足')
            if otc_dropped:
                parts.append('OTC筆數不足')
            result['reason'] = ', '.join(parts)

        print('爬取完成! 共寫入 %s 筆股價資料.' % len(prices_to_create))
        return result
