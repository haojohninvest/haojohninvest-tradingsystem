"""
批次執行管線命令: 給定 start_date ~ end_date，依序執行:
  1. calc_indicators     (計算技術指標)
  2. calc_market_breadth (市場寬度)
  3. calc_divergence     (族群背離)
  4. stock_pick_scanner  (選股掃描, 含 --output-db)
  5. simulate_buy_pool   (模擬漲幅選股, 含 --output-db)

使用方式:
    python manage.py run_pipeline --start_date 2025-01-02 --end_date 2026-05-29
    python manage.py run_pipeline --start_date 2025-01-02 --end_date 2026-05-29 --market_cap 200000000000 --step scanner
    python manage.py run_pipeline --start_date 2025-01-02 --end_date 2026-05-29 --simulation_pct 7.0
"""

from django.core.management.base import BaseCommand
from django.core.management import call_command
from datetime import datetime, date
import logging

logger = logging.getLogger('apps')


class Command(BaseCommand):
    help = '批次執行管線: calc_indicators → calc_market_breadth → calc_divergence → stock_pick_scanner → simulate_buy_pool'

    STEP_CHOICES = ['indicators', 'breadth', 'divergence', 'scanner', 'simulation', 'all']
    INDICATOR_BUFFER_DAYS = 60

    def add_arguments(self, parser):
        parser.add_argument(
            '--start_date',
            type=str,
            required=True,
            help='起始日期 (YYYY-MM-DD)'
        )
        parser.add_argument(
            '--end_date',
            type=str,
            required=True,
            help='結束日期 (YYYY-MM-DD)'
        )
        parser.add_argument(
            '--step',
            type=str,
            default='all',
            choices=self.STEP_CHOICES,
            help='指定只跑某一步 (預設: all)'
        )
        parser.add_argument(
            '--market_cap',
            type=float,
            default=15_000_000_000,
            help='市值門檻 (預設: 15,000,000,000 = 150億)'
        )
        parser.add_argument(
            '--r20_threshold',
            type=float,
            default=0.9,
            help='R20 門檻 (預設: 0.9)'
        )
        parser.add_argument(
            '--r20_hole_threshold',
            type=float,
            default=0.85,
            help='R20_hole 門檻 (預設: 0.85)'
        )
        parser.add_argument(
            '--output_dir',
            type=str,
            default='.',
            help='Excel 輸出目錄 (預設: 當前目錄)'
        )
        parser.add_argument(
            '--simulation_pct',
            type=float,
            default=None,
            help='模擬漲幅百分比，有提供時才會執行 simulate_buy_pool (預設: 不執行)'
        )

    def handle(self, *args, **options):
        start_date = datetime.strptime(options['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(options['end_date'], '%Y-%m-%d').date()
        step = options['step']
        market_cap = options['market_cap']
        r20_threshold = options['r20_threshold']
        r20_hole_threshold = options['r20_hole_threshold']
        output_dir = options['output_dir']
        simulation_pct = options['simulation_pct']

        total_days = (end_date - start_date).days
        indicator_days = total_days + self.INDICATOR_BUFFER_DAYS

        self.stdout.write(self.style.SUCCESS(
            f"=== Pipeline: {start_date} ~ {end_date} (共 {total_days} 天) ===\n"
            f"  指標回溯: {indicator_days} 天"
            f" | 市值門檻: {market_cap:,.0f}"
            f" | 步驟: {step}"
            + (f" | 模擬漲幅: +{simulation_pct}%" if simulation_pct else "")
        ))

        when_all = self.STEP_CHOICES[:-1]
        if simulation_pct is None:
            when_all = [s for s in when_all if s != 'simulation']
        steps_to_run = when_all if step == 'all' else [step]

        if 'indicators' in steps_to_run:
            self._run_step(
                '1/5 計算技術指標',
                'calc_indicators',
                days=indicator_days,
            )

        if 'breadth' in steps_to_run:
            self._run_step(
                '2/5 計算市場寬度',
                'calc_market_breadth',
                days=max(total_days, 1),
            )

        if 'divergence' in steps_to_run:
            self._run_step(
                '3/5 計算族群背離',
                'calc_divergence',
                days=max(total_days, 1),
            )

        if 'scanner' in steps_to_run:
            self._run_step(
                '4/5 選股掃描',
                'stock_pick_scanner',
                start_date=options['start_date'],
                end_date=options['end_date'],
                output_db=True,
                market_cap=market_cap,
                r20_threshold=r20_threshold,
                r20_hole_threshold=r20_hole_threshold,
                output_dir=output_dir,
            )

        if 'simulation' in steps_to_run and simulation_pct:
            self._run_step(
                '5/5 模擬漲幅選股',
                'simulate_buy_pool',
                start_date=options['start_date'],
                end_date=options['end_date'],
                simulation_pct=simulation_pct,
                output_db=True,
                market_cap=market_cap,
                r20_threshold=r20_threshold,
                r20_hole_threshold=r20_hole_threshold,
                output_dir=output_dir,
            )

        self.stdout.write(self.style.SUCCESS(
            f"=== Pipeline 全部完成！==="
        ))

    def _run_step(self, label, command_name, **kwargs):
        self.stdout.write(self.style.WARNING(f"\n{'─' * 60}"))
        self.stdout.write(self.style.WARNING(f"[{label}] 開始執行..."))
        self.stdout.write(f"  manage.py {command_name} " + " ".join(f"--{k}={v}" for k, v in kwargs.items()))

        try:
            call_command(command_name, **kwargs)
            self.stdout.write(self.style.SUCCESS(f"[{label}] 完成！"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"[{label}] 失敗: {e}"))
            raise
