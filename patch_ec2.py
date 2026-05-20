# Patch script for EC2
# This script writes the modified files directly on EC2

import os

BASE = "/home/ubuntu/haojohninvest-tradingsystem"

# 1. run_crawler.py patch
RUN_CRAWLER = os.path.join(BASE, "apps/market_data/management/commands/run_crawler.py")
with open(RUN_CRAWLER, "r", encoding="utf-8") as f:
    content = f.read()

# Add weekend check to --date branch
old_date_block = """        elif options.get('date'):
            target_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
            self.stdout.write(f"正在處理 {target_date}...")
            MarketCrawler.run_daily_crawl(target_date)"""

new_date_block = """        elif options.get('date'):
            target_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
            # PATCH: 增加週末檢查，避免在週末寫入髒資料
            if target_date.weekday() >= 5:
                self.stdout.write(
                    self.style.WARNING(
                        f"指定日期 {target_date} 為週六/日，台股休市，跳過爬取。"
                    )
                )
                return
            self.stdout.write(f"正在處理 {target_date}...")
            MarketCrawler.run_daily_crawl(target_date)"""

if old_date_block in content:
    content = content.replace(old_date_block, new_date_block)
    print("[OK] run_crawler.py patched")
else:
    print("[WARN] run_crawler.py date block not found as expected")

with open(RUN_CRAWLER, "w", encoding="utf-8") as f:
    f.write(content)

# 2. Create validators.py
VALIDATORS_PATH = os.path.join(BASE, "apps/market_data/validators.py")
if not os.path.exists(VALIDATORS_PATH):
    with open(VALIDATORS_PATH, "w", encoding="utf-8") as f:
        f.write('''import pandas as pd\nfrom datetime import date, timedelta\nimport logging\n\nlogger = logging.getLogger(__name__)\n\n\nclass PriceValidator:\n    """\n    三層檢驗機制中的 Layer 1: 即時檢驗\n    每筆價格寫入 DB 前執行\n    """\n    \n    @staticmethod\n    def validate_row(row, prev_close=None):\n        """\n        驗證單筆價格資料是否合理\n        \n        Args:\n            row: dict with keys \'open\', \'high\', \'low\', \'close\', \'volume\'\n            prev_close: 前一日收盤價（可選）\n        \n        Returns:\n            (is_valid: bool, reason: str)\n        """\n        # 1. 基本合理性\n        if pd.isna(row.get(\'close\')) or row[\'close\'] <= 0:\n            return False, f"close <= 0 or NaN: {row.get(\'close\')}"\n        \n        if pd.isna(row.get(\'volume\')) or row[\'volume\'] <= 0:\n            return False, f"volume <= 0 or NaN: {row.get(\'volume\')}"\n        \n        # 2. 價格邏輯關係\n        low = row.get(\'low\')\n        high = row.get(\'high\')\n        close = row.get(\'close\')\n        \n        if not pd.isna(low) and not pd.isna(high):\n            if low > high:\n                return False, f"low ({low}) > high ({high})"\n            \n            if not (low <= close <= high):\n                return False, f"close ({close}) not in [low ({low}), high ({high})]"\n        \n        # 3. 異常跳動檢查（與前日比較）\n        if prev_close and prev_close > 0:\n            change_pct = abs(close - prev_close) / prev_close\n            \n            # 一般股票 ±10%，創新板 ±15%（這裡用較寬鬆的 15%）\n            if change_pct > 0.15:\n                return False, f"jump > 15%: {prev_close} -> {close} ({change_pct:.1%})"\n        \n        return True, "OK"\n    \n    @staticmethod\n    def get_prev_close(stock_code, target_date):\n        """\n        從資料庫取得前一日收盤價（如果有）\n        """\n        from apps.market_data.models import DailyPrice, Stock\n        \n        try:\n            stock = Stock.objects.filter(code=stock_code).first()\n            if not stock:\n                return None\n            \n            prev = DailyPrice.objects.filter(\n                stock=stock,\n                date__lt=target_date\n            ).order_by(\'-date\').first()\n            \n            return prev.close if prev else None\n        except Exception:\n            return None\n''')
    print("[OK] validators.py created")
else:
    print("[INFO] validators.py already exists")

# 3. Quick test
print("\nAll patches applied on EC2!")
print("Files modified:")
print(f"  - {RUN_CRAWLER}")
print(f"  - {VALIDATORS_PATH}")
print("\n[TODO] crawler.py dynamic column mapping needs manual update on EC2")