from django.db import models


class Stock(models.Model):
    code = models.CharField('股票代號', max_length=10, unique=True)
    name = models.CharField('股票名稱', max_length=50)
    market = models.CharField('市場別', max_length=10, choices=[('twse', '上市'), ('otc', '上櫃')])
    market_cap = models.BigIntegerField('市值(元)', null=True, blank=True)

    class Meta:
        verbose_name = '股票'
        verbose_name_plural = '股票'
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['market']),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"


class DailyPrice(models.Model):
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='daily_prices', verbose_name='股票')
    date = models.DateField('日期')
    open = models.DecimalField('開盤價', max_digits=10, decimal_places=2, null=True, blank=True)
    high = models.DecimalField('最高價', max_digits=10, decimal_places=2, null=True, blank=True)
    low = models.DecimalField('最低價', max_digits=10, decimal_places=2, null=True, blank=True)
    close = models.DecimalField('收盤價', max_digits=10, decimal_places=2, null=True, blank=True)
    volume = models.BigIntegerField('成交股數', null=True, blank=True)
    trade_value = models.BigIntegerField('成交金額(元)', null=True, blank=True)

    class Meta:
        verbose_name = '每日股價'
        verbose_name_plural = '每日股價'
        unique_together = ('stock', 'date')
        ordering = ['-date']

    def __str__(self):
        return f"{self.stock.code} - {self.date}"


class StockSharesHistory(models.Model):
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='shares_history', verbose_name='股票')
    date = models.DateField('適用日期')
    outstanding_shares = models.BigIntegerField('發行股數', null=True, blank=True)
    source = models.CharField('資料來源', max_length=50, default='finmind')

    class Meta:
        verbose_name = '歷史股數'
        verbose_name_plural = '歷史股數'
        unique_together = ('stock', 'date')
        ordering = ['-date']

    def __str__(self):
        return f"{self.stock.code} - {self.date}: {self.outstanding_shares}"
