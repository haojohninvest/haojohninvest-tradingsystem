"""
URL configuration for config project.
"""
from django.contrib import admin
from django.urls import path

admin.site.site_header = '豪強資本交易系統管理後台'
admin.site.site_title = '豪強資本管理後台'
admin.site.index_title = '管理工具'

urlpatterns = [
    path('admin/', admin.site.urls),
]
