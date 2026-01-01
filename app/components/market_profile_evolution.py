"""
Market Profile Evolution 可视化组件 v2

显示 4 个 Phase 的 Market Profile 并排对比：
- 绿色 = 买方 (Aggressive Buy)
- 红色 = 卖方 (Aggressive Sell)  
- 蓝色条 = POC (Point of Control)
- 紫色星 = POMD (Point of Max Disagreement)
- 红色区域 = Tail (被拒绝的概率区)
- 蓝色虚线 = VAH/VAL
- 绿色虚线 = 当前价格
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Dict, List, Optional, Tuple
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.metrics import (
    calculate_consensus_band,
    calculate_poc,
    calculate_pomd,
    calculate_tails
)


def analyze_phase_histogram(histogram: Dict[float, Dict]) -> Dict:
    """
    分析单个 Phase 的 histogram，计算所有指标
    
    Args:
        histogram: {price_bin: {'volume': x, 'buy': y, 'sell': z}}
    
    Returns:
        {
            'poc': float,
            'pomd': float,
            'vah': float,
            'val': float,
            'upper_tail': list,
            'lower_tail': list,
            'sorted_prices': list,
            'buy_volumes': list,
            'sell_volumes': list,
            'total_volumes': list
        }
    """
    if not histogram:
        return None
    
    sorted_prices = sorted(histogram.keys())
    buy_volumes = [histogram[p].get('buy', 0) for p in sorted_prices]
    sell_volumes = [histogram[p].get('sell', 0) for p in sorted_prices]
    total_volumes = [
        histogram[p].get('volume', 0) or (histogram[p].get('buy', 0) + histogram[p].get('sell', 0))
        for p in sorted_prices
    ]
    
    # 简化版 histogram（只有 volume）用于 VAH/VAL/POC/Tail 计算
    simple_histogram = {p: total_volumes[i] for i, p in enumerate(sorted_prices)}
    
    # POC
    poc = calculate_poc(simple_histogram)
    
    # VAH/VAL
    vah, val, mid = calculate_consensus_band(simple_histogram)
    
    # Tails
    tails = calculate_tails(simple_histogram, vah, val) if vah and val else {'upper_tail': [], 'lower_tail': []}
    
    # POMD（需要 buy/sell 分开的 histogram）
    aggressor_histogram = {
        p: {'buy': histogram[p].get('buy', 0), 'sell': histogram[p].get('sell', 0)}
        for p in histogram
    }
    pomd = calculate_pomd(aggressor_histogram)
    
    return {
        'poc': poc,
        'pomd': pomd,
        'vah': vah,
        'val': val,
        'upper_tail': tails.get('upper_tail', []),
        'lower_tail': tails.get('lower_tail', []),
        'sorted_prices': sorted_prices,
        'buy_volumes': buy_volumes,
        'sell_volumes': sell_volumes,
        'total_volumes': total_volumes
    }


def create_market_profile_evolution(
    phase_histograms: Dict[int, Dict[float, Dict]],
    phase_metadata: Dict[int, Dict] = None,
    current_price: float = None,
    current_phase: int = None,
    title: str = "Market Profile Evolution",
    height: int = 500
) -> go.Figure:
    """
    创建 4 个 Phase 并排的 Market Profile Evolution 图表
    
    Args:
        phase_histograms: {phase_number: {price_bin: {'volume', 'buy', 'sell'}}}
        phase_metadata: {phase_number: {'poc', 'pomd', 'vah', 'val', 'status', ...}} 
                        可选，从 lifecycle_phases 表读取的元数据
        current_price: 当前价格
        current_phase: 当前所处的 phase (1-4)
        title: 图表标题
        height: 图表高度
    
    Returns:
        Plotly Figure
    """
    # 创建 4 列子图
    fig = make_subplots(
        rows=1, 
        cols=4,
        subplot_titles=['Phase 1', 'Phase 2', 'Phase 3', 'Phase 4'],
        shared_yaxes=True,
        horizontal_spacing=0.03
    )
    
    # 收集所有价格范围，统一 Y 轴
    all_prices = []
    for phase_num, histogram in phase_histograms.items():
        if histogram:
            all_prices.extend(histogram.keys())
    
    if current_price:
        all_prices.append(current_price)
    
    if all_prices:
        y_min = min(all_prices) - 0.03
        y_max = max(all_prices) + 0.03
    else:
        y_min, y_max = 0, 1
    
    # 计算全局最大 volume（用于统一条形宽度比例）
    global_max_vol = 0
    for histogram in phase_histograms.values():
        if histogram:
            for data in histogram.values():
                vol = data.get('buy', 0) + data.get('sell', 0)
                global_max_vol = max(global_max_vol, vol)
    
    if global_max_vol == 0:
        global_max_vol = 1
    
    # 为每个 Phase 添加 Profile
    for phase_num in range(1, 5):
        histogram = phase_histograms.get(phase_num, {})
        metadata = (phase_metadata or {}).get(phase_num, {})
        is_current = (current_phase == phase_num) if current_phase else False
        
        if not histogram:
            # 显示 "No Data"
            fig.add_annotation(
                text="No Data",
                xref=f"x{phase_num}" if phase_num > 1 else "x",
                yref="y",
                x=0.5,
                y=(y_min + y_max) / 2,
                showarrow=False,
                font=dict(size=14, color='#9ca3af')
            )
            continue
        
        # 分析 histogram
        analysis = analyze_phase_histogram(histogram)
        if not analysis:
            continue
        
        sorted_prices = analysis['sorted_prices']
        buy_volumes = analysis['buy_volumes']
        sell_volumes = analysis['sell_volumes']
        total_volumes = analysis['total_volumes']
        
        # 使用 metadata 中的值（如果有），否则用计算值
        poc = metadata.get('poc') or analysis['poc']
        pomd = metadata.get('pomd') or analysis['pomd']
        vah = metadata.get('vah') or metadata.get('va_high') or analysis['vah']
        val = metadata.get('val') or metadata.get('va_low') or analysis['val']
        upper_tail = analysis['upper_tail']
        lower_tail = analysis['lower_tail']
        
        # 确定每个价格的颜色
        # Tail = 红色, Value Area = 正常, POC = 蓝色
        tail_prices = set(upper_tail + lower_tail)
        
        for i, price in enumerate(sorted_prices):
            buy_vol = buy_volumes[i]
            sell_vol = sell_volumes[i]
            total_vol = total_volumes[i]
            
            is_tail = price in tail_prices
            is_poc = (poc is not None and abs(price - poc) < 0.005)
            
            if is_poc:
                # POC: 蓝色条，覆盖整个宽度
                fig.add_trace(go.Bar(
                    y=[price],
                    x=[total_vol],
                    orientation='h',
                    marker_color='rgba(59, 130, 246, 1.0)',  # 蓝色
                    showlegend=False,
                    hovertemplate=f'POC: {price:.2f}<br>Volume: {total_vol:,.0f}<extra></extra>'
                ), row=1, col=phase_num)
            elif is_tail:
                # Tail: 红色背景，仍然显示买卖
                # 先画红色背景
                fig.add_trace(go.Bar(
                    y=[price],
                    x=[buy_vol],
                    orientation='h',
                    marker_color='rgba(239, 68, 68, 0.6)',  # 淡红色
                    showlegend=False,
                    hovertemplate=f'Tail: {price:.2f}<br>Buy: {buy_vol:,.0f}<extra></extra>'
                ), row=1, col=phase_num)
                fig.add_trace(go.Bar(
                    y=[price],
                    x=[sell_vol],
                    orientation='h',
                    marker_color='rgba(239, 68, 68, 0.9)',  # 深红色
                    showlegend=False,
                    hovertemplate=f'Tail: {price:.2f}<br>Sell: {sell_vol:,.0f}<extra></extra>'
                ), row=1, col=phase_num)
            else:
                # 正常区域：绿色买，红色卖
                if buy_vol > 0:
                    fig.add_trace(go.Bar(
                        y=[price],
                        x=[buy_vol],
                        orientation='h',
                        marker_color='rgba(34, 197, 94, 0.8)',  # 绿色
                        showlegend=False,
                        hovertemplate=f'Price: {price:.2f}<br>Buy: {buy_vol:,.0f}<extra></extra>'
                    ), row=1, col=phase_num)
                if sell_vol > 0:
                    fig.add_trace(go.Bar(
                        y=[price],
                        x=[sell_vol],
                        orientation='h',
                        marker_color='rgba(239, 68, 68, 0.8)',  # 红色
                        showlegend=False,
                        hovertemplate=f'Price: {price:.2f}<br>Sell: {sell_vol:,.0f}<extra></extra>'
                    ), row=1, col=phase_num)
        
        # 添加 POMD 标记（紫色星形）
        if pomd is not None:
            # 找到 POMD 对应的 volume
            pomd_vol = 0
            for p, data in histogram.items():
                if abs(p - pomd) < 0.005:
                    pomd_vol = data.get('buy', 0) + data.get('sell', 0)
                    break
            
            fig.add_trace(go.Scatter(
                x=[pomd_vol * 0.5],  # 放在条形中间
                y=[pomd],
                mode='markers',
                marker=dict(
                    symbol='star',
                    size=14,
                    color='#8b5cf6',  # 紫色
                    line=dict(width=1, color='white')
                ),
                showlegend=False,
                hovertemplate=f'POMD: {pomd:.2f}<extra></extra>'
            ), row=1, col=phase_num)
        
        # 添加 VAH/VAL 水平线
        if vah is not None:
            fig.add_shape(
                type="line",
                x0=0, x1=1, xref=f"x{phase_num} domain" if phase_num > 1 else "x domain",
                y0=vah, y1=vah,
                line=dict(color='rgba(59, 130, 246, 0.6)', width=1, dash='dot'),
                row=1, col=phase_num
            )
        
        if val is not None:
            fig.add_shape(
                type="line",
                x0=0, x1=1, xref=f"x{phase_num} domain" if phase_num > 1 else "x domain",
                y0=val, y1=val,
                line=dict(color='rgba(59, 130, 246, 0.6)', width=1, dash='dot'),
                row=1, col=phase_num
            )
    
    # 添加当前价格线（跨所有子图）
    if current_price is not None:
        for col in range(1, 5):
            fig.add_hline(
                y=current_price,
                line_dash="dash",
                line_color="#22c55e",
                line_width=2,
                row=1,
                col=col
            )
        
        # 在最后一列添加标注
        fig.add_annotation(
            text=f"{current_price*100:.0f}%",
            xref="paper",
            yref="y",
            x=1.02,
            y=current_price,
            xanchor="left",
            showarrow=False,
            font=dict(size=11, color='#22c55e', weight='bold')
        )
    
    # 更新布局
    fig.update_layout(
        title=dict(text=title, font=dict(size=16)) if title else None,
        height=height,
        barmode='stack',
        showlegend=False,
        margin=dict(l=60, r=60, t=60 if title else 30, b=40),
        plot_bgcolor='#fafafa',
        paper_bgcolor='white'
    )
    
    # 更新 Y 轴（价格轴）- 只在第一列显示
    fig.update_yaxes(
        range=[y_min, y_max],
        tickformat='.0%',
        gridcolor='rgba(0,0,0,0.08)',
        title_text="Probability",
        row=1, col=1
    )
    
    for col in range(2, 5):
        fig.update_yaxes(
            range=[y_min, y_max],
            showticklabels=False,
            gridcolor='rgba(0,0,0,0.08)',
            row=1, col=col
        )
    
    # 更新 X 轴（成交量轴）- 隐藏刻度
    for col in range(1, 5):
        fig.update_xaxes(
            showticklabels=False,
            showgrid=False,
            zeroline=False,
            row=1, col=col
        )
    
    return fig


def create_profile_legend_html() -> str:
    """
    创建图例 HTML
    """
    return """
