from django.core.management.base import BaseCommand
from apps.market_data.indicators import calculate_all_indicators

class Command(BaseCommand):
    help = '重新計算所有技術指標 (EMA, SMA, 偏離度等)'

    def handle(self, *args, **options):
        self.stdout.write('開始執行技術指標計算...')
        calculate_all_indicators()
        self.stdout.write(self.style.SUCCESS('技術指標計算完畢！'))
