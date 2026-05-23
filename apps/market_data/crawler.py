import requests
import urllib3
import pandas as pd
from io import StringIO
from datetime import datetime
import time
import logging
from .validators import PriceValidator
from .models import Stock, DailyPrice

# Ting Yong SSL Ping Zheng Jing Gao (Zheng Jiao Suo Wang Zhan You Shi Ping Zheng Yi Chang)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


class MarketCrawler:
    """TWSE Yu OTC Pa Chong: He Bing Johnny Yuan Shi Luo Ji + Yuan You DB Xie Ru"""

    # ------------------------------------------------------------------
    # TWSE: Yong Johnny "17 Lan Wei Guo Lu" Ce Lue
    # ------------------------------------------------------------------
    @staticmethod
    def fetch_twse(date_obj, max_retries=2, retry_delay=10):
        """Pa Qu Shang Shi Gu Piao Mei Ri Shou Pan Hang Qing"""
        date_str = str(date_obj).split(' ')[0].replace('-', '')
        url = 'https://www.twse.com.tw/exchangeReport/MI_INDEX?response=csv&date=' + date_str + '&type=ALL'

        for attempt in range(max_retries):
            try:
                r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30, verify=False)
                if r.status_code != 200:
                    logger.warning('TWSE HTTP %s, attempt %s' % (r.status_code, attempt + 1))
                    time.sleep(retry_delay)
                    continue

                text = r.text
                if len(text) < 1000:
                    logger.warning('TWSE content too short (%s bytes), attempt %s' % (len(text), attempt + 1))
                    time.sleep(retry_delay)
                    continue

                # Johnny He Xin: 17 Lan Wei + Bu Yi = Kai Tou
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

                # Zhuan Huan Shu Zi (Xian Qu Dou Hao)
                numeric_cols = ['成交股數', '成交金額', '開盤價', '最高價', '最低價', '收盤價']
                for col in numeric_cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce')

                # Chong Ming Wei Ying Wen (Yu DB Yi Zhi)
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

                # Qu Diao Wu Xiao Shu Ju
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

    # ------------------------------------------------------------------
    # OTC: Yong Wei Zhi Chong Ming + Big5 Jie Ma
    # ------------------------------------------------------------------
    @staticmethod
    def fetch_otc(date_obj, max_retries=2, retry_delay=10):
        """Pa Qu Shang Gui Gu Piao Mei Ri Shou Pan Hang Qing"""
        a = str(date_obj).split(' ')[0]
        year = int(a.split('-')[0]) - 1911
        month = a.split('-')[1]
        day = a.split('-')[2]
        date_str = str(year) + '/' + month + '/' + day
        url = 'https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php?l=zh-tw&o=csv&d=' + date_str + '&se=AL&s=0,asc,0'

        for attempt in range(max_retries):
            try:
                r = requests.post(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30, verify=False)
                if r.status_code != 200:
                    logger.warning('OTC HTTP %s, attempt %s' % (r.status_code, attempt + 1))
                    time.sleep(retry_delay)
                    continue

                # OTC Shi Yong Big5/MS950 Bian Ma
                text = r.content.decode('big5', errors='ignore')
                if len(text) < 1000:
                    logger.warning('OTC content too short (%s bytes), attempt %s' % (len(text), attempt + 1))
                    time.sleep(retry_delay)
                    continue

                lines = text.split('\n')

                # Zhao Header (Han You 'Dai Hao' De Na Hang)
                header_idx = None
                for i, line in enumerate(lines):
                    if '代號' in line:
                        header_idx = i
                        break

                if header_idx is None:
                    logger.warning('OTC header not found, attempt %s' % (attempt + 1))
                    time.sleep(retry_delay)
                    continue

                # Zhi Qu Header + Data, Qu Diao =
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

                # Yong Lan Wei Ming Cheng Dui Ying (Bu Zai Yong Wei Zhi)
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

                # Qing Chu Dou Hao Hou Zhuan Huan Shu Zi
                for col in ['open', 'high', 'low', 'close', 'volume', 'trade_value']:
                    if col in df.columns:
                        df[col] = df[col].astype(str).str.replace(',', '').str.strip()
                        df[col] = pd.to_numeric(df[col], errors='coerce')

                df = df.set_index('code')

                # Zhi Bao Liu 4 Ma Shu Zi Pu Tong Gu
                df = df[df.index.astype(str).str.match(r'^\d{4}$')]

                # Qu Diao Guan Bi Jia Wei 0 De (Xiu Shi Ri)
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

    # ------------------------------------------------------------------
    # Mei Ri Pa Qu Bing Xie Ru DB (Bao Chi Yuan You Luo Ji)
    # ------------------------------------------------------------------
    @classmethod
    def run_daily_crawl(cls, target_date=None):
        """Zhi Xing Mei Ri Pa Qu, Bing Jiang Zi Liao Xie Ru DB"""
        if target_date is None:
            target_date = datetime.today().date()

        print('Kai Shi Pa Qu %s Gu Shi Zi Liao...' % target_date)

        twse_df = cls.fetch_twse(target_date)
        time.sleep(3)  # Bi Kai Bei Feng Suo
        otc_df = cls.fetch_otc(target_date)

        if twse_df.empty and otc_df.empty:
            print('%s Wu Jiao Yi Zi Liao (Ke Neng Shi Jia Ri).' % target_date)
            return

        MIN_TWSE_ROWS = 500
        MIN_OTC_ROWS = 300

        if not twse_df.empty and len(twse_df) < MIN_TWSE_ROWS:
            print('Jing Gao: TWSE Jin %s Bi (< %s), Yi Si Bu Wan Zheng, She Qi' % (len(twse_df), MIN_TWSE_ROWS))
            twse_df = pd.DataFrame()
        if not otc_df.empty and len(otc_df) < MIN_OTC_ROWS:
            print('Jing Gao: OTC Jin %s Bi (< %s), Yi Si Bu Wan Zheng, She Qi' % (len(otc_df), MIN_OTC_ROWS))
            otc_df = pd.DataFrame()

        if twse_df.empty and otc_df.empty:
            print('%s Wu You Xiao Zi Liao (TWSE Huo OTC Bi Shu Bu Zu).' % target_date)
            return

        # He Bing Shang Shi + Shang Gui
        df_all = pd.concat([twse_df, otc_df])

        # Zhi Bao Liu You 4 Ma Shu Zi De Pu Tong Gu
        df_all = df_all[df_all.index.astype(str).str.match(r'^\d{4}$')]

        stocks_to_create = []
        prices_to_create = []
        existing_stocks = {s.code: s for s in Stock.objects.all()}

        for code, row in df_all.iterrows():
            code = str(code).strip()

            # Jian Li Huo Geng Xin Stock
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

            # Zhun Bei DailyPrice
            if pd.notna(row.get('close')):
                row_dict = {
                    'open': row.get('open'),
                    'high': row.get('high'),
                    'low': row.get('low'),
                    'close': row.get('close'),
                    'volume': row.get('volume'),
                }
                prev_close = PriceValidator.get_prev_close(code, target_date)
                is_ok, reason = PriceValidator.check_jump(row_dict, prev_close)
                if not is_ok:
                    from apps.market_data.validators import log_price_anomaly
                    log_price_anomaly(str(target_date), code, str(row.get('name', '')).strip(), row['close'], float(prev_close) if prev_close else 0, (row['close'] - float(prev_close)) / float(prev_close) if prev_close else 0)
                    logger.warning('[%s] %s Jia Ge Yi Chang (reng xie ru): %s' % (target_date, code, reason))

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

        # Pi Ci Xie Ru Shu Ju Ku
        if stocks_to_create:
            Stock.objects.bulk_create(stocks_to_create, ignore_conflicts=True)
            existing_stocks = {s.code: s for s in Stock.objects.filter(code__in=df_all.index.unique().astype(str))}
            for price in prices_to_create:
                price.stock = existing_stocks.get(price.stock.code)

        if prices_to_create:
            prices_to_create = [p for p in prices_to_create if p.stock and p.stock.id]
            DailyPrice.objects.filter(date=target_date).delete()
            DailyPrice.objects.bulk_create(prices_to_create)

        print('Pa Qu Wan Cheng! Gong Xie Ru %s Bi Gu Jia Zi Liao.' % len(prices_to_create))
