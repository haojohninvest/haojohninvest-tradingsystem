from django.contrib import admin
from .models import MarginAnalysis

@admin.register(MarginAnalysis)
class MarginAnalysisAdmin(admin.ModelAdmin):
    list_display = ('date', 'index_close', 'margin_balance', 'margin_score', 'change_1d', 'change_5d', 'change_10d', 'change_20d', 'change_40d', 'score_change_21d')
    list_filter = ('date',)
    ordering = ('-date',)
    date_hierarchy = 'date'
