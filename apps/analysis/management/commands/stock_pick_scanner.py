"""
stock_pick_scanner.py

Stock Pick Strategy v0519 Scanner
基於 stock_pick_strategy_v0519 的策略邏輯：
1. Signal Pool：Gap (今日最低 > 昨日最高 × 1.03) 或 Surge (> 7%)
2. 情境 A/B 判斷
3. 動態 R20 窗口計算
4. Buy Pool 每日重新計算
5. 族群橘色燈號過濾
6. 輸出 CSV

使用方式:
    python manage.py stock_pick_scanner --start_date 2025-01-02 --end_date 2026-05-08
    python manage.py stock_pick_scanner --start_date 2025-01-02 --end_date 2026-05-08 --sector_filter
"""

from django.core.management.base import BaseCommand
from django.db.models import Max
from datetime import timedelta
import pandas as pd
import numpy as np
import os

from apps.market_data.models import DailyPrice, Stock, StockSharesHistory
from apps.analysis.models import Indicator, SectorDivergence
from apps.sectors.models import StockSector


class Command(BaseCommand):
    help = 'Stock Pick Strategy v0519 Scanner'

    # ====== 策略參數 (可調) ======
    DEFAULT_MARKET = 'twse'
    DEFAULT_EXCLUDE_PATTERNS = ['*', '*-KY', '*-TW']
    DEFAULT_MARKET_CAP_THRESHOLD = 150_000_000_000  # 150億
    DEFAULT_GAP_THRESHOLD = 1.03
    DEFAULT_SURGE_THRESHOLD = 7.0
    DEFAULT_SIGNAL_POOL_MAX_DAYS = 20  # D=0~19
    DEFAULT_R20_THRESHOLD = 0.9
    DEFAULT_SECTOR_ORANGE_LOOKBACK = 5  # 交易日

    def add_arguments(self, parser):
        parser.add_argument(
            '--start_date',
            type=str,
            required=True,
            help='開始日期 (YYYY-MM-DD)'
        )
        parser.add_argument(
            '--end_date',
            type=str,
            required=True,
            help='結束日期 (YYYY-MM-DD)'
        )
        parser.add_argument(
            '--market',
            type=str,
            default=self.DEFAULT_MARKET,
            help=f'市場別 (預設: {self.DEFAULT_MARKET})'
        )
        parser.add_argument(
            '--market_cap',
            type=float,
            default=self.DEFAULT_MARKET_CAP_THRESHOLD,
            help=f'市值門檻 (預設: {self.DEFAULT_MARKET_CAP_THRESHOLD})'
        )
        parser.add_argument(
            '--gap_threshold',
            type=float,
            default=self.DEFAULT_GAP_THRESHOLD,
            help=f'跳空門檻倍數 (預設: {self.DEFAULT_GAP_THRESHOLD})'
        )
        parser.add_argument(
            '--surge_threshold',
            type=float,
            default=self.DEFAULT_SURGE_THRESHOLD,
            help=f'長紅門檻% (預設: {self.DEFAULT_SURGE_THRESHOLD})'
        )
        parser.add_argument(
            '--r20_threshold',
            type=float,
            default=self.DEFAULT_R20_THRESHOLD,
            help=f'R20門檻 (預設: {self.DEFAULT_R20_THRESHOLD})'
        )
        parser.add_argument(
            '--sector_filter',
            action='store_true',
            help='啟用族群橘色燈號過濾'
        )
        parser.add_argument(
            '--sector_lookback',
            type=int,
            default=self.DEFAULT_SECTOR_ORANGE_LOOKBACK,
            help=f'族群回溯交易日數 (預設: {self.DEFAULT_SECTOR_ORANGE_LOOKBACK})'
        )
        parser.add_argument(
            '--output_dir',
            type=str,
            default='.',
            help='CSV 輸出目錄 (預設: 當前目錄)'
        )

    def handle(self, *args, **options):
        self.start_date = pd.to_datetime(options['start_date']).date()
        self.end_date = pd.to_datetime(options['end_date']).date()
        self.market = options['market']
        self.market_cap_threshold = options['market_cap']
        self.gap_threshold = options['gap_threshold']
        self.surge_threshold = options['surge_threshold']
        self.r20_threshold = options['r20_threshold']
        self.sector_filter = options['sector_filter']
        self.sector_lookback = options['sector_lookback']
        self.output_dir = options['output_dir']

        self.stdout.write(self.style.SUCCESS(
            f"=== Stock Pick Strategy v0519 Scanner ===\n"
            f"日期範圍: {self.start_date} ~ {self.end_date}\n"
            f"市場: {self.market}\n"
            f"市值門檻: {self.market_cap_threshold:,.0f} 元\n"
            f"跳空門檻: {self.gap_threshold}\n"
            f"長紅門檻: {self.surge_threshold}%\n"
            f"R20門檻: {self.r20_threshold}\n"
            f"族群過濾: {'啟用' if self.sector_filter else '停用'}\n"
            f"族群回溯: {self.sector_lookback} 交易日\n"
        ))

        # 1. 預載資料
        self._preload_data()

        # 2. 逐日掃描
        results = self._scan_daily()

        # 3. 輸出 CSV
        self._output_csv(results)

        self.stdout.write(self.style.SUCCESS("掃描完成！"))

    # ====== 資料預載 ======

    def _preload_data(self):
        """預載所有需要的資料，避免逐筆查詢"""
        self.stdout.write("預載資料中...")

        # 股票基本資料
        stocks = Stock.objects.filter(market=self.market).exclude(
            name__in=self.DEFAULT_EXCLUDE_PATTERNS
        )
        # 簡易排除：名稱含 * 或 -KY 或 -TW
        self.stock_map = {}
        self.stock_name_map = {}
        for s in stocks:
            if '*' in s.name or s.name.endswith('-KY') or s.name.endswith('-TW'):
                continue
            self.stock_map[s.code] = s.id
            self.stock_name_map[s.code] = s.name

        self.stdout.write(f"  載入 {len(self.stock_map)} 支股票")

        # 股價資料 (start_date 前推 30 天 ~ end_date)
        preload_start = self.start_date - timedelta(days=30)
        prices_qs = DailyPrice.objects.filter(
            stock_id__in=list(self.stock_map.values()),
            date__gte=preload_start,
            date__lte=self.end_date
        ).order_by('date').values('stock_id', 'date', 'open', 'high', 'low', 'close', 'volume')

        self.price_df = pd.DataFrame(list(prices_qs))
        if self.price_df.empty:
            raise ValueError("沒有股價資料！")

        self.price_df['date'] = pd.to_datetime(self.price_df['date']).dt.date
        for col in ['open', 'high', 'low', 'close', 'volume']:
            self.price_df[col] = pd.to_numeric(self.price_df[col], errors='coerce')

        # 建立 stock_id -> code 對照
        id_to_code = {v: k for k, v in self.stock_map.items()}
        self.price_df['code'] = self.price_df['stock_id'].map(id_to_code)

        self.stdout.write(f"  載入 {len(self.price_df)} 筆股價")

        # 技術指標
        indicators_qs = Indicator.objects.filter(
            stock_id__in=list(self.stock_map.values()),
            date__gte=preload_start,
            date__lte=self.end_date
        ).values('stock_id', 'date', 'ema20', 'ema60', 'ema120')

        self.indicator_df = pd.DataFrame(list(indicators_qs))
        if not self.indicator_df.empty:
            self.indicator_df['date'] = pd.to_datetime(self.indicator_df['date']).dt.date
            for col in ['ema20', 'ema60', 'ema120']:
                self.indicator_df[col] = pd.to_numeric(self.indicator_df[col], errors='coerce')
            self.indicator_df['code'] = self.indicator_df['stock_id'].map(id_to_code)

        self.stdout.write(f"  載入 {len(self.indicator_df)} 筆技術指標")

        # 發行股數快取
        shares_qs = StockSharesHistory.objects.filter(
            stock_id__in=list(self.stock_map.values()),
            date__lte=self.end_date
        ).order_by('stock_id', '-date').values('stock_id', 'date', 'outstanding_shares')

        shares_df = pd.DataFrame(list(shares_qs))
        if not shares_df.empty:
            shares_df['outstanding_shares'] = pd.to_numeric(shares_df['outstanding_shares'], errors='coerce').fillna(0)
            # 對每個 stock_id 保留最新的
            self.shares_map = {}
            for sid, group in shares_df.groupby('stock_id'):
                self.shares_map[sid] = group.iloc[0]['outstanding_shares']
        else:
            self.shares_map = {}

        self.stdout.write(f"  載入 {len(self.shares_map)} 筆股數")

        # 族群對照
        sector_qs = StockSector.objects.select_related('sector').values('stock_id', 'sector__name')
        self.stock_to_sector = {}
        for row in sector_qs:
            code = id_to_code.get(row['stock_id'])
            if code:
                self.stock_to_sector[code] = row['sector__name']

        self.stdout.write(f"  載入 {len(self.stock_to_sector)} 筆族群對照")

        # 族群背離橘色燈號 (預載全部，因為數量不多)
        if self.sector_filter:
            div_qs = SectorDivergence.objects.filter(
                sector_name__in=set(self.stock_to_sector.values()),
                is_orange=True,
                date__gte=self.start_date - timedelta(days=30),
                date__lte=self.end_date
            ).values('date', 'sector_name')

            self.orange_df = pd.DataFrame(list(div_qs))
            if not self.orange_df.empty:
                self.orange_df['date'] = pd.to_datetime(self.orange_df['date']).dt.date
            else:
                self.orange_df = pd.DataFrame(columns=['date', 'sector_name'])

            self.stdout.write(f"  載入 {len(self.orange_df)} 筆橘色燈號")

        # 建立 Pivot：每個股票每天的 close/high/low
        self.price_pivot = self.price_df.pivot_table(
            index='date', columns='code', values=['open', 'high', 'low', 'close', 'volume']
        )

        # 建立 indicator pivot
        if not self.indicator_df.empty:
            self.indicator_pivot = self.indicator_df.pivot_table(
                index='date', columns='code', values=['ema20', 'ema60', 'ema120']
            )
        else:
            self.indicator_pivot = None

    # ====== 逐日掃描 ======

    def _scan_daily(self):
        """逐日掃描，回傳 Buy Pool records"""
        results = []
        sector_results = []

        # Signal Pool: {code: entry_date}
        signal_pool = {}

        # 產生所有交易日列表
        trading_dates = sorted(self.price_pivot.index)
        trading_dates = [d for d in trading_dates if self.start_date <= d <= self.end_date]

        self.stdout.write(f"開始掃描 {len(trading_dates)} 個交易日...")

        for current_date in trading_dates:
            # 1. 處理 Signal Pool：移除過期的 (D >= 20)
            to_remove = []
            for code, info in signal_pool.items():
                entry_date = info['entry_date']
                d = self._trading_days_between(entry_date, current_date, trading_dates)
                if d >= 20:
                    to_remove.append(code)
            for code in to_remove:
                del signal_pool[code]

            # 2. 檢查新的 Gap/Surge，加入 Signal Pool
            new_signals = self._find_signals(current_date, trading_dates)
            for code, signal_type in new_signals.items():
                # 市值檢查
                if not self._check_market_cap(code, current_date):
                    continue
                signal_pool[code] = {
                    'entry_date': current_date,
                    'signal_type': signal_type,
                }

            # 3. 對 Signal Pool 內股票檢查情境 A/B + R20
            buy_pool_today = []
            for code, info in signal_pool.items():
                entry_date = info['entry_date']
                signal_type = info['signal_type']
                d = self._trading_days_between(entry_date, current_date, trading_dates)

                if d > 19:
                    continue  # 已過期，但應該上面已移除

                # 情境 A/B
                scenario = self._check_scenario(code, current_date)
                if scenario is None:
                    continue

                # R20 計算
                r20 = self._calculate_r20(code, entry_date, current_date, d, trading_dates)
                if r20 is None or r20 > self.r20_threshold:
                    continue

                # 通過！組成 Buy Pool record
                close = self._get_price(code, current_date, 'close')
                volume = self._get_price(code, current_date, 'volume')
                ema20 = self._get_indicator(code, current_date, 'ema20')
                ema60 = self._get_indicator(code, current_date, 'ema60')
                ema120 = self._get_indicator(code, current_date, 'ema120')
                market_cap = self._get_market_cap(code, current_date)

                record = {
                    'date': current_date,
                    'stock_code': code,
                    'stock_name': self.stock_name_map.get(code, ''),
                    'close': close,
                    'volume': volume,
                    'turnover': round(close * volume / 100_000_000, 2) if close and volume else 0,
                    'ema20': ema20,
                    'ema60': ema60,
                    'ema120': ema120,
                    'signal_type': info['signal_type'],
                    'entry_date': entry_date,
                    'd': d,
                    'r20': round(r20, 3) if r20 else None,
                    'scenario': scenario,
                    'market_cap': int(market_cap) if market_cap else 0,
                }
                buy_pool_today.append(record)

            # 4. 同公司只保留 A 最新的
            buy_pool_today = self._dedup_entries(buy_pool_today)
            results.extend(buy_pool_today)

            # 5. 族群過濾
            if self.sector_filter:
                sector_records = self._apply_sector_filter(buy_pool_today, current_date)
                sector_results.extend(sector_records)

        self.stdout.write(f"  Buy Pool: {len(results)} records")
        if self.sector_filter:
            self.stdout.write(f"  Sector Buy Pool: {len(sector_results)} records")

        return {'buy_pool': results, 'sector_buy_pool': sector_results}

    # ====== 工具函數 ======

    def _trading_days_between(self, start_date, end_date, trading_dates):
        """計算兩日期間的交易日數"""
        count = 0
        for d in trading_dates:
            if start_date <= d < end_date:
                count += 1
        return count

    def _find_signals(self, current_date, trading_dates):
        """尋找今天的 Gap 或 Surge"""
        signals = {}

        # 找到昨天的索引
        try:
            idx = trading_dates.index(current_date)
            if idx == 0:
                return signals  # 第一天沒有昨天
            prev_date = trading_dates[idx - 1]
        except ValueError:
            return signals

        for code in self.price_pivot['close'].columns:
            try:
                today_low = self.price_pivot.loc[current_date, ('low', code)]
                today_close = self.price_pivot.loc[current_date, ('close', code)]
                yesterday_high = self.price_pivot.loc[prev_date, ('high', code)]
                yesterday_close = self.price_pivot.loc[prev_date, ('close', code)]

                if pd.isna(today_low) or pd.isna(yesterday_high) or pd.isna(today_close) or pd.isna(yesterday_close):
                    continue

                # Gap: 今日最低 > 昨日最高 × 1.03
                if today_low > yesterday_high * self.gap_threshold:
                    signals[code] = 'gap'
                    continue

                # Surge: (今日收盤 - 昨日收盤) / 昨日收盤 > 7%
                change_pct = (today_close - yesterday_close) / yesterday_close * 100
                if change_pct > self.surge_threshold:
                    signals[code] = 'surge'

            except KeyError:
                continue

        return signals

    def _check_market_cap(self, code, current_date):
        """檢查市值 >= 門檻"""
        stock_id = self.stock_map.get(code)
        if not stock_id:
            return False

        close = self._get_price(code, current_date, 'close')
        shares = self.shares_map.get(stock_id, 0)

        if not close or not shares:
            return False

        market_cap = close * shares
        return market_cap >= self.market_cap_threshold

    def _get_price(self, code, date, field):
        """取得指定股票某日的價格"""
        try:
            val = self.price_pivot.loc[date, (field, code)]
            return float(val) if pd.notna(val) else None
        except KeyError:
            return None

    def _get_indicator(self, code, date, field):
        """取得技術指標"""
        if self.indicator_pivot is None:
            return None
        try:
            val = self.indicator_pivot.loc[date, (field, code)]
            return float(val) if pd.notna(val) else None
        except KeyError:
            return None

    def _get_market_cap(self, code, date):
        """取得市值"""
        stock_id = self.stock_map.get(code)
        close = self._get_price(code, date, 'close')
        shares = self.shares_map.get(stock_id, 0)
        if close and shares:
            return close * shares
        return 0

    def _check_scenario(self, code, current_date):
        """檢查情境 A 或 B"""
        ema20 = self._get_indicator(code, current_date, 'ema20')
        ema60 = self._get_indicator(code, current_date, 'ema60')
        ema120 = self._get_indicator(code, current_date, 'ema120')

        if ema20 is None or ema60 is None or ema120 is None:
            return None

        # 情境 A: EMA120 < EMA60
        if ema120 < ema60:
            return 'A'

        # 情境 B: EMA120 > EMA60 且 EMA20 > EMA60
        if ema120 > ema60 and ema20 > ema60:
            return 'B'

        return None

    def _calculate_r20(self, code, entry_date, current_date, d, trading_dates):
        """計算動態 R20"""
        # 找到 entry_date 在 trading_dates 中的索引
        try:
            entry_idx = trading_dates.index(entry_date)
        except ValueError:
            return None

        # 終點 = A-1 (入池前一天)
        end_idx = entry_idx - 1
        if end_idx < 0:
            return None

        # 起點 = A - (20 - D)
        window_size = 20 - d
        start_idx = entry_idx - window_size
        if start_idx < 0:
            return None  # 資料不足

        # 取收盤價
        closes = []
        for idx in range(start_idx, end_idx + 1):
            dt = trading_dates[idx]
            val = self._get_price(code, dt, 'close')
            if val:
                closes.append(val)

        if len(closes) == 0:
            return None

        close_t = self._get_price(code, current_date, 'close')
        if not close_t or close_t == 0:
            return None

        # Strict R20: every close in window must be < close_t
        for c in closes:
            if c >= close_t:
                return None

        avg = np.mean(closes)

        return avg / close_t

    def _dedup_entries(self, records):
        """同一天 T、同公司只保留 A 最新的"""
        if not records:
            return records

        df = pd.DataFrame(records)
        # 按 stock_code + date 分組，取 entry_date 最新的
        df = df.sort_values('entry_date', ascending=False)
        df = df.drop_duplicates(subset=['stock_code', 'date'], keep='first')
        return df.to_dict('records')

    def _apply_sector_filter(self, buy_pool_records, current_date):
        """族群橘色燈號過濾"""
        results = []

        if self.orange_df.empty:
            return results

        # 建立每個族群的橘色日期集合
        sector_orange = {}
        for _, row in self.orange_df.iterrows():
            sname = row['sector_name']
            date = row['date']
            if sname not in sector_orange:
                sector_orange[sname] = set()
            sector_orange[sname].add(date)

        for record in buy_pool_records:
            code = record['stock_code']
            sector_name = self.stock_to_sector.get(code)
            if not sector_name:
                continue

            orange_dates = sector_orange.get(sector_name, set())
            if not orange_dates:
                continue

            # 檢查最近 N 個交易日
            found = False
            found_date = None
            days_since = None

            # 找最近的橘燈日期
            for lb in range(self.sector_lookback + 1):
                check_date = current_date - timedelta(days=lb)
                if check_date in orange_dates:
                    found = True
                    found_date = check_date
                    days_since = lb
                    break

            if found:
                rec = record.copy()
                rec['sector_name'] = sector_name
                rec['sector_orange_date'] = found_date
                rec['days_since_orange'] = days_since
                results.append(rec)

        return results

    # ====== CSV 輸出 ======

    def _output_csv(self, results):
        """輸出 CSV"""
        suffix = f"{self.start_date.strftime('%Y%m%d')}_{self.end_date.strftime('%Y%m%d')}"

        # Buy Pool CSV
        bp = results['buy_pool']
        if bp:
            df = pd.DataFrame(bp)
            filename = os.path.join(self.output_dir, f"buy_pool_{suffix}.csv")
            df.to_csv(filename, index=False, encoding='utf-8-sig')
            self.stdout.write(self.style.SUCCESS(f"輸出 Buy Pool: {filename} ({len(df)} records)"))

        # Sector Buy Pool CSV
        sbp = results['sector_buy_pool']
        if sbp:
            df = pd.DataFrame(sbp)
            filename = os.path.join(self.output_dir, f"sector_buy_pool_{suffix}.csv")
            df.to_csv(filename, index=False, encoding='utf-8-sig')
            self.stdout.write(self.style.SUCCESS(f"輸出 Sector Buy Pool: {filename} ({len(df)} records)"))