<div style="display:flex;gap:24px;justify-content:center;align-items:center;margin:12px 0;font-size:13px;">
    <div style="display:flex;align-items:center;gap:6px;">
        <div style="width:14px;height:14px;background:rgba(34,197,94,0.8);border-radius:2px;"></div>
        <span>Buy</span>
    </div>
    <div style="display:flex;align-items:center;gap:6px;">
        <div style="width:14px;height:14px;background:rgba(239,68,68,0.8);border-radius:2px;"></div>
        <span>Sell</span>
    </div>
    <div style="display:flex;align-items:center;gap:6px;">
        <div style="width:14px;height:14px;background:rgba(59,130,246,1.0);border-radius:2px;"></div>
        <span>POC</span>
    </div>
    <div style="display:flex;align-items:center;gap:6px;">
        <div style="width:14px;height:14px;display:flex;justify-content:center;align-items:center;">
            <span style="color:#8b5cf6;font-size:16px;">★</span>
        </div>
        <span>POMD</span>
    </div>
    <div style="display:flex;align-items:center;gap:6px;">
        <div style="width:14px;height:2px;background:#22c55e;border-style:dashed;"></div>
        <span>Current</span>
    </div>
    <div style="display:flex;align-items:center;gap:6px;">
        <div style="width:14px;height:2px;background:rgba(59,130,246,0.6);border-style:dotted;"></div>
        <span>VAH/VAL</span>
    </div>
