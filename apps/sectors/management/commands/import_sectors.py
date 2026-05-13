from django.core.management.base import BaseCommand
import pandas as pd
from apps.market_data.models import Stock
from apps.sectors.models import Sector, StockSector

class Command(BaseCommand):
    help = '從 Excel 檔案匯入股票分類'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default='產業分類_原始檔.xlsx',
            help='Excel 檔案路徑 (預設: 專案根目錄下的 產業分類_原始檔.xlsx)'
        )

    def handle(self, *args, **options):
        file_path = options['file']
        self.stdout.write(f"正在讀取分類檔案: {file_path} ...")
        
        try:
            df = pd.read_excel(file_path)
            # 取得第一和第二欄的名字，不管名字有無亂碼直接用位置抓
            col_stock = df.columns[0]
            col_sector = df.columns[1]
            
            # 清理資料：去掉空行
            df = df.dropna(subset=[col_stock, col_sector])
            
            success_count = 0
            
            # 建立一個預設的「未分類」分類
            unclassified_sector, _ = Sector.objects.get_or_create(
                name='未分類',
                defaults={'category_type': '主分類'}
            )

            # 1. 匯入有分類的股票
            for idx, row in df.iterrows():
                # 抓取前 4 個字元作為股票代號
                stock_str = str(row[col_stock]).strip()
                code = stock_str[:4]
                sector_name = str(row[col_sector]).strip()
                
                if not code.isdigit():
                    continue

                # 找尋對應的股票
                stock = Stock.objects.filter(code=code).first()
                if stock:
                    # 尋找或建立該產業分類
                    sector, _ = Sector.objects.get_or_create(
                        name=sector_name,
                        defaults={'category_type': '主分類'}
                    )
                    
                    # 建立或更新對應關係
                    StockSector.objects.update_or_create(
                        stock=stock,
                        defaults={'sector': sector}
                    )
                    success_count += 1

            self.stdout.write(self.style.SUCCESS(f"成功匯入 {success_count} 筆自訂分類！"))

            # 2. 處理剩餘「未分類」的股票
            # 找出還沒有對應關係的股票
            unmapped_stocks = Stock.objects.filter(sector_mapping__isnull=True)
            unmapped_count = unmapped_stocks.count()
            
            if unmapped_count > 0:
                self.stdout.write(f"發現 {unmapped_count} 檔股票沒有分類，正在統一貼上「未分類」標籤...")
                unmapped_mappings = [
                    StockSector(stock=stock, sector=unclassified_sector)
                    for stock in unmapped_stocks
                ]
                StockSector.objects.bulk_create(unmapped_mappings, ignore_conflicts=True)
            
            self.stdout.write(self.style.SUCCESS(f"所有分類處理完畢！(包含 {unmapped_count} 筆未分類)"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"匯入失敗: {e}"))