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


class MarketBreadth(models.Model):
    """大盤寬度快取 (前300大權值股站上EMA20的比例)"""
    date = models.DateField('日期', unique=True)
    breadth_percent = models.DecimalField('大盤寬度(%)', max_digits=6, decimal_places=2)

    class Meta:
        verbose_name = '大盤寬度'
        verbose_name_plural = '大盤寬度'
        ordering = ['-date']

    def __str__(self):
        return f"{self.date} - Breadth: {self.breadth_percent}%"


class BuyPool(models.Model):
    """選股掃描結果 (Stock Pick Strategy v0519)"""
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='buy_pool_entries', verbose_name='股票', null=True, blank=True)
    date = models.DateField('買入日期')
    stock_code = models.CharField('股票代號', max_length=10)
    stock_name = models.CharField('股票名稱', max_length=50, blank=True)
    close = models.DecimalField('收盤價', max_digits=10, decimal_places=2, null=True, blank=True)
    volume = models.BigIntegerField('成交量', null=True, blank=True)
    turnover = models.DecimalField('成交金額(億)', max_digits=12, decimal_places=2, null=True, blank=True)
    ema20 = models.DecimalField('EMA20', max_digits=10, decimal_places=2, null=True, blank=True)
    ema60 = models.DecimalField('EMA60', max_digits=10, decimal_places=2, null=True, blank=True)
    ema120 = models.DecimalField('EMA120', max_digits=10, decimal_places=2, null=True, blank=True)
    signal_type = models.CharField('訊號類型', max_length=10)
    entry_date = models.DateField('入池日期')
    d = models.IntegerField('D值(入池天數)')
    r20 = models.DecimalField('R20', max_digits=8, decimal_places=3, null=True, blank=True)
    r20_hole = models.DecimalField('R20_hole', max_digits=8, decimal_places=3, null=True, blank=True)
    scenario = models.CharField('情境', max_length=1)
    market_cap = models.BigIntegerField('市值(元)', null=True, blank=True)

    ema20_cross_date = models.DateField('EMA20穿越日(R欄)', null=True, blank=True)
    first_r_date = models.BooleanField('首次R日期(S欄)', default=False)

    sell_date = models.DateField('賣出日期', null=True, blank=True)
    return_rate = models.DecimalField('報酬率(%)', max_digits=8, decimal_places=2, null=True, blank=True)
    max_drawdown = models.DecimalField('最大回撤(%)', max_digits=8, decimal_places=2, null=True, blank=True)
    max_return_rate = models.DecimalField('最高報酬率(%)', max_digits=8, decimal_places=2, null=True, blank=True)

    scan_run_id = models.CharField('掃描批次ID', max_length=50, blank=True, help_text='用於辨識同一次掃描 run')

    class Meta:
        verbose_name = '選股掃描結果'
        verbose_name_plural = '選股掃描結果'
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['stock_code']),
            models.Index(fields=['scan_run_id']),
        ]
        unique_together = ('date', 'stock_code', 'scan_run_id')

    def __str__(self):
        return f"{self.stock_code} {self.stock_name} - {self.date} [{self.scenario}]"


class BuyPoolSimulation(models.Model):
    """模擬漲幅後的選股掃描結果 (Simulation of Stock Pick Strategy v0519)"""
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='buy_pool_sim_entries', verbose_name='股票', null=True, blank=True)
    date = models.DateField('買入日期')
    stock_code = models.CharField('股票代號', max_length=10)
    stock_name = models.CharField('股票名稱', max_length=50, blank=True)
    close = models.DecimalField('收盤價(模擬)', max_digits=10, decimal_places=2, null=True, blank=True)
    volume = models.BigIntegerField('成交量', null=True, blank=True)
    turnover = models.DecimalField('成交金額(億)', max_digits=12, decimal_places=2, null=True, blank=True)
    ema20 = models.DecimalField('EMA20(模擬)', max_digits=10, decimal_places=2, null=True, blank=True)
    ema60 = models.DecimalField('EMA60(模擬)', max_digits=10, decimal_places=2, null=True, blank=True)
    ema120 = models.DecimalField('EMA120(模擬)', max_digits=10, decimal_places=2, null=True, blank=True)
    signal_type = models.CharField('訊號類型', max_length=10)
    entry_date = models.DateField('入池日期')
    d = models.IntegerField('D值(入池天數)')
    r20 = models.DecimalField('R20', max_digits=8, decimal_places=3, null=True, blank=True)
    r20_hole = models.DecimalField('R20_hole', max_digits=8, decimal_places=3, null=True, blank=True)
    scenario = models.CharField('情境', max_length=1)
    market_cap = models.BigIntegerField('市值(元)', null=True, blank=True)

    simulation_pct = models.DecimalField('模擬漲幅(%)', max_digits=5, decimal_places=2)
    simulated_date = models.DateField('模擬日期')

    ema20_cross_date = models.DateField('EMA20穿越日(R欄)', null=True, blank=True)
    first_r_date = models.BooleanField('首次R日期(S欄)', default=False)

    sell_date = models.DateField('賣出日期', null=True, blank=True)
    return_rate = models.DecimalField('報酬率(%)', max_digits=8, decimal_places=2, null=True, blank=True)
    max_drawdown = models.DecimalField('最大回撤(%)', max_digits=8, decimal_places=2, null=True, blank=True)
    max_return_rate = models.DecimalField('最高報酬率(%)', max_digits=8, decimal_places=2, null=True, blank=True)

    scan_run_id = models.CharField('掃描批次ID', max_length=50, blank=True, help_text='用於辨識同一次模擬 run')

    class Meta:
        verbose_name = '模擬選股掃描結果'
        verbose_name_plural = '模擬選股掃描結果'
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['stock_code']),
            models.Index(fields=['simulated_date']),
        ]
        unique_together = ('date', 'stock_code', 'scan_run_id')

    def __str__(self):
        return f"[SIM] {self.stock_code} {self.stock_name} - {self.date} (+{self.simulation_pct}%)"
