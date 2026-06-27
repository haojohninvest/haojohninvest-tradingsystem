"""
simulate_buy_pool.py

模擬全市場股票上漲 N% 後，哪些股票會入選 Buy Pool。
完全繼承 stock_pick_scanner.Command，只覆寫關鍵方法來套用漲幅模擬。

使用方式:
    python manage.py simulate_buy_pool --simulate_date 2025-06-25 --simulation_pct 7.0
    python manage.py simulate_buy_pool --start_date 2025-01-02 --end_date 2025-06-25 --simulation_pct 7.0

輸出:
    buy_pool_sim_7pct_20250625_20250625.xlsx
    若使用 --output-db，同時寫入 BuyPoolSimulation DB table
"""

from django.core.management.base import BaseCommand
from datetime import timedelta
import pandas as pd
import numpy as np
import os

from apps.analysis.management.commands.stock_pick_scanner import Command as BaseScanner


class Command(BaseScanner):
    help = '模擬全市場漲 N% 後的 Buy Pool 入選情況'

    def add_arguments(self, parser):
        super().add_arguments(parser)
        for action in parser._actions:
            if action.dest in ('start_date', 'end_date'):
                action.required = False
        parser.add_argument(
            '--simulate_date',
            type=str,
            default=None,
            help='模擬單一日期 (YYYY-MM-DD)，提供此參數時忽略 --start_date/--end_date'
        )
        parser.add_argument(
            '--simulation_pct',
            type=float,
            default=7.0,
            help='模擬漲幅百分比 (預設: 7.0)'
        )

    def handle(self, *args, **options):
        from datetime import date

        self.simulation_pct = options.get('simulation_pct', 7.0)

        simulate_date = options.get('simulate_date')
        if simulate_date:
            self.sim_date = pd.to_datetime(simulate_date).date()
            options['start_date'] = self.sim_date.isoformat()
            options['end_date'] = self.sim_date.isoformat()
        else:
            self.sim_date = None

        required_args = ['start_date', 'end_date']
        for arg in required_args:
            if not options.get(arg):
                self.stdout.write(self.style.ERROR(
                    f"必須提供 --{arg.replace('_', '-')} 或 --simulate-date"
                ))
                return

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
            f"=== 模擬選股掃描 ===\n"
            f"日期範圍: {self.start_date} ~ {self.end_date}\n"
            f"模擬漲幅: +{self.simulation_pct}%\n"
            f"股票篩選: {filter_desc}\n"
            f"跳空門檻: {self.gap_threshold}\n"
            f"長紅門檻: {self.surge_threshold}%\n"
            f"R20門檻: {self.r20_threshold}\n"
            f"R20_hole門檻: {self.r20_hole_threshold}\n"
        ))

        self._preload_data()

        self._apply_simulation()

        self._full_trading_dates = sorted(self.price_pivot.index)

        results = self._scan_daily()

        self._output_csv(results)

        if self.output_db:
            self._output_db(results)

        self.stdout.write(self.style.SUCCESS("模擬掃描完成！"))

    def _apply_simulation(self):
        """對模擬日期範圍內的價格 pivot 套用漲幅，並重算 EMA"""
        multiplier = 1 + self.simulation_pct / 100
        trading_dates = sorted(self.price_pivot.index)

        sim_dates = [
            d for d in trading_dates
            if self.start_date <= d <= self.end_date
        ]

        for sim_date in sim_dates:
            self.stdout.write(f"  套用模擬: {sim_date} (×{multiplier:.4f})")

            for field in ['open', 'high', 'low', 'close']:
                cols = self.price_pivot.columns[
                    self.price_pivot.columns.get_level_values(0) == field
                ]
                if len(cols) > 0:
                    self.price_pivot.loc[sim_date, cols] = (
                        self.price_pivot.loc[sim_date, cols] * multiplier
                    )

            self._recalc_simulated_ema(sim_date, trading_dates)

    def _recalc_simulated_ema(self, sim_date, trading_dates):
        """使用模擬收盤價重算當天的 EMA20/60/120"""
        idx = trading_dates.index(sim_date)
        if idx == 0:
            return
        prev_date = trading_dates[idx - 1]

        if prev_date not in self.indicator_pivot.index:
            return

        close_cols = self.price_pivot.columns[
            self.price_pivot.columns.get_level_values(0) == 'close'
        ]

        k20, k60, k120 = 2 / 21, 2 / 61, 2 / 121

        for field, k in [('ema20', k20), ('ema60', k60), ('ema120', k120)]:
            cols = self.indicator_pivot.columns[
                self.indicator_pivot.columns.get_level_values(0) == field
            ]
            prev_vals = self.indicator_pivot.loc[prev_date, cols].values
            sim_close_vals = self.price_pivot.loc[sim_date, close_cols].values
            sim_vals = sim_close_vals * k + prev_vals * (1 - k)
            self.indicator_pivot.loc[sim_date, cols] = sim_vals

    @property
    def _full_dates(self):
        return sorted(self.price_pivot.index)

    def _find_signals(self, current_date, trading_dates):
        return super()._find_signals(current_date, self._full_dates)

    def _calculate_r20(self, code, entry_date, current_date, d, trading_dates):
        return super()._calculate_r20(code, entry_date, current_date, d, self._full_dates)

    def _trading_days_between(self, start_date, end_date, trading_dates):
        return super()._trading_days_between(start_date, end_date, self._full_dates)

    def _output_csv(self, results):
        """輸出模擬結果 Excel"""
        suffix = (
            f"sim_{self.simulation_pct:.0f}pct_"
            f"{self.start_date.strftime('%Y%m%d')}_{self.end_date.strftime('%Y%m%d')}"
        )

        df_bp = pd.DataFrame(results)
        results_rs = self._compute_rs(results)
        df_rs = pd.DataFrame(results_rs)
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
            f"輸出模擬結果: {filename} "
            f"(Sheet1: {len(df_bp)} records, Sheet2: {len(df_rs)} records, Sheet3: {len(df_sim)} records)"
        ))

    def _output_db(self, results):
        """寫入 BuyPoolSimulation DB table"""
        from datetime import datetime
        from apps.analysis.models import BuyPoolSimulation, Stock

        scan_run_id = (
            f"sim_{self.simulation_pct:.0f}pct_"
            f"{self.start_date.strftime('%Y%m%d')}_{self.end_date.strftime('%Y%m%d')}_"
            f"{datetime.now().strftime('%H%M%S')}"
        )

        BuyPoolSimulation.objects.filter(
            scan_run_id__startswith=(
                f"sim_{self.simulation_pct:.0f}pct_"
                f"{self.start_date.strftime('%Y%m%d')}_{self.end_date.strftime('%Y%m%d')}"
            )
        ).delete()

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

            records_to_create.append(BuyPoolSimulation(
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

                simulation_pct=self.simulation_pct,
                simulated_date=self.sim_date if self.sim_date else self.start_date,

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
            BuyPoolSimulation.objects.bulk_create(records_to_create[i:i + batch_size])

        self.stdout.write(self.style.SUCCESS(
            f"寫入 BuyPoolSimulation DB: {len(records_to_create)} records "
            f"(scan_run_id: {scan_run_id})"
        ))
