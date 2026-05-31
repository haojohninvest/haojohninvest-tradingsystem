"""
stock_pick_scanner.py

Stock Pick Strategy v0519 Scanner
基於 stock_pick_strategy_v0519 的策略邏輯：
1. 前置篩選：市值 >= 門檻 或 CSV 白名單
2. Signal Pool：Gap (今日最低 > 昨日最高 x 1.03) 或 Surge (> 7%)
3. 情境 A/B 判斷
4. 動態 R20 窗口計算
5. Buy Pool 每日重新計算
6. 輸出 Excel (.xlsx) / DB (BuyPool table)

使用方式:
    python manage.py stock_pick_scanner --start_date 2025-01-02 --end_date 2026-05-08
    python manage.py stock_pick_scanner --start_date 2025-01-02 --end_date 2026-05-08 --stock_filter whitelist_csv --whitelist_csv ./my_stocks.csv
    python manage.py stock_pick_scanner --start_date 2025-01-02 --end_date 2026-05-08 --market_cap 200000000000 --output-db

輸出:
    buy_pool_YYYYMMDD_YYYYMMDD.xlsx
        Sheet1: Buy Pool (15 欄，原始掃描結果)
        Sheet2: Buy Pool + RS (17 欄，含 ema20_cross_date 和 first_r_date)
        Sheet3: Return Simulation (20 欄，含 sell_date, return_rate, max_drawdown)
    若使用 --output-db，同時寫入 BuyPool DB table
"""

from django.core.management.base import BaseCommand
from django.db.models import Max
from datetime import timedelta, date, datetime
import pandas as pd
import numpy as np
import os
import csv
import bisect

from apps.market_data.models import DailyPrice, Stock, StockSharesHistory
from apps.analysis.models import Indicator


