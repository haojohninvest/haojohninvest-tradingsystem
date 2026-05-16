from django.urls import path
from . import views

app_name = 'analysis'

urlpatterns = [
    path('breadth/', views.market_breadth_view, name='market_breadth'),
    path('market-cap-ranking/', views.market_cap_ranking_view, name='market_cap_ranking'),
    path('divergence/', views.sector_divergence_view, name='divergence'),
    path('margin-analysis/', views.margin_analysis_view, name='margin_analysis'),
    path('calc-divergence/', views.calc_divergence_view, name='calc_divergence'),
    path('sector/<str:sector_name>/', views.sector_detail_view, name='sector_detail'),
    path('api/stock/<int:stock_id>/signals/', views.sector_detail_ajax, name='sector_detail_ajax'),
]
