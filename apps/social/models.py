from django.db import models
from django.contrib.auth.models import User
from apps.market_data.models import Stock

class Message(models.Model):
    """留言板"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='messages', verbose_name='留言者')
    content = models.TextField('留言內容')
    created_at = models.DateTimeField('留言時間', auto_now_add=True)
    page = models.CharField('所在頁面', max_length=50, default='dashboard', help_text='辨識留言在哪個頁面產生')

    class Meta:
        verbose_name = '留言'
        verbose_name_plural = '留言'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} 於 {self.created_at.strftime('%Y-%m-%d %H:%M')} 留言"

class StockWatch(models.Model):
    """個股註記 / 追蹤"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='watchlist', verbose_name='用戶')
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='watched_by', verbose_name='追蹤股票')
    note = models.TextField('備註', blank=True, null=True)
    created_at = models.DateTimeField('加入時間', auto_now_add=True)

    class Meta:
        verbose_name = '個股追蹤'
        verbose_name_plural = '個股追蹤'
        unique_together = ('user', 'stock')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} 追蹤 {self.stock.name}"
