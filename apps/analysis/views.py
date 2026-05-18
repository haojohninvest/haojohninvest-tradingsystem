from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.core.management import call_command
from io import StringIO
import sys
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from .models import Indicator, SectorDivergence
from apps.market_data.models import DailyPrice, Stock, StockSharesHistory
from apps.sectors.models import StockSector, Sector
from .signals import detect_all_signals, get_signal_details

def get_color(val):
    if val >= 80: return 'mediumseagreen'
    elif val >= 50: return 'lightgreen'
    elif val > 20: return 'lightcoral'
    else: return 'red'

def sector_divergence_view(request):
    """極速版族群背離多面板圖表 (讀取預先算好的 SectorDivergence)"""
    # 1. 先只撈出所有不重複的日期 (只取最近 **30 天**，加快載入速度)
    all_dates = list(SectorDivergence.objects.order_by('-date').values_list('date', flat=True).distinct()[:30])
    if not all_dates:
        return render(request, 'analysis/divergence.html', {'error': '尚未計算族群背離，請先在終端機執行 python manage.py calc_divergence'})
    
    # 不反轉，保持最新日期在最前面 (配合 yaxis autorange="reversed" 會讓最新在最上面)
    latest_date = all_dates[0]
    
    # 2. 撈出最新一天有資料的族群 (取前 **15 名**，減少 panel 數量加快顯示)
    latest_div = SectorDivergence.objects.filter(date=latest_date).exclude(sector_name='__MARKET_BREADTH__').order_by('-divergence').values('sector_name')[:15]
    sorted_sectors = [d['sector_name'] for d in latest_div]
    
    # 3. 把需要的資料一次撈出來 (只撈這 15 個族群的最近 150 天)
    all_sectors = sorted_sectors + ['__MARKET_BREADTH__']
    div_qs = SectorDivergence.objects.filter(
        date__in=all_dates,
        sector_name__in=all_sectors
    ).order_by('date', 'sector_name').values('date', 'sector_name', 'divergence', 'is_orange', 'is_pink')
    
    df_div = pd.DataFrame(list(div_qs))
    
    if df_div.empty:
        return render(request, 'analysis/divergence.html', {'error': '沒有足夠的資料顯示圖表'})
    
    # 建立 Pivot Table (這次資料量少很多，速度會快)
    div_pivot = df_div.pivot(index='date', columns='sector_name', values='divergence')
    orange_pivot = df_div.pivot(index='date', columns='sector_name', values='is_orange')
    pink_pivot = df_div.pivot(index='date', columns='sector_name', values='is_pink')
    
    # 依照日期排序，最新日期在最上面 (比照 Market Breadth)
    div_pivot = div_pivot.sort_index(ascending=False)
    orange_pivot = orange_pivot.sort_index(ascending=False)
    pink_pivot = pink_pivot.sort_index(ascending=False)
    
    # 轉成字串列表
    dates_str = [d.strftime('%Y-%m-%d') for d in div_pivot.index]
    
    # 4. 準備 Market Breadth 第一格資料
    if '__MARKET_BREADTH__' in div_pivot.columns:
        b_vals = div_pivot['__MARKET_BREADTH__'].fillna(0).tolist()
    else:
        b_vals = [0] * len(dates_str)
            
    # 5. 畫圖 (減少族群數量，寬度固定)
    num_cols = len(sorted_sectors) + 1
    total_width = max(1200, num_cols * 200)
    chart_height = max(800, len(dates_str) * 15)

    titles = ['大盤 Market Breadth'] + sorted_sectors
    fig = make_subplots(rows=1, cols=num_cols, shared_yaxes=False, 
                        horizontal_spacing=0.008, subplot_titles=titles)

    # Market Breadth 柱狀圖
    b_colors = [get_color(v) for v in b_vals]
    fig.add_trace(go.Bar(
        x=b_vals, y=dates_str, orientation='h',
        marker=dict(color=b_colors, line=dict(color='black', width=0.5)),
        name='Market Breadth',
        hovertemplate='大盤<br>%{y}<br>寬度：%{x:.2f}%<extra></extra>',
    ), row=1, col=1)

    fig.add_vline(x=80, line_width=2, line_color="gray", opacity=0.5, row=1, col=1)
    fig.add_vline(x=20, line_width=2, line_color="gray", opacity=0.5, row=1, col=1)

    # 其他族群柱狀圖
    for i, sector in enumerate(sorted_sectors):
        col_idx = i + 2
        
        # 直接从 pivot table 取数据并转为 list
        vals = div_pivot[sector].fillna(0).tolist()
        oranges = orange_pivot[sector].fillna(False).tolist()
        pinks = pink_pivot[sector].fillna(False).tolist()
        
        bar_colors = ['orange' if o else 'lightgrey' for o in oranges]
        
        fig.add_trace(go.Bar(
            x=vals, y=dates_str, orientation='h',
            marker=dict(color=bar_colors, line=dict(color='black', width=0.5)),
            name=sector,
            hovertemplate=sector + '<br>%{y}<br>乖離率：%{x:.2f}%<extra></extra>',
        ), row=1, col=col_idx)
        
        fig.add_vline(x=0, line_width=1, line_color="black", opacity=0.3, row=1, col=col_idx)
        
        # 優化紫色背景的繪製 (一次性畫完所有 rect)
        pink_indices = [idx for idx, is_p in enumerate(pinks) if is_p]
        for row_idx in pink_indices:
            fig.add_hrect(
                y0=row_idx - 0.5, y1=row_idx + 0.5, 
                fillcolor="#241ADB", opacity=0.18, layer="below", line_width=0,
                row=1, col=col_idx
            )

    fig.update_layout(
        width=total_width, height=chart_height,
        plot_bgcolor='white', paper_bgcolor='white',
        margin=dict(l=80, r=10, t=50, b=10),  # 左邊留多一點空間給日期
        showlegend=False,
        xaxis=dict(fixedrange=True),  # x 軸固定
    )
    
    # 設定所有 y 軸：最新日期在最上面 (比照 Market Breadth)
    fig.update_yaxes(
        autorange="reversed",  # ★ 關鍵：讓 y 軸顛倒，最新日期在最上面
        showgrid=True,
        gridcolor='#e5e7eb',
        type='category',
        row=1,
        col=1
    )
    # 其他 y 軸隱藏標籤，但保持格線
    for i in range(2, num_cols + 1):
        fig.update_yaxes(
            autorange="reversed",
            showgrid=True,
            gridcolor='#e5e7eb',
            type='category',
            showticklabels=False,
            row=1,
            col=i
        )
    
    fig.update_xaxes(showticklabels=False, showgrid=False)
    fig.update_xaxes(showticklabels=True, showgrid=True, gridcolor='#e5e7eb', dtick=20, row=1, col=1)

    # 加入 config 設定：禁用 scrollZoom 避免誤觸，固定 y 軸
    chart_html = fig.to_html(
        full_html=False,
        include_plotlyjs=False,
        config={'scrollZoom': False, 'displayModeBar': True}
    )
    return render(request, 'analysis/divergence.html', {'chart_html': chart_html})

