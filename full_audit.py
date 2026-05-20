import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from apps.market_data.models import DailyPrice
from django.db.models import Count, Min, Max

print("=== 週末髒資料統計 ===")
weekend = DailyPrice.objects.filter(date__week_day__in=[1, 7])
stats = weekend.aggregate(
    total=Count('id'),
    earliest=Min('date'),
    latest=Max('date')
)
print(f"總筆數: {stats['total']}")
print(f"最早: {stats['earliest']}")
print(f"最晚: {stats['latest']}")

# 按年份統計
from django.db.models.functions import ExtractYear
year_stats = weekend.annotate(year=ExtractYear('date')).values('year').annotate(cnt=Count('id')).order_by('year')
print("\n按年份:")
for s in year_stats:
    print(f"  {s['year']}: {s['cnt']} 筆")

# 抽查 2024/5/20 星期一 的資料（user 說多家公司錯）
print("\n=== 2024/5/20 (週一) 抽查 ===")
may20 = DailyPrice.objects.filter(date="2024-05-20").select_related('stock').order_by('stock__code')[:10]
for p in may20:
    print(f"{p.stock.code} {p.stock.name}: close={p.close}")

print("\n=== 2025/5/11 (週日) 抽查 ===")
may11 = DailyPrice.objects.filter(date="2025-05-11").select_related('stock').order_by('stock__code')[:10]
for p in may11:
    print(f"{p.stock.code} {p.stock.name}: close={p.close}")

# 檢查 2025/7/20 (週日) 多家公司同時出現 757 的異常
print("\n=== 2025/7/20 (週日) 異常值分析 ===")
jul20 = DailyPrice.objects.filter(date="2025-07-20").select_related('stock').order_by('stock__code')
print(f"總共 {jul20.count()} 筆週日資料")
for p in jul20[:20]:
    print(f"{p.stock.code} {p.stock.name}: close={p.close}")

# 檢查是否有連續多個週末都有資料的情況（這很異常）
print("\n=== 每個週末有資料的天數統計 ===")
from django.db.models import Count
weekend_dates = weekend.values('date').annotate(cnt=Count('id')).order_by('-date')
print(f"總共有資料的週末日數: {weekend_dates.count()}")
for d in weekend_dates[:20]:
    wd = d['date'].weekday()
    name = "週六" if wd == 5 else "週日"
    print(f"  {d['date']} ({name}): {d['cnt']} 筆股票")
