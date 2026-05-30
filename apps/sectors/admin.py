from django.contrib import admin
from django.utils.html import format_html
from .models import Sector, StockSector

@admin.register(StockSector)
class StockSectorAdmin(admin.ModelAdmin):
    """股票分類對應管理後台"""
    list_display = ['stock_code', 'stock_name', 'sector_name', 'modified_by', 'modified_at']
    list_filter = ['sector']
    search_fields = ['stock__code', 'stock__name']
    list_per_page = 100
    ordering = ['stock__code']
    change_list_template = 'admin/sectors/stocksector_changelist.html'
    
    def stock_code(self, obj):
        return obj.stock.code
    stock_code.short_description = '股票代號'
    
    def stock_name(self, obj):
        return obj.stock.name
    stock_name.short_description = '股票名稱'
    
    def sector_name(self, obj):
        return obj.sector.name if obj.sector else '未分類'
    sector_name.short_description = '所屬分類'

@admin.register(Sector)
class SectorAdmin(admin.ModelAdmin):
    """產業分類管理後台"""
    list_display = ['name', 'category_type']
    list_filter = ['category_type']
    search_fields = ['name']
    list_per_page = 50
    change_list_template = 'admin/sectors/sector_changelist.html'
