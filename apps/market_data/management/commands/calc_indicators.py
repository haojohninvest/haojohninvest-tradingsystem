from django.core.management.base import BaseCommand
from apps.market_data.indicators import calculate_all_indicators

class Command(BaseCommand):
    help = '重新計算所有技術指標 (EMA, SMA, 偏離度等)，預設只算最近150天'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=150,
            help='回溯計算天數 (預設 150，首次跑可設大一點如 2000)'
        )
        parser.add_argument(
            '--full',
            action='store_true',
            help='全量重算所有歷史資料 (會刪除舊 Indicator)'
        )

    def handle(self, *args, **options):
        if options['full']:
            self.stdout.write('開始全量重算所有技術指標...')
            from apps.analysis.models import Indicator
            Indicator.objects.all().delete()
            calculate_all_indicators(lookback_days=9999)  # 大到足以涵蓋所有歷史
        else:
            days = options['days']
            self.stdout.write(f'開始執行技術指標計算 (最近 {days} 天)...')
            calculate_all_indicators(lookback_days=days)
        self.stdout.write(self.style.SUCCESS('技術指標計算完畢！'))