def market_breadth_view(request):
    """讀取預先計算好的 Market Breadth（從 SectorDivergence.__MARKET_BREADTH__），速度從 3 秒降到 0.1 秒"""
    from datetime import date, timedelta
    cutoff = date.today() - timedelta(days=150)
    
    # ★ 直接從 SectorDivergence 快取表讀取預計算好的 Market Breadth（calc_divergence 已算好）
    breadth_qs = SectorDivergence.objects.filter(
        date__gte=cutoff,
        sector_name='__MARKET_BREADTH__'
    ).order_by('-date').values('date', 'divergence')
    
    if not breadth_qs.exists():
        return render(request, 'analysis/market_breadth.html', {'chart_html': '<p class="text-center text-gray-500 mt-20">目前資料庫沒有 Market Breadth 資料，請先執行 python manage.py calc_divergence</p>'})
    
    df = pd.DataFrame(list(breadth_qs))
    df['divergence'] = pd.to_numeric(df['divergence'], errors='coerce').fillna(0)
    
    # Y 軸字串與顏色
    df['date_str'] = df['date'].astype(str)
    def get_color(val):
        if val >= 80: return 'mediumseagreen'
        elif val >= 50: return 'lightgreen'
        elif val > 20: return 'lightcoral'
        else: return 'red'
    df['color'] = df['divergence'].apply(get_color)
    
    # 畫圖
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df['divergence'].tolist(), y=df['date_str'].tolist(), orientation='h',
        marker=dict(color=df['color'].tolist(), line=dict(color='black', width=0.5)),
        name='Market Breadth (%)',
        hovertemplate='日期: %{y}<br>寬度: %{x:.2f}%<extra></extra>',
    ))
    fig.add_vline(x=80, line_width=4, line_color="gray", opacity=0.8)
    fig.add_vline(x=20, line_width=4, line_color="gray", opacity=0.8)
    
    chart_height = max(600, len(df) * 20)
    fig.update_layout(
        height=chart_height, plot_bgcolor='white', paper_bgcolor='white',
        margin=dict(l=40, r=40, t=40, b=40),
        xaxis=dict(title='', range=[0, 100], showgrid=True, gridcolor='#d3d3d3', dtick=5, tickfont=dict(size=12)),
        yaxis=dict(title='', autorange="reversed", showgrid=True, gridcolor='#e5e7eb', type='category'),
        showlegend=False, hovermode='y unified'
    )
    
    chart_html = fig.to_html(full_html=False, include_plotlyjs=False)
    return render(request, 'analysis/market_breadth.html', {'chart_html': chart_html})