class Command(BaseCommand):
    help = 'Stock Pick Strategy v0519 Scanner'

    # ====== 策略參數 (可調) ======
    DEFAULT_MARKET_CAP_THRESHOLD = 15_000_000_000  # 150億
    DEFAULT_GAP_THRESHOLD = 1.03
    DEFAULT_SURGE_THRESHOLD = 7.0
    DEFAULT_SIGNAL_POOL_MAX_DAYS = 20  # D=0~19
    DEFAULT_R20_THRESHOLD = 0.9
    DEFAULT_R20_HOLE_THRESHOLD = 0.85

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
            '--stock_filter',
            type=str,
            default='market_cap',
            choices=['market_cap', 'whitelist_csv'],
            help='股票篩選方式: market_cap (市值門檻) 或 whitelist_csv (CSV白名單) (預設: market_cap)'
        )
        parser.add_argument(
            '--market_cap',
            type=float,
            default=self.DEFAULT_MARKET_CAP_THRESHOLD,
            help=f'市值門檻，僅 --stock_filter=market_cap 時生效 (預設: {self.DEFAULT_MARKET_CAP_THRESHOLD})'
        )
        parser.add_argument(
            '--whitelist_csv',
            type=str,
            default=None,
            help='白名單 CSV 路徑 (A列為股票代碼)，僅 --stock_filter=whitelist_csv 時生效'
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
            '--r20_hole_threshold',
            type=float,
            default=self.DEFAULT_R20_HOLE_THRESHOLD,
            help=f'R20_hole門檻 (預設: {self.DEFAULT_R20_HOLE_THRESHOLD})'
        )
        parser.add_argument(
            '--output_dir',
            type=str,
            default='.',
            help='CSV 輸出目錄 (預設: 當前目錄)'
        )
        parser.add_argument(
            '--output-db',
            action='store_true',
            default=False,
            help='同時寫入 BuyPool DB table (掃描完成後)'
        )

    def handle(self, *args, **options):
        self.start_date = pd.to_datetime(options['start_date']).date()
        self.end_date = pd.to_datetime(options['end_date']).date()
        self.stock_filter = options['stock_filter']
        self.market_cap_threshold = options['market_cap']
        self.whitelist_csv_path = options['whitelist_csv']
        self.gap_threshold = options['gap_threshold']
        self.surge_threshold = options['surge_threshold']
        self.r20_threshold = options['r20_threshold']
        self.r20_hole_threshold = options['r20_hole_threshold']
        self.output_dir = options['output_dir']
        self.output_db = options['output_db']

        if self.stock_filter == 'whitelist_csv' and not self.whitelist_csv_path:
            self.stdout.write(self.style.ERROR(
                "使用 whitelist_csv 模式時必須提供 --whitelist_csv 參數"
            ))
            return

        filter_desc = (
            f"市值 >= {self.market_cap_threshold:,.0f} 元"
            if self.stock_filter == 'market_cap'
            else f"CSV 白名單: {self.whitelist_csv_path}"
        )

        self.stdout.write(self.style.SUCCESS(
            f"=== Stock Pick Strategy v0519 Scanner ===\n"
            f"日期範圍: {self.start_date} ~ {self.end_date}\n"
            f"股票篩選: {filter_desc}\n"
            f"跳空門檻: {self.gap_threshold}\n"
            f"長紅門檻: {self.surge_threshold}%\n"
            f"R20門檻: {self.r20_threshold}\n"
            f"R20_hole門檻: {self.r20_hole_threshold}\n"
        ))

        # 1. 預載資料
        self._preload_data()

        # 2. 逐日掃描
        results = self._scan_daily()

        # 3. 輸出 Excel
        self._output_csv(results)

        # 4. 輸出 DB (若啟用)
        if self.output_db:
            self._output_db(results)

        self.stdout.write(self.style.SUCCESS("掃描完成！"))

    # ====== 資料預載 ======

    def _preload_data(self):
        """預載所有需要的資料，避免逐筆查詢"""
        self.stdout.write("預載資料中...")

        # 股票基本資料
        stocks = Stock.objects.all()
        self.stock_map = {}
        self.stock_name_map = {}
        for s in stocks:
            self.stock_map[s.code] = s.id
            self.stock_name_map[s.code] = s.name

        self.stdout.write(f"  載入 {len(self.stock_map)} 支股票")

        # 建立 stock_id -> code 對照
        id_to_code = {v: k for k, v in self.stock_map.items()}

        # 股價資料 (start_date 前推 60 天 ~ 最新日期，供 R20 + R/S + 報酬模擬使用)
        preload_start = self.start_date - timedelta(days=60)
        latest_date = self._get_latest_trading_date()
        prices_qs = DailyPrice.objects.filter(
            stock_id__in=list(self.stock_map.values()),
            date__gte=preload_start,
            date__lte=latest_date
        ).order_by('date').values('stock_id', 'date', 'open', 'high', 'low', 'close', 'volume')

        self.price_df = pd.DataFrame(list(prices_qs))
        if self.price_df.empty:
            raise ValueError("沒有股價資料！")

        self.price_df['date'] = pd.to_datetime(self.price_df['date']).dt.date
        for col in ['open', 'high', 'low', 'close', 'volume']:
            self.price_df[col] = pd.to_numeric(self.price_df[col], errors='coerce')
        self.price_df['code'] = self.price_df['stock_id'].map(id_to_code)

        self.stdout.write(f"  載入 {len(self.price_df)} 筆股價")

        # 技術指標
        indicators_qs = Indicator.objects.filter(
            stock_id__in=list(self.stock_map.values()),
            date__gte=preload_start,
            date__lte=latest_date
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
        ).order_by('stock_id', 'date').values('stock_id', 'date', 'outstanding_shares')

        shares_df = pd.DataFrame(list(shares_qs))
        if not shares_df.empty:
            shares_df['outstanding_shares'] = pd.to_numeric(shares_df['outstanding_shares'], errors='coerce').fillna(0)
            shares_df['date'] = pd.to_datetime(shares_df['date']).dt.date
            self.shares_map = {}
            for sid, group in shares_df.groupby('stock_id'):
                self.shares_map[sid] = list(
                    zip(group['date'], group['outstanding_shares'])
                )
        else:
            self.shares_map = {}

        self.stdout.write(f"  載入 {len(self.shares_map)} 筆股數")

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

        # 建立 R/S 欄用的資料結構 (close + ema20)
        self._build_rs_lookup(id_to_code)

        # 建立報酬模擬用的資料結構 (close + ema20 + ema60)
        self._build_simulation_lookup(id_to_code)

        # 前置篩選：決定哪些股票能進入後續掃描
        self._build_eligible_stocks()

    def _get_latest_trading_date(self):
        latest = DailyPrice.objects.aggregate(m=Max('date'))['m']
        if latest is None:
            return self.end_date
        return max(latest, self.end_date)

    def _build_simulation_lookup(self, id_to_code):
        """建立報酬模擬用的 (date, close, ema20, ema60) 時間序列，按股票索引"""
        prices = self.price_df[['stock_id', 'code', 'date', 'close']].copy()
        indicators = self.indicator_df[['stock_id', 'code', 'date', 'ema20', 'ema60']].copy()
        merged = prices.merge(indicators, on=['stock_id', 'code', 'date'], how='left')

        self.sim_data = {}
        for (sid, code), group in merged.groupby(['stock_id', 'code']):
            group = group.sort_values('date')
            self.sim_data[str(code)] = {
                'dates': list(group['date']),
                'closes': list(group['close']),
                'ema20s': list(group['ema20']),
                'ema60s': list(group['ema60']),
            }
        self.stdout.write(f"  建立 {len(self.sim_data)} 支股票的報酬模擬快取")

    def _build_rs_lookup(self, id_to_code):
        """預先建立每支股票的 (date, close, ema20) 時間序列，供 R/S 查詢使用"""
        prices = self.price_df[['stock_id', 'code', 'date', 'close']].copy()
        indicators = self.indicator_df[['stock_id', 'code', 'date', 'ema20']].copy()
        merged = prices.merge(indicators, on=['stock_id', 'code', 'date'], how='left')

        self.rs_data = {}
        for (sid, code), group in merged.groupby(['stock_id', 'code']):
            group = group.sort_values('date')
            self.rs_data[str(code)] = {
                'dates': list(group['date']),
                'closes': list(group['close']),
                'ema20s': list(group['ema20']),
            }

        self.stdout.write(f"  建立 {len(self.rs_data)} 支股票的 R/S 查詢快取")

    def _build_eligible_stocks(self):
        """
        根據 --stock_filter 決定合格股票名單。
        - market_cap: 每個交易日的市值 >= 門檻才算合格（每日動態計算）
        - whitelist_csv: 讀取 CSV 的 A 列股票代碼，全期間固定
        """
        if self.stock_filter == 'whitelist_csv':
            self._load_whitelist()
        else:
            self._build_market_cap_eligibility()

    def _load_whitelist(self):
        """從 CSV 讀取白名單（A 列為股票代碼）"""
        whitelist_codes = set()
        try:
            with open(self.whitelist_csv_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                for row in reader:
                    if row and row[0]:
                        code = row[0].strip()
                        if code in self.stock_map:
                            whitelist_codes.add(code)
        except FileNotFoundError:
            raise FileNotFoundError(f"找不到白名單 CSV: {self.whitelist_csv_path}")

        if not whitelist_codes:
            raise ValueError(f"白名單 CSV 中沒有任何有效的股票代碼")

        self.whitelist_codes = whitelist_codes
        self.eligible_mode = 'whitelist_csv'
        self.stdout.write(f"  白名單: {len(self.whitelist_codes)} 支股票")

    def _build_market_cap_eligibility(self):
        """市值模式：為每個交易日預先計算市值，篩選合格的股票"""
        trading_dates = sorted(self.price_pivot.index)
        trading_dates = [d for d in trading_dates if self.start_date <= d <= self.end_date]

        self.eligible_by_date = {}
        total_eligible = 0

        for d in trading_dates:
            eligible = set()
            for code in self.price_pivot['close'].columns:
                if self._check_market_cap(code, d):
                    eligible.add(code)
            self.eligible_by_date[d] = eligible
            total_eligible += len(eligible)

        self.eligible_mode = 'market_cap'
        avg_eligible = total_eligible / len(trading_dates) if trading_dates else 0
        self.stdout.write(f"  市值篩選: 平均每日 {avg_eligible:.0f} 支合格股票")

    def _is_eligible(self, code, date):
        """檢查股票在特定日期是否合格"""
        if self.eligible_mode == 'whitelist_csv':
            return code in self.whitelist_codes
        else:
            return code in self.eligible_by_date.get(date, set())

    def _check_market_cap(self, code, date):
        """檢查市值 >= 門檻"""
        stock_id = self.stock_map.get(code)
        if not stock_id:
            return False

        close = self._get_price(code, date, 'close')
        shares = self._get_shares(stock_id, date)

        if not close or not shares:
            return False

        market_cap = close * shares
        return market_cap >= self.market_cap_threshold

    # ====== 逐日掃描 ======

    def _scan_daily(self):
        """逐日掃描，回傳 Buy Pool records"""
        results = []

        # Signal Pool: {code: [entry1, entry2, ...]}
        signal_pool = {}

        # 產生所有交易日列表
        trading_dates = sorted(self.price_pivot.index)
        trading_dates = [d for d in trading_dates if self.start_date <= d <= self.end_date]

        self.stdout.write(f"開始掃描 {len(trading_dates)} 個交易日...")

        for current_date in trading_dates:
            # 1. 處理 Signal Pool：移除過期的 (D >= 20)
            for code, entries in signal_pool.items():
                signal_pool[code] = [
                    e for e in entries
                    if self._trading_days_between(e['entry_date'], current_date, trading_dates) < 20
                ]
            signal_pool = {k: v for k, v in signal_pool.items() if v}

            # 2. 檢查新的 Gap/Surge（只掃描合格股票），加入 Signal Pool
            new_signals = self._find_signals(current_date, trading_dates)
            for code, signal_type in new_signals.items():
                signal_pool.setdefault(code, []).append({
                    'entry_date': current_date,
                    'signal_type': signal_type,
                })

            # 3. 對 Signal Pool 內股票檢查情境 A/B + R20
            buy_pool_today = []
            for code, entries in signal_pool.items():
                for info in entries:
                    entry_date = info['entry_date']
                    signal_type = info['signal_type']
                    d = self._trading_days_between(entry_date, current_date, trading_dates)

                    if d > 19:
                        continue

                    # 情境 A/B
                    scenario = self._check_scenario(code, current_date)
                    if scenario is None:
                        continue

                    # R20 計算
                    r20_result = self._calculate_r20(code, entry_date, current_date, d, trading_dates)
                    if r20_result is None:
                        continue
                    r20, r20_hole = r20_result
                    if r20 >= self.r20_threshold:
                        continue
                    if r20_hole >= self.r20_hole_threshold:
                        continue

                    # 從 entry_date 到 buy_pool_date 的漲幅必須 < 10%
                    close_entry = self._get_price(code, entry_date, 'close')
                    if close_entry and close_entry > 0:
                        close_t = self._get_price(code, current_date, 'close')
                        if close_t and close_t / close_entry > 1.10:
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
                        'signal_type': signal_type,
                        'entry_date': entry_date,
                        'd': d,
                        'r20': round(r20, 3),
                        'r20_hole': round(r20_hole, 3),
                        'scenario': scenario,
                        'market_cap': int(market_cap) if market_cap else 0,
                    }
                    buy_pool_today.append(record)

            # 4. 同公司只保留 A 最新的
            buy_pool_today = self._dedup_entries(buy_pool_today)
            results.extend(buy_pool_today)

        self.stdout.write(f"  Buy Pool: {len(results)} records")
        return results

    # ====== 工具函數 ======

    def _trading_days_between(self, start_date, end_date, trading_dates):
        """計算兩日期間的交易日數"""
        count = 0
        for d in trading_dates:
            if start_date <= d < end_date:
                count += 1
        return count

    def _find_signals(self, current_date, trading_dates):
        """尋找今天的 Gap 或 Surge（只針對合格股票）"""
        signals = {}

        try:
            idx = trading_dates.index(current_date)
            if idx == 0:
                return signals
            prev_date = trading_dates[idx - 1]
        except ValueError:
            return signals

        for code in self.price_pivot['close'].columns:
            if not self._is_eligible(code, current_date):
                continue

            try:
                today_low = self.price_pivot.loc[current_date, ('low', code)]
                today_close = self.price_pivot.loc[current_date, ('close', code)]
                yesterday_high = self.price_pivot.loc[prev_date, ('high', code)]
                yesterday_close = self.price_pivot.loc[prev_date, ('close', code)]

                if pd.isna(today_low) or pd.isna(yesterday_high) or pd.isna(today_close) or pd.isna(yesterday_close):
                    continue

                # Gap: 今日最低 > 昨日最高 x 1.03
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

    def _get_shares(self, stock_id, date):
        """取得 date 當天或之前最新的發行股數"""
        records = self.shares_map.get(stock_id)
        if not records:
            return 0
        result = 0
        for d, shares in records:
            if d <= date:
                result = shares
            else:
                break
        return result

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
        shares = self._get_shares(stock_id, date)
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
            return None

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

        # 額外檢查：從 entry_date 到 T-1 的所有收盤價也必須低於 Close(T)
        try:
            t_idx = trading_dates.index(current_date)
        except ValueError:
            return None
        for idx in range(entry_idx, t_idx):
            dt = trading_dates[idx]
            val = self._get_price(code, dt, 'close')
            if val and val >= close_t:
                return None

        avg = np.mean(closes)
        r20 = avg / close_t

        sorted_closes = sorted(closes)

        hole_count = max(1, int(len(sorted_closes) * 0.3))
        hole_avg = np.mean(sorted_closes[:hole_count])
        r20_hole = hole_avg / close_t

        return r20, r20_hole

    def _dedup_entries(self, records):
        """同一天 T、同公司只保留 A 最新的"""
        if not records:
            return records

        df = pd.DataFrame(records)
        df = df.sort_values('entry_date', ascending=False)
        df = df.drop_duplicates(subset=['stock_code', 'date'], keep='first')
        return df.to_dict('records')

    # ====== R / S 欄計算 ======

    def _compute_rs(self, results):
        """
        針對每一筆 Buy Pool entry：
          R欄 (ema20_cross_date)：往前找最近一次 close <= ema20 的日期（買入前）
          S欄 (first_r_date)：同一次掃描中，(stock_code, R_date) 組合首次出現標 True
        """
        if not results:
            return results

        self.stdout.write("計算 R/S 欄位中...")

        r_dates = []
        seen_pairs = set()

        for record in results:
            code = str(record['stock_code'])
            buy_date = record['date']

            r_date = self._find_last_cross_below_ema20(code, buy_date)
            r_dates.append(r_date)

        df = pd.DataFrame(results)
        df['ema20_cross_date'] = r_dates

        s_flags = []
        for _, row in df.iterrows():
            code = str(row['stock_code'])
            r_date = row['ema20_cross_date']
            pair = (code, r_date)
            if r_date is not None and pair not in seen_pairs:
                seen_pairs.add(pair)
                s_flags.append(True)
            else:
                s_flags.append(False)
        df['first_r_date'] = s_flags

        self.stdout.write(f"  R/S 計算完成 (unique pairs: {len(seen_pairs)})")
        return df.to_dict('records')

    def _find_last_cross_below_ema20(self, code, buy_date):
        """使用預載的 rs_data 往前找最近一次 close <= ema20"""
        data = self.rs_data.get(code)
        if not data:
            return None

        dates = data['dates']
        closes = data['closes']
        ema20s = data['ema20s']

        idx = bisect.bisect_left(dates, buy_date) - 1

        while idx >= 0:
            c = closes[idx]
            e = ema20s[idx]
            if c is not None and e is not None and not pd.isna(c) and not pd.isna(e):
                if float(c) <= float(e):
                    return str(dates[idx])
            elif c is not None and not pd.isna(c):
                pass
            idx -= 1

        return None

    # ====== 報酬模擬 (Sheet3) ======

    def _compute_return_simulation(self, results):
        """
        針對 Sheet1 的每一筆 Buy Pool entry（買入日 = date），模擬賣出。

        賣出邏輯：
        - 情境 B: ema20 死叉 ema60 -> 賣出
        - 情境 A:
            - ema20 > ema60: ema20 死叉 ema60 -> 賣出
            - ema20 < ema60: 等 ema20 金叉 ema60，等待期間若報酬 < -10% -> 立即賣出
                              金叉後改等死叉賣出
        - max_drawdown: 買入後到首次達 +10% 之前的最大虧損
        """
        if not results:
            self.stdout.write("  沒有 Buy Pool records，跳過報酬模擬")
            return []

        self.stdout.write("計算報酬模擬中...")

        sim_results = []
        success_count = 0

        for record in results:
            code = str(record['stock_code'])
            buy_date = record['date']
            scenario = record['scenario']

            sim = self._simulate_sell(code, buy_date, scenario)
            if sim is None:
                continue

            success_count += 1
            row = record.copy()
            row['sell_date'] = sim['sell_date']
            row['return_rate'] = sim['return_rate']
            row['max_drawdown'] = sim['max_drawdown']
            row['max_return_rate'] = sim['max_return_rate']
            sim_results.append(row)

        self.stdout.write(f"  報酬模擬完成: {success_count}/{len(results)} records")
        return sim_results

    def _simulate_sell(self, code, buy_date, scenario):
        data = self.sim_data.get(code)
        if not data:
            return None

        dates = data['dates']
        closes = data['closes']
        ema20s = data['ema20s']
        ema60s = data['ema60s']

        idx = bisect.bisect_left(dates, buy_date)
        if idx >= len(dates):
            return None

        buy_close = closes[idx]
        if buy_close is None or pd.isna(buy_close) or buy_close == 0:
            return None
        buy_close = float(buy_close)

        e20 = ema20s[idx]
        e60 = ema60s[idx]

        if e20 is None or e60 is None or pd.isna(e20) or pd.isna(e60):
            return None
        e20 = float(e20)
        e60 = float(e60)

        # 決定賣出模式
        if scenario == 'B':
            return self._find_death_cross_exit(dates, closes, ema20s, ema60s, idx, buy_close)

        if e20 > e60:
            return self._find_death_cross_exit(dates, closes, ema20s, ema60s, idx, buy_close)
        else:
            return self._find_golden_then_death_exit(dates, closes, ema20s, ema60s, idx, buy_close)

    def _find_death_cross_exit(self, dates, closes, ema20s, ema60s, start_idx, buy_close):
        """從 start_idx+1 往後找 ema20 死叉 ema60（ema20 由上往下穿 ema60）"""
        prev_e20 = ema20s[start_idx]
        prev_e60 = ema60s[start_idx]
        prev_above = prev_e20 is not None and prev_e60 is not None and not pd.isna(prev_e20) and not pd.isna(prev_e60) and float(prev_e20) > float(prev_e60)

        for i in range(start_idx + 1, len(dates)):
            c = closes[i]
            e20 = ema20s[i]
            e60 = ema60s[i]

            if c is None or pd.isna(c):
                continue
            if e20 is None or e60 is None or pd.isna(e20) or pd.isna(e60):
                continue

            sell_close = float(c)
            curr_above = float(e20) > float(e60)

            if prev_above and not curr_above:
                ret = (sell_close - buy_close) / buy_close * 100
                dd = self._compute_max_drawdown(closes, start_idx, i, buy_close)
                max_ret = self._compute_max_return_rate(closes, start_idx, i, buy_close)
                return {
                    'sell_date': str(dates[i]),
                    'return_rate': round(ret, 2),
                    'max_drawdown': round(dd, 2),
                    'max_return_rate': round(max_ret, 2),
                }

            prev_above = curr_above

        # 沒有死叉發生（資料不夠），取最後一天
        last_c = closes[-1]
        if last_c is None or pd.isna(last_c):
            return None
        last_close = float(last_c)
        ret = (last_close - buy_close) / buy_close * 100
        dd = self._compute_max_drawdown(closes, start_idx, len(closes) - 1, buy_close)
        max_ret = self._compute_max_return_rate(closes, start_idx, len(closes) - 1, buy_close)
        return {
            'sell_date': str(dates[-1]),
            'return_rate': round(ret, 2),
            'max_drawdown': round(dd, 2),
            'max_return_rate': round(max_ret, 2),
        }

    def _find_golden_then_death_exit(self, dates, closes, ema20s, ema60s, start_idx, buy_close):
        """先等 ema20 金叉 ema60，等金叉期間若報酬 < -10% 則賣出。金叉後改等死叉。"""
        for i in range(start_idx + 1, len(dates)):
            c = closes[i]
            e20 = ema20s[i]
            e60 = ema60s[i]

            if c is None or pd.isna(c):
                continue

            ret = (float(c) - buy_close) / buy_close * 100
            if ret < -10.0:
                dd = self._compute_max_drawdown(closes, start_idx, i, buy_close)
                max_ret = self._compute_max_return_rate(closes, start_idx, i, buy_close)
                return {
                    'sell_date': str(dates[i]),
                    'return_rate': round(ret, 2),
                    'max_drawdown': round(dd, 2),
                    'max_return_rate': round(max_ret, 2),
                }

            if e20 is None or e60 is None or pd.isna(e20) or pd.isna(e60):
                continue

            if float(e20) > float(e60):
                return self._find_death_cross_exit(dates, closes, ema20s, ema60s, i, buy_close)

        last_c = closes[-1]
        if last_c is None or pd.isna(last_c):
            return None
        last_close = float(last_c)
        ret = (last_close - buy_close) / buy_close * 100
        dd = self._compute_max_drawdown(closes, start_idx, len(closes) - 1, buy_close)
        max_ret = self._compute_max_return_rate(closes, start_idx, len(closes) - 1, buy_close)
        return {
            'sell_date': str(dates[-1]),
            'return_rate': round(ret, 2),
            'max_drawdown': round(dd, 2),
            'max_return_rate': round(max_ret, 2),
        }

    def _compute_max_return_rate(self, closes, start_idx, end_idx, buy_close):
        """計算從買入到賣出期間的最高報酬率 (%)"""
        max_ret = 0.0
        for i in range(start_idx + 1, end_idx + 1):
            c = closes[i]
            if c is None or pd.isna(c):
                continue
            ret = (float(c) - buy_close) / buy_close * 100
            if ret > max_ret:
                max_ret = ret
        return max_ret

    def _compute_max_drawdown(self, closes, start_idx, end_idx, buy_close):
        """計算從買入到首次達到 +10% 前的最大虧損 (%)
        如果從未達到 +10%，則取整個期間的最大虧損
        """
        min_ret = 0.0
        for i in range(start_idx + 1, end_idx + 1):
            c = closes[i]
            if c is None or pd.isna(c):
                continue
            ret = (float(c) - buy_close) / buy_close * 100
            if ret < min_ret:
                min_ret = ret
            if ret >= 10.0:
                break
        return min_ret

    # ====== 輸出 ======

    def _output_csv(self, results):
        """輸出 Excel (.xlsx) 三個工作表"""
        suffix = f"{self.start_date.strftime('%Y%m%d')}_{self.end_date.strftime('%Y%m%d')}"

        # Sheet1: 原始 Buy Pool
        df_bp = pd.DataFrame(results)

        # Sheet2: Buy Pool + RS 欄位
        results_rs = self._compute_rs(results)
        df_rs = pd.DataFrame(results_rs)

        # Sheet3: Return Simulation
        results_sim = self._compute_return_simulation(results)
        df_sim = pd.DataFrame(results_sim) if results_sim else pd.DataFrame()

        for df in [df_bp, df_rs, df_sim]:
            if df.empty:
                continue
            if 'r20' in df.columns:
                df['r20'] = df['r20'].apply(lambda x: round(x, 3) if pd.notna(x) else None)
            if 'r20_hole' in df.columns:
                df['r20_hole'] = df['r20_hole'].apply(lambda x: round(x, 3) if pd.notna(x) else None)

        filename = os.path.join(self.output_dir, f"buy_pool_{suffix}.xlsx")
        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            df_bp.to_excel(writer, sheet_name='Buy Pool', index=False)
            df_rs.to_excel(writer, sheet_name='Buy Pool RS', index=False)
            df_sim.to_excel(writer, sheet_name='Return Sim', index=False)

        self.stdout.write(self.style.SUCCESS(
            f"輸出 Buy Pool: {filename} "
            f"(Sheet1: {len(df_bp)} records, Sheet2: {len(df_rs)} records, Sheet3: {len(df_sim)} records)"
        ))

    @staticmethod
    def _to_date(val):
        """將 Timestamp / datetime 安全轉成 date，Django bulk_create 才不會報錯"""
        if val is None:
            return None
        if isinstance(val, date):
            return val
        if isinstance(val, (datetime, pd.Timestamp)):
            return val.date()
        s = str(val)
        if s in ('', 'nan', 'None', 'NaT'):
            return None
        return date.fromisoformat(s)

    def _output_db(self, results):
        """寫入 BuyPool DB table"""
        from datetime import datetime
        from apps.analysis.models import BuyPool

        scan_run_id = f"{self.start_date.strftime('%Y%m%d')}_{self.end_date.strftime('%Y%m%d')}_{datetime.now().strftime('%H%M%S')}"

        # Remove old entries for this date range before writing new ones
        BuyPool.objects.filter(scan_run_id__startswith=f"{self.start_date.strftime('%Y%m%d')}_{self.end_date.strftime('%Y%m%d')}").delete()

        # Sheet1: Buy Pool
        results_rs = self._compute_rs(results)
        results_sim = self._compute_return_simulation(results)

        sim_map = {}
        if results_sim:
            for r in results_sim:
                key = (str(r.get('date')), str(r['stock_code']))
                sim_map[key] = r

        stock_map = {s.code: s for s in Stock.objects.only('code', 'id')}

        records_to_create = []

        for record in results_rs if results_rs else results:
            key = (str(record.get('date')), str(record['stock_code']))
            sim = sim_map.get(key, {})

            stock = stock_map.get(str(record['stock_code']))

            records_to_create.append(BuyPool(
                stock=stock,
                date=self._to_date(record.get('date')),
                stock_code=str(record.get('stock_code', '')),
                stock_name=str(record.get('stock_name', '')),
                close=record.get('close'),
                volume=record.get('volume'),
                turnover=record.get('turnover'),
                ema20=record.get('ema20'),
                ema60=record.get('ema60'),
                ema120=record.get('ema120'),
                signal_type=str(record.get('signal_type', '')),
                entry_date=self._to_date(record.get('entry_date')),
                d=record.get('d'),
                r20=record.get('r20'),
                r20_hole=record.get('r20_hole'),
                scenario=str(record.get('scenario', '')),
                market_cap=record.get('market_cap'),

                ema20_cross_date=self._to_date(record.get('ema20_cross_date')),
                first_r_date=record.get('first_r_date', False),

                sell_date=self._to_date(sim.get('sell_date')),
                return_rate=sim.get('return_rate'),
                max_drawdown=sim.get('max_drawdown'),
                max_return_rate=sim.get('max_return_rate'),

                scan_run_id=scan_run_id,
            ))

        batch_size = 5000
        for i in range(0, len(records_to_create), batch_size):
            BuyPool.objects.bulk_create(records_to_create[i:i + batch_size])

        self.stdout.write(self.style.SUCCESS(
            f"寫入 BuyPool DB: {len(records_to_create)} records (scan_run_id: {scan_run_id})"
        ))
