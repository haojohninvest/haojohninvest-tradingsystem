import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from apps.market_data.models import DailyPrice, Stock

s = Stock.objects.filter(code="1519").first()
print("Stock:", s)
prices = DailyPrice.objects.filter(stock__code="1519").order_by("-date")[:10]
for p in prices:
    print(f"{p.date}: {p.close}")
