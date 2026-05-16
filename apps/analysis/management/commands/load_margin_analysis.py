import csv
import os
from pathlib import Path
from datetime import datetime
from django.core.management.base import BaseCommand
from apps.analysis.models import MarginAnalysis
from decimal import Decimal, InvalidOperation

class Command(BaseCommand):
    help = '從 margin_analysis_final.csv 載入融資分析資料到資料庫'

    def handle(self, *args, **options):
        # 使用 BASE_DIR 找到 CSV 檔案
        base_dir = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
        csv_path = base_dir / 'margin_analysis_final.csv'

        if not csv_path.exists():
            self.stdout.write(self.style.ERROR(f'找不到檔案: {csv_path}'))
            return

        self.stdout.write(f'讀取檔案: {csv_path}')

        count = 0
        skipped = 0

        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                date_str = row.get('日期', '').strip()
                if not date_str:
                    skipped += 1
                    continue

                try:
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                except ValueError:
                    self.stdout.write(self.style.WARNING(f'日期格式錯誤: {date_str}'))
                    skipped += 1
                    continue

                def parse_decimal(val, default=None):
                    if val is None or str(val).strip() == '' or str(val).strip().lower() == 'nan':
                        return default
                    try:
                        return Decimal(str(val).strip())
                    except (InvalidOperation, ValueError):
                        return default

                defaults = {
                    'index_close': parse_decimal(row.get('TWA00加_收盤')),
                    'margin_balance': parse_decimal(row.get('融資金額_資餘_仟元')),
                    'margin_score': parse_decimal(row.get('融資分數')),
                    'change_1d': parse_decimal(row.get('融資1日變化')),
                    'change_5d': parse_decimal(row.get('融資5日變化')),
                    'change_10d': parse_decimal(row.get('融資10日變化')),
                    'change_20d': parse_decimal(row.get('融資20日變化')),
                    'change_40d': parse_decimal(row.get('融資40日變化')),
                    'score_change_21d': parse_decimal(row.get('融資分數變動率')),
                }

                obj, created = MarginAnalysis.objects.update_or_create(
                    date=date_obj,
                    defaults=defaults
                )
                count += 1
                if count % 100 == 0:
                    self.stdout.write(f'已處理 {count} 筆...')

        self.stdout.write(self.style.SUCCESS(f'完成！處理 {count} 筆，跳過 {skipped} 筆。'))