def market_cap_ranking_view(request):
    """最新市值排行榜 (前 200 大)"""
    # 找出資料庫裡有股價的「最新日期」
    latest_price = DailyPrice.objects.order_by('-date').first()
    
    if not latest_price:
        return render(request, 'analysis/market_cap_ranking.html', {'error': '目前資料庫沒有股價資料'})
        
    latest_date = latest_price.date
    
    # 撈出該日期的所有股價與股票資料
    prices = DailyPrice.objects.filter(date=latest_date).select_related('stock')
    
    ranking_data = []
    # ★ 一次性查出所有需要的最新股數
    all_latest_shares = StockSharesHistory.objects.filter(
        date__lte=latest_date
    ).values('stock_id', 'outstanding_shares').order_by('stock_id', '-date')
    
    shares_map = {}
    for record in all_latest_shares:
        sid = record['stock_id']
        if sid not in shares_map:
            shares_map[sid] = record['outstanding_shares'] or 0
    
    for p in prices:
        shares = shares_map.get(p.stock.id, 0)
        
        # 計算市值 (收盤價 * 股數)
        if p.close and shares > 0:
            market_cap = float(p.close) * shares
            ranking_data.append({
                'code': p.stock.code,
                'name': p.stock.name,
                'market': '上市' if p.stock.market == 'twse' else '上櫃',
                'close': float(p.close),
                'shares': shares,
                'market_cap': market_cap,
                # 把市值換算成「億」為單位，方便閱讀
                'market_cap_e': market_cap / 100000000 
            })
            
    # 依照市值由大到小排序
    ranking_data.sort(key=lambda x: x['market_cap'], reverse=True)
    
    # 只取前 300 名
    top_300 = ranking_data[:300]
    
    context = {
        'target_date': latest_date,
        'top_300': top_300
    }
    
    return render(request, 'analysis/market_cap_ranking.html', context)

@staff_member_required
def calc_divergence_view(request):
    """管理用：手動重新計算族群背離"""
    output = StringIO()
    old_stdout = sys.stdout
    sys.stdout = output
    
    try:
        # 執行 calc_divergence 命令
        call_command('calc_divergence')
        success = True
        message = '計算成功！'
    except Exception as e:
        success = False
        message = f'計算失敗：{str(e)}'
    finally:
        sys.stdout = old_stdout
    
    # 獲取命令輸出
    command_output = output.getvalue()
    
    # 獲取最新計算時間
    latest_calc = SectorDivergence.objects.order_by('-date').first()
    latest_date = latest_calc.date if latest_calc else None
    
    context = {
        'success': success,
        'message': message,
        'command_output': command_output,
        'latest_date': latest_date,
    }
    
    return render(request, 'admin/calc_divergence_result.html', context)


def sector_detail_view(request, sector_name):
    """
    族群詳情頁：顯示該族群所有股票及標誌性動作
    """
    # 取得族群
    sector = get_object_or_404(Sector, name=sector_name)
    
    # 取得該族群所有股票
    stock_sectors = StockSector.objects.filter(sector=sector).select_related('stock')
    stocks = [ss.stock for ss in stock_sectors if ss.stock]
    
    if not stocks:
        return render(request, 'analysis/sector_detail.html', {
            'error': f'族群 "{sector_name}" 目前沒有股票',
            'sector_name': sector_name,
        })
    
    # 取得最新交易日
    latest_price = DailyPrice.objects.order_by('-date').first()
    latest_date = latest_price.date if latest_price else None
    
    # 計算每支股票的訊號和市值
    stock_data = []
    for stock in stocks:
        # 偵測訊號
        signals = detect_all_signals(stock.id, days=20, end_date=latest_date)
        
        # 取得最新股價和市值
        latest_daily = DailyPrice.objects.filter(stock=stock, date=latest_date).first()
        
        # 計算市值
        shares_record = StockSharesHistory.objects.filter(
            stock=stock, date__lte=latest_date
        ).order_by('-date').first()
        if latest_daily and shares_record and shares_record.outstanding_shares:
            market_cap = float(latest_daily.close) * float(shares_record.outstanding_shares)
        else:
            market_cap = 0
        
        # 計算當日漲跌幅
        if latest_daily:
            prev_daily = DailyPrice.objects.filter(
                stock=stock,
                date__lt=latest_date
            ).order_by('-date').first()
            
            if prev_daily and prev_daily.close:
                daily_return = ((float(latest_daily.close) - float(prev_daily.close)) / float(prev_daily.close)) * 100
            else:
                daily_return = 0
            close_price = float(latest_daily.close)
        else:
            daily_return = 0
            close_price = 0
        
        stock_data.append({
            'stock': stock,
            'market_cap': market_cap,
            'close_price': close_price,
            'daily_return': daily_return,
            'surge_count': signals['surge_count'],
            'gap_count': signals['gap_count'],
            'volume_count': signals['volume_count'],
        })
    
    # 依市值排序
    stock_data.sort(key=lambda x: x['market_cap'], reverse=True)
    
    context = {
        'sector': sector,
        'stock_data': stock_data,
        'latest_date': latest_date,
        'total_stocks': len(stock_data),
    }
    
    return render(request, 'analysis/sector_detail.html', context)


def sector_detail_ajax(request, stock_id):
    """
    AJAX 端點：取得單一股票的訊號詳細資訊（用於展開詳情）
    """
    from django.http import JsonResponse
    
    latest_price = DailyPrice.objects.order_by('-date').first()
    latest_date = latest_price.date if latest_price else None
    
    details = get_signal_details(stock_id, days=20, end_date=latest_date)
    
    return JsonResponse(details)
