from django.db import models
from apps.market_data.models import Stock


class Indicator(models.Model):
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='indicators', verbose_name='股票')
    date = models.DateField('日期')

    ema20 = models.DecimalField('EMA20', max_digits=10, decimal_places=2, null=True, blank=True)
    ema60 = models.DecimalField('EMA60', max_digits=10, decimal_places=2, null=True, blank=True)
    ema120 = models.DecimalField('EMA120', max_digits=10, decimal_places=2, null=True, blank=True)
    sma20 = models.DecimalField('SMA20', max_digits=10, decimal_places=2, null=True, blank=True)
    sma60 = models.DecimalField('SMA60', max_digits=10, decimal_places=2, null=True, blank=True)
    sma120 = models.DecimalField('SMA120', max_digits=10, decimal_places=2, null=True, blank=True)

    daily_return = models.DecimalField('當日漲跌(%)', max_digits=8, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = '技術指標'
        verbose_name_plural = '技術指標'
        unique_together = ('stock', 'date')
        indexes = [
            models.Index(fields=['date']),
        ]

    def __str__(self):
        return f"{self.stock.code} 指標 - {self.date}"
