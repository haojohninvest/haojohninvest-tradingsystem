from django.db import models
from django.contrib.auth.models import User
from apps.market_data.models import Stock

class Sector(models.Model):
    """產業分類"""
    name = models.CharField('分類名稱', max_length=50, unique=True)
    category_type = models.CharField('分類層級', max_length=20, choices=[('主分類', '主分類'), ('子分類', '子分類')], default='主分類')
    
    class Meta:
        verbose_name = '產業分類'
        verbose_name_plural = '產業分類'

    def __str__(self):
        return self.name

class StockSector(models.Model):
    """股票-分類對應 (可在網頁上編輯)"""
    stock = models.OneToOneField(Stock, on_delete=models.CASCADE, related_name='sector_mapping', verbose_name='股票')
    sector = models.ForeignKey(Sector, on_delete=models.SET_NULL, null=True, blank=True, related_name='stocks', verbose_name='所屬分類')
    modified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='最後修改者')
    modified_at = models.DateTimeField('最後修改時間', auto_now=True)
    
    class Meta:
        verbose_name = '股票分類對應'
        verbose_name_plural = '股票分類對應'

    def __str__(self):
        sector_name = self.sector.name if self.sector else '未分類'
        return f"{self.stock.name} -> {sector_name}"