</div>
"""


# 测试
if __name__ == "__main__":
    print("🧪 Testing Market Profile Evolution v2")
    
    # 模拟 4 个 Phase 的数据（展示收敛过程）
    test_phase_histograms = {
        # Phase 1: 宽分布，不确定性高
        1: {
            0.35: {'buy': 80, 'sell': 90, 'volume': 170},
            0.40: {'buy': 120, 'sell': 130, 'volume': 250},
            0.45: {'buy': 200, 'sell': 180, 'volume': 380},
            0.50: {'buy': 350, 'sell': 300, 'volume': 650},
            0.55: {'buy': 400, 'sell': 380, 'volume': 780},  # POC
            0.60: {'buy': 300, 'sell': 320, 'volume': 620},
            0.65: {'buy': 150, 'sell': 180, 'volume': 330},
            0.70: {'buy': 60, 'sell': 80, 'volume': 140},
        },
        # Phase 2: 开始收敛
        2: {
            0.45: {'buy': 100, 'sell': 90, 'volume': 190},
            0.50: {'buy': 200, 'sell': 180, 'volume': 380},
            0.55: {'buy': 350, 'sell': 320, 'volume': 670},
            0.60: {'buy': 500, 'sell': 450, 'volume': 950},  # POC 上移
            0.65: {'buy': 400, 'sell': 380, 'volume': 780},
            0.70: {'buy': 200, 'sell': 220, 'volume': 420},
            0.75: {'buy': 80, 'sell': 100, 'volume': 180},
        },
        # Phase 3: 继续收敛
        3: {
            0.55: {'buy': 80, 'sell': 70, 'volume': 150},
            0.60: {'buy': 200, 'sell': 180, 'volume': 380},
            0.65: {'buy': 400, 'sell': 350, 'volume': 750},
            0.70: {'buy': 600, 'sell': 500, 'volume': 1100},  # POC
            0.75: {'buy': 350, 'sell': 300, 'volume': 650},
            0.80: {'buy': 120, 'sell': 100, 'volume': 220},
        },
        # Phase 4: 接近确定
        4: {
            0.65: {'buy': 50, 'sell': 40, 'volume': 90},
            0.70: {'buy': 150, 'sell': 120, 'volume': 270},
            0.75: {'buy': 300, 'sell': 250, 'volume': 550},
            0.80: {'buy': 550, 'sell': 450, 'volume': 1000},  # POC
            0.85: {'buy': 250, 'sell': 200, 'volume': 450},
            0.90: {'buy': 80, 'sell': 60, 'volume': 140},
        }
    }
    
    # 模拟 metadata
    test_metadata = {
        1: {'poc': 0.55, 'pomd': 0.50, 'vah': 0.62, 'val': 0.48},
        2: {'poc': 0.60, 'pomd': 0.55, 'vah': 0.68, 'val': 0.52},
        3: {'poc': 0.70, 'pomd': 0.65, 'vah': 0.76, 'val': 0.62},
        4: {'poc': 0.80, 'pomd': 0.75, 'vah': 0.86, 'val': 0.72},
    }
    
    fig = create_market_profile_evolution(
        phase_histograms=test_phase_histograms,
        phase_metadata=test_metadata,
        current_price=0.82,
        current_phase=4,
        title="Market Profile Evolution"
    )
    
    print("✅ Figure created successfully")
    print(f"   Traces: {len(fig.data)}")
    
    # 保存为 HTML 查看
    # fig.write_html("/tmp/profile_evolution_test.html")
    # print("   Saved to /tmp/profile_evolution_test.html")
    
    print("\n📋 Legend HTML:")
    print(create_profile_legend_html())
