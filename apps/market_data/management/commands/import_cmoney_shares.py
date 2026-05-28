import pandas as pd
from datetime import date
from calendar import monthrange
from django.core.management.base import BaseCommand
from apps.market_data.models import Stock, StockSharesHistory


QUARTER_LAST_DAY = {
    1: (3, 31),
    2: (6, 30),
    3: (9, 30),
    4: (12, 31),
}

CMONEY_FILE = r'C:\Users\user\OneDrive\豪強資本交易系統\股本_20260526.xlsx'

Q_MAP = [
    (2022, 1), (2022, 2), (2022, 3), (2022, 4),
    (2023, 1), (2023, 2), (2023, 3), (2023, 4),
    (2024, 1), (2024, 2), (2024, 3), (2024, 4),
    (2025, 1), (2025, 2), (2025, 3), (2025, 4),
    (2026, 1),
]


def quarter_date(year, quarter):
    month, day = QUARTER_LAST_DAY[quarter]
    max_day = monthrange(year, month)[1]
    return date(year, month, min(day, max_day))


class Command(BaseCommand):
    help = '從 CMoney Excel 匯入股本資料到 StockSharesHistory（每季最後一天為 date）'

    def add_arguments(self, parser):
        parser.add_argument('--file', type=str, default=CMONEY_FILE,
                            help='CMoney Excel 檔案路徑')
        parser.add_argument('--dry-run', action='store_true',
                            help='僅預覽不寫入 DB')

    def handle(self, *args, **options):
        filepath = options['file']
        dry_run = options['dry_run']

        self.stdout.write(f'讀取: {filepath}')
        df = pd.read_excel(filepath, header=None)

        data_rows = df.iloc[4:]

        code_map = {s.code: s for s in Stock.objects.all()}
        self.stdout.write(f'DB 中有 {len(code_map)} 檔股票')

        to_create = []
        skipped_no_stock = 0
        skipped_no_value = 0

        for _, row in data_rows.iterrows():
            code_str = str(row.iloc[0]).strip().zfill(4)
            if code_str == 'nan' or code_str == '':
                continue

            stock = code_map.get(code_str)
            if not stock:
                skipped_no_stock += 1
                continue

            for col_idx, (year, quarter) in enumerate(Q_MAP):
                val = row.iloc[2 + col_idx]
                if pd.isna(val):
                    skipped_no_value += 1
                    continue

                try:
                    shares = int(float(val) * 100)
                except (ValueError, TypeError):
                    skipped_no_value += 1
                    continue

                to_create.append(StockSharesHistory(
                    stock=stock,
                    date=quarter_date(year, quarter),
                    outstanding_shares=shares,
                    source='CMoney',
                ))

        if dry_run:
            for obj in to_create[:50]:
                self.stdout.write(
                    f'  {obj.stock.code} {obj.stock.name} | {obj.date} | '
                    f'{obj.outstanding_shares:>12,} 千股 | {obj.source}'
                )
            self.stdout.write(
                f'\n共 {len(to_create)} 筆，'
                f'跳過 {skipped_no_stock} 筆(無對應股票)，'
                f'跳過 {skipped_no_value} 筆(無數值)'
            )
            return

        self.stdout.write(f'準備寫入 {len(to_create)} 筆...')

        deleted, _ = StockSharesHistory.objects.filter(source='CMoney').delete()
        self.stdout.write(f'刪除舊 CMoney 資料 {deleted} 筆')

        StockSharesHistory.objects.bulk_create(to_create)

        total = StockSharesHistory.objects.filter(source='CMoney').count()
        self.stdout.write(self.style.SUCCESS(
            f'完成！CMoney 來源共 {total} 筆，'
            f'跳過 {skipped_no_stock} 筆(無對應股票)，'
            f'跳過 {skipped_no_value} 筆(無數值)'
        ))
