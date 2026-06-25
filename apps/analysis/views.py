from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.core.management import call_command
from django.db import models
from io import StringIO
import sys
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from .models import Indicator, SectorDivergence, MarketBreadth, BuyPool
from apps.market_data.models import DailyPrice, Stock, StockSharesHistory
from apps.sectors.models import StockSector, Sector
from .signals import detect_all_signals, get_signal_details


def sector_divergence_view(request):
    """極速版族群背離多面板圖表 (讀取預先算好的 SectorDivergence)"""
    # 1. 先只撈出所有不重複的日期 (只取最近 **30 天**，加快載入速度)
    all_dates = list(SectorDivergence.objects.order_by('-date').values_list('date', flat=True).distinct()[:30])
    if not all_dates:
        return render(request, 'analysis/divergence.html', {'error': '尚未計算族群背離，請先在終端機執行 python manage.py calc_divergence'})
    
    # 不反轉，保持最新日期在最前面 (配合 yaxis autorange="reversed" 會讓最新在最上面)
    latest_date = all_dates[0]
    
    # 2. 撈出最新一天有資料的族群 (取前 **15 名**，減少 panel 數量加快顯示)
    latest_div = SectorDivergence.objects.filter(date=latest_date).order_by('-divergence').values('sector_name')[:15]
    sorted_sectors = [d['sector_name'] for d in latest_div]
    
    # 3. 把需要的資料一次撈出來 (只撈這 15 個族群的最近 150 天)
    div_qs = SectorDivergence.objects.filter(
        date__in=all_dates,
        sector_name__in=sorted_sectors
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
    
    # 4. 畫圖 (減少族群數量，寬度固定)
    num_cols = len(sorted_sectors)
    total_width = max(1200, num_cols * 200)
    chart_height = max(800, len(dates_str) * 15)

    titles = sorted_sectors
    fig = make_subplots(rows=1, cols=num_cols, shared_yaxes=False, 
                        horizontal_spacing=0.008, subplot_titles=titles)

    # 族群柱狀圖
    for i, sector in enumerate(sorted_sectors):
        col_idx = i + 1
        
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
    
    # 設定所有 y 軸：最新日期在最上面
    for i in range(1, num_cols + 1):
        fig.update_yaxes(
            autorange="reversed",
            showgrid=True,
            gridcolor='#e5e7eb',
            type='category',
            showticklabels=(i == 1),
            row=1,
            col=i
        )
    
    fig.update_xaxes(showticklabels=False, showgrid=False)

    # 加入 config 設定：禁用 scrollZoom 避免誤觸，固定 y 軸
    chart_html = fig.to_html(
        full_html=False,
        include_plotlyjs=False,
        config={'scrollZoom': False, 'displayModeBar': True}
    )
    return render(request, 'analysis/divergence.html', {'chart_html': chart_html})

def market_breadth_view(request):
    """讀取預先計算好的 Market Breadth（從獨立 MarketBreadth 快取表），速度從 3 秒降到 0.1 秒"""
    from datetime import date, timedelta
    cutoff = date.today() - timedelta(days=150)
    
    # 直接從 MarketBreadth 快取表讀取預計算好的 Market Breadth
    breadth_qs = MarketBreadth.objects.filter(
        date__gte=cutoff
    ).order_by('-date').values('date', 'breadth_percent')
    
    if not breadth_qs.exists():
        return render(request, 'analysis/market_breadth.html', {'chart_html': '<p class="text-center text-gray-500 mt-20">目前資料庫沒有 Market Breadth 資料，請先執行 python manage.py calc_market_breadth --full</p>'})
    
    df = pd.DataFrame(list(breadth_qs))
    df['breadth_percent'] = pd.to_numeric(df['breadth_percent'], errors='coerce').fillna(0)
    
    # Y 軸字串與顏色
    df['date_str'] = df['date'].astype(str)
    def get_color(val):
        if val >= 80: return 'mediumseagreen'
        elif val >= 50: return 'lightgreen'
        elif val > 20: return 'lightcoral'
        else: return 'red'
    df['color'] = df['breadth_percent'].apply(get_color)
    
    # 畫圖
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df['breadth_percent'].tolist(), y=df['date_str'].tolist(), orientation='h',
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
    """最新市值排行榜 (前 300 大)"""
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


def trade_value_ranking_view(request):
    """成交金額增減排行榜：氣泡圖 + 族群每日明細"""
    from datetime import date, timedelta
    import plotly.graph_objects as go
    import pandas as pd
    import numpy as np

    # ── 1. 取得所有交易日 ──
    all_dates = list(DailyPrice.objects.order_by('-date').values_list('date', flat=True).distinct())
    if not all_dates:
        return render(request, 'analysis/trade_value_ranking.html', {'error': '無股價資料'})

    latest_date = all_dates[0]
    all_asc = sorted(all_dates)
    all_set = set(all_dates)

    # ── 2. 解析參數 ──
    mode = request.GET.get('mode', 'single')
    selected_sector = request.GET.get('sector', '').strip()

    curr_dates = []
    prev_dates = []
    curr_label = ''

    if mode == 'single':
        raw = request.GET.get('date', str(latest_date))
        try:
            td = date.fromisoformat(raw)
        except ValueError:
            td = latest_date
        if td not in all_set:
            td = latest_date
        curr_dates = [td]
        prev_candidates = [d for d in all_dates if d < td]
        prev_dates = [prev_candidates[0]] if prev_candidates else []
        curr_label = str(td)

    elif mode == 'range':
        df_str = request.GET.get('date_from', '')
        dt_str = request.GET.get('date_to', '')
        try:
            df = date.fromisoformat(df_str) if df_str else all_asc[0]
        except ValueError:
            df = all_asc[0]
        try:
            dt = date.fromisoformat(dt_str) if dt_str else latest_date
        except ValueError:
            dt = latest_date
        if dt > latest_date:
            dt = latest_date
        if df < all_asc[0]:
            df = all_asc[0]
        if df > dt:
            df, dt = dt, df
        curr_dates = sorted([d for d in all_asc if df <= d <= dt])
        trading_before = sorted([d for d in all_asc if d < df], reverse=True)
        prev_dates = trading_before[:len(curr_dates)]
        curr_label = f'{df} ~ {dt}'

    else:  # nday
        n_str = request.GET.get('n', '20')
        try:
            n = max(1, int(n_str))
        except ValueError:
            n = 20
        latest_idx = all_asc.index(latest_date)
        curr_start = max(0, latest_idx - n + 1)
        curr_dates = all_asc[curr_start:latest_idx + 1]
        prev_end = curr_start - 1
        prev_start = max(0, prev_end - n + 1)
        prev_dates = all_asc[prev_start:prev_end + 1] if prev_end >= 0 else []
        curr_label = f'近 {n} 日'

    if not curr_dates:
        return render(request, 'analysis/trade_value_ranking.html', {'error': '無有效的日期區間'})

    # ── 3. 建立 stock → sector 對照 ──
    sq = StockSector.objects.filter(
        sector__isnull=False
    ).select_related('sector').values('stock_id', 'sector__name')
    stock_to_sector = {}
    bad_names = {'#REF!', '0', '', 'IC�˴�', '��L', '�u���', '������', '���q'}
    for rec in sq:
        nm = rec['sector__name']
        if nm and nm not in bad_names:
            stock_to_sector[rec['stock_id']] = nm

    # ── 4. 撈 DailyPrice ──
    all_needed = sorted(set(curr_dates + prev_dates))
    prices = DailyPrice.objects.filter(
        date__in=all_needed,
        trade_value__isnull=False,
        trade_value__gt=0,
    ).values('date', 'stock_id', 'trade_value')

    if not prices:
        return render(request, 'analysis/trade_value_ranking.html', {'error': '無成交金額資料'})

    df = pd.DataFrame(list(prices))
    df['sector'] = df['stock_id'].map(stock_to_sector)
    df = df[df['sector'].notna()].copy()
    if df.empty:
        return render(request, 'analysis/trade_value_ranking.html', {'error': '無族群分類資料'})
    df['trade_value'] = df['trade_value'].astype(float)

    # ── 5. 每日 × 族群 匯總 ──
    daily_sector = df.groupby(['date', 'sector'], as_index=False)['trade_value'].sum()

    # ── 6. 計算區間增減 ──
    curr_agg = daily_sector[daily_sector['date'].isin(curr_dates)].groupby('sector', as_index=False)['trade_value'].sum()
    prev_agg = daily_sector[daily_sector['date'].isin(prev_dates)].groupby('sector', as_index=False)['trade_value'].sum()
    curr_agg.columns = ['sector', 'curr_val']
    prev_agg.columns = ['sector', 'prev_val']

    merged = pd.merge(curr_agg, prev_agg, on='sector', how='left').fillna(0)
    merged['abs_change'] = merged['curr_val'] - merged['prev_val']
    merged['pct_change'] = np.where(
        merged['prev_val'] > 0,
        (merged['abs_change'] / merged['prev_val']) * 100,
        0.0
    )
    # 排除兩個期間都沒資料的
    merged = merged[(merged['curr_val'] > 0) | (merged['prev_val'] > 0)].copy()

    if merged.empty:
        return render(request, 'analysis/trade_value_ranking.html', {'error': '計算後無有效資料'})

    # ── 7. 排序 ──
    abs_sorted = merged.sort_values('abs_change', ascending=False).reset_index(drop=True)
    pct_sorted = merged.sort_values('pct_change', ascending=False).reset_index(drop=True)
    abs_sorted['rank'] = range(1, len(abs_sorted) + 1)
    pct_sorted['rank'] = range(1, len(pct_sorted) + 1)

    # ── 8. 畫 Treemap 矩形樹狀圖（只取前 50 名避免太擠） ──
    def _treemap_chart(sorted_df, val_col, fmt, title):
        df = sorted_df.head(50).copy() if len(sorted_df) > 50 else sorted_df
        vals = df[val_col].tolist()
        labels = df['sector'].tolist()

        sizes = [abs(v) for v in vals]
        colors = ['#22c55e' if v >= 0 else '#ef4444' for v in vals]
        text_vals = [fmt.format(v=v) for v in vals]

        fig = go.Figure()
        fig.add_trace(go.Treemap(
            labels=labels,
            parents=[''] * len(labels),
            values=sizes,
            marker=dict(
                colors=colors,
                line=dict(width=1.5, color='rgba(255,255,255,0.6)'),
                pad=dict(t=3, l=3, r=3, b=3),
            ),
            text=text_vals,
            textinfo='label+text',
            textfont=dict(size=15, color='white', family='Arial Black'),
            hovertemplate='<b>%{label}</b><br>%{customdata}<extra></extra>',
            customdata=[[v] for v in text_vals],
            branchvalues='total',
            tiling=dict(packing='squarify', pad=3),
        ))

        fig.update_layout(
            title=dict(text=title, font=dict(size=18, color='#1f2937')),
            height=520,
            margin=dict(l=5, r=5, t=50, b=5),
            paper_bgcolor='white',
            hoverlabel=dict(bgcolor='#1f2937', font_size=13, font_color='white'),
        )
        return fig.to_html(full_html=False, include_plotlyjs=False)

    abs_chart = _treemap_chart(
        abs_sorted, 'abs_change', '{v:+,.0f}',
        f'成交金額增減（絕對值）— {curr_label}'
    )
    pct_chart = _treemap_chart(
        pct_sorted, 'pct_change', '{v:+.2f}%',
        f'成交金額增減（%）— {curr_label}'
    )

    # ── 9. 族群每日明細（當選定族群時） ──
    all_sectors = sorted(merged['sector'].unique().tolist())
    detail_rows = []

    if selected_sector and selected_sector in merged['sector'].values:
        for d in sorted(curr_dates):
            day_df = daily_sector[daily_sector['date'] == d].copy()
            if day_df.empty:
                continue

            # 找到前一個交易日
            prev_d = None
            for pd_candidate in all_dates:
                if pd_candidate < d:
                    prev_d = pd_candidate
                    break

            s_row = day_df[day_df['sector'] == selected_sector]
            if s_row.empty:
                continue
            curr_val = s_row['trade_value'].iloc[0]

            if prev_d:
                prev_day_df = daily_sector[(daily_sector['date'] == prev_d) & (daily_sector['sector'] == selected_sector)]
                prev_val = prev_day_df['trade_value'].iloc[0] if not prev_day_df.empty else 0.0
            else:
                prev_val = 0.0

            abs_ch = curr_val - prev_val
            pct_ch = (abs_ch / prev_val * 100) if prev_val > 0 else 0.0

            # 計算當日所有族群的排名
            if prev_d:
                day_merged = pd.merge(
                    day_df[['sector', 'trade_value']].rename(columns={'trade_value': 'curr'}),
                    daily_sector[daily_sector['date'] == prev_d][['sector', 'trade_value']].rename(columns={'trade_value': 'prev'}),
                    on='sector', how='left'
                ).fillna(0)
                day_merged['abs'] = day_merged['curr'] - day_merged['prev']
                day_merged['pct'] = np.where(
                    day_merged['prev'] > 0,
                    (day_merged['abs'] / day_merged['prev']) * 100,
                    0.0
                )
                day_merged['abs_rk'] = day_merged['abs'].rank(ascending=False, method='min').astype(int)
                day_merged['pct_rk'] = day_merged['pct'].rank(ascending=False, method='min').astype(int)

                r = day_merged[day_merged['sector'] == selected_sector].iloc[0]
                detail_rows.append({
                    'date': d,
                    'curr_val': curr_val,
                    'prev_val': prev_val,
                    'abs_change': abs_ch,
                    'pct_change': pct_ch,
                    'abs_rank': int(r['abs_rk']),
                    'pct_rank': int(r['pct_rk']),
                })
            else:
                detail_rows.append({
                    'date': d,
                    'curr_val': curr_val,
                    'prev_val': prev_val,
                    'abs_change': abs_ch,
                    'pct_change': pct_ch,
                    'abs_rank': '-',
                    'pct_rank': '-',
                })

    context = {
        'error': '',
        'mode': mode,
        'curr_label': curr_label,
        'latest_date': latest_date,
        'all_dates': all_dates[:60],
        'all_sectors': all_sectors,
        'selected_sector': selected_sector,
        'date_val': request.GET.get('date', str(latest_date)),
        'date_from': request.GET.get('date_from', ''),
        'date_to': request.GET.get('date_to', ''),
        'n_val': request.GET.get('n', '20'),
        'abs_chart': abs_chart,
        'pct_chart': pct_chart,
        'detail_rows': detail_rows,
    }
    return render(request, 'analysis/trade_value_ranking.html', context)


def buy_pool_view(request):
    """選股掃描結果 (Buy Pool) 頁面"""
    from django.core.paginator import Paginator
    from datetime import date, timedelta

    # 取得最新掃描日期範圍
    all_dates = BuyPool.objects.order_by('-date').values_list('date', flat=True).distinct()

    # 日期過濾
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    search = request.GET.get('search', '').strip()
    scenario_filter = request.GET.get('scenario', '')
    first_r_date_filter = request.GET.get('first_r_date', '')
    market_cap_min_str = request.GET.get('market_cap_min', '')
    sort_by = request.GET.get('sort', '-date')
    page = request.GET.get('page', 1)

    qs = BuyPool.objects.select_related('stock__sector_mapping__sector')

    # Deduplicate: per (date, stock_code), keep only the latest id
    from django.db.models import Max
    latest_ids = BuyPool.objects.values('date', 'stock_code').annotate(
        max_id=Max('id')
    ).values_list('max_id', flat=True)
    qs = qs.filter(id__in=latest_ids)

    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    if search:
        qs = qs.filter(
            models.Q(stock_code__icontains=search) | models.Q(stock_name__icontains=search)
        )
    if scenario_filter:
        qs = qs.filter(scenario=scenario_filter)
    if first_r_date_filter:
        if first_r_date_filter == 'true':
            qs = qs.filter(first_r_date=True)
        elif first_r_date_filter == 'false':
            qs = qs.filter(first_r_date=False)
    if market_cap_min_str:
        market_cap_min = int(market_cap_min_str) * 100_000_000
        qs = qs.filter(market_cap__gte=market_cap_min)

    valid_sorts = ['date', '-date', 'stock_code', 'd', 'r20', 'scenario', 'market_cap', '-market_cap', '-r20', 'return_rate', '-return_rate']
    if sort_by in valid_sorts:
        qs = qs.order_by(sort_by)
    else:
        qs = qs.order_by('-date')

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(page)

    # Build top-5 sector lookup for current page dates
    page_dates = {item.date for item in page_obj}
    if page_dates:
        date_to_top5_sectors = {}
        for d in page_dates:
            top5 = SectorDivergence.objects.filter(date=d).order_by('-divergence')[:5]
            date_to_top5_sectors[d] = {r.sector_name for r in top5}
    else:
        date_to_top5_sectors = {}

    # Build dicts for template (no underscore prefix)
    sector_names = {}
    is_sector_top5 = {}
    for item in page_obj:
        sector_name = '-'
        try:
            sector_name = item.stock.sector_mapping.sector.name or '-'
        except Exception:
            pass
        sector_names[item.id] = sector_name
        is_sector_top5[item.id] = (
            item.date in date_to_top5_sectors
            and sector_name in date_to_top5_sectors[item.date]
        )

    # 統計摘要
    total_count = paginator.count
    latest_date = BuyPool.objects.order_by('-date').values_list('date', flat=True).first()
    available_dates = list(all_dates[:30])

    context = {
        'page_obj': page_obj,
        'total_count': total_count,
        'latest_date': latest_date,
        'available_dates': available_dates,
        'date_from': date_from,
        'date_to': date_to,
        'search': search,
        'scenario_filter': scenario_filter,
        'first_r_date_filter': first_r_date_filter,
        'market_cap_min_str': market_cap_min_str,
        'sort_by': sort_by,
        'sector_names': sector_names,
        'is_sector_top5': is_sector_top5,
    }

    return render(request, 'analysis/buy_pool.html', context)
