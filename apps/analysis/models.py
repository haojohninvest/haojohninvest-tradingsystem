from django.db import models
from apps.market_data.models import Stock

class Indicator(models.Model):
    """技術指標 (每日每股一筆)"""
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='indicators', verbose_name='股票')
    date = models.DateField('日期')
    
    # 均線
    ema20 = models.DecimalField('EMA20', max_digits=10, decimal_places=2, null=True, blank=True)
    ema60 = models.DecimalField('EMA60', max_digits=10, decimal_places=2, null=True, blank=True)
    ema120 = models.DecimalField('EMA120', max_digits=10, decimal_places=2, null=True, blank=True)
    sma20 = models.DecimalField('SMA20', max_digits=10, decimal_places=2, null=True, blank=True)
    sma60 = models.DecimalField('SMA60', max_digits=10, decimal_places=2, null=True, blank=True)
    sma120 = models.DecimalField('SMA120', max_digits=10, decimal_places=2, null=True, blank=True)
    
    # 漲跌率
    daily_return = models.DecimalField('當日漲跌(%)', max_digits=8, decimal_places=2, null=True, blank=True)
    five_day_return = models.DecimalField('五日漲跌(%)', max_digits=8, decimal_places=2, null=True, blank=True)
    
    # 偏離率
    ema20_dev = models.DecimalField('EMA20偏離率(%)', max_digits=8, decimal_places=2, null=True, blank=True)
    ema60_dev = models.DecimalField('EMA60偏離率(%)', max_digits=8, decimal_places=2, null=True, blank=True)
    ema120_dev = models.DecimalField('EMA120偏離率(%)', max_digits=8, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = '技術指標'
        verbose_name_plural = '技術指標'
        unique_together = ('stock', 'date')
        indexes = [
            models.Index(fields=['date']),
        ]

    def __str__(self):
        return f"{self.stock.code} 指標 - {self.date}"

class SectorDivergence(models.Model):
    """族群總市值 EMA20 乖離率 (預先計算快取表)"""
    date = models.DateField('日期')
    sector_name = models.CharField('族群名稱', max_length=50)
    divergence = models.DecimalField('乖離率(%)', max_digits=10, decimal_places=2, null=True, blank=True)
    is_orange = models.BooleanField('亮橘燈(連2天前五名)', default=False)
    is_pink = models.BooleanField('亮紫燈(由負轉正)', default=False)
    
    class Meta:
        verbose_name = '族群背離快取'
        verbose_name_plural = '族群背離快取'
        unique_together = ('date', 'sector_name')
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['sector_name']),
        ]

    def __str__(self):
        return f"{self.date} - {self.sector_name} ({self.divergence}%)"
