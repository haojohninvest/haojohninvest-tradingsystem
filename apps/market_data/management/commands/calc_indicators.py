from django.core.management.base import BaseCommand
from apps.market_data.indicators import calculate_all_indicators

class Command(BaseCommand):
    help = '計算技術指標 (EMA, SMA, 漲跌幅)，預設覆蓋最近14天'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=14,
            help='覆蓋最近 N 天 (預設 14，約 10 個交易日)'
        )
        parser.add_argument(
            '--full',
            action='store_true',
            help='全量首次重算 (清空 Indicator 後從頭計算)'
        )

    def handle(self, *args, **options):
        if options['full']:
            self.stdout.write('開始全量重算所有技術指標...')
            from apps.analysis.models import Indicator
            Indicator.objects.all().delete()
            calculate_all_indicators(lookback_days=9999)
        else:
            days = options['days']
            self.stdout.write(f'開始計算技術指標 (覆蓋最近 {days} 天)...')
            calculate_all_indicators(lookback_days=days)
        self.stdout.write(self.style.SUCCESS('技術指標計算完畢！'))
