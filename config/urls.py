"""
URL configuration for config project.
"""
from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect

admin.site.site_header = '豪強資本交易系統管理後台'
admin.site.site_title = '豪強資本管理後台'
admin.site.index_title = '管理工具'

from django_apscheduler.models import DjangoJob, DjangoJobExecution
admin.site.unregister(DjangoJob)
admin.site.unregister(DjangoJobExecution)

from apps.analysis.views import calc_divergence_view

urlpatterns = [
    path('admin/calc-divergence/', calc_divergence_view, name='admin_calc_divergence'),
    path('admin/', admin.site.urls),
    path('analysis/', include('apps.analysis.urls')),
    path('', lambda req: redirect('/analysis/breadth/')),
]
