"""
Market Profile 可视化组件

提供类似传统 Market Profile 的图表：
- 横向条形图显示成交量分布
- Value Area (VAH/VAL) 高亮显示
- POC 标记
- Tail 区域标记
- 当前价格线
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Dict, List, Optional
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.metrics import (
    calculate_consensus_band,
    calculate_poc,
    calculate_tails,
    calculate_pomd
)


def create_market_profile_chart(
    histogram: Dict[float, float],
    current_price: float = None,
    poc: float = None,
    vah: float = None,
    val: float = None,
    pomd: float = None,
    title: str = "Market Profile"
) -> go.Figure:
    """
    创建 Market Profile 图表
    
    Args:
        histogram: {price: volume}
        current_price: 当前价格（绿色虚线）
        poc: Point of Control（橙色标记）
        vah: Value Area High
        val: Value Area Low
        pomd: Point of Max Disagreement（紫色标记）
        title: 图表标题
    
    Returns:
        Plotly Figure
    """
    if not histogram:
        fig = go.Figure()
        fig.add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
        return fig
    
    # 计算 VAH/VAL 如果没有提供
    if vah is None or val is None:
        vah, val, _ = calculate_consensus_band(histogram)
    
    # 计算 POC 如果没有提供
    if poc is None:
        poc = calculate_poc(histogram)
    
    # 计算 Tails
    tails = calculate_tails(histogram, vah, val)
    upper_tail = tails['upper_tail']
    lower_tail = tails['lower_tail']
    
    # 排序价格
    sorted_prices = sorted(histogram.keys())
    volumes = [histogram[p] for p in sorted_prices]
    max_volume = max(volumes) if volumes else 1
    
    # 确定颜色
    colors = []
    for p in sorted_prices:
        if p in upper_tail or p in lower_tail:
            colors.append('rgba(239, 68, 68, 0.7)')    # 红色 - Tail
        elif val is not None and vah is not None and val <= p <= vah:
            colors.append('rgba(59, 130, 246, 0.7)')  # 蓝色 - Value Area
        else:
            colors.append('rgba(156, 163, 175, 0.5)') # 灰色 - 其他区域
    
    # 创建图表
    fig = go.Figure()
    
    # 添加横向条形图
    fig.add_trace(go.Bar(
        y=sorted_prices,
        x=volumes,
        orientation='h',
        marker_color=colors,
        name='Volume',
        hovertemplate='Price: %{y:.2f}<br>Volume: %{x:,.0f}<extra></extra>'
    ))
    
    # 添加 POC 标记
    if poc is not None and poc in histogram:
        fig.add_trace(go.Scatter(
            x=[histogram[poc]],
            y=[poc],
            mode='markers',
            marker=dict(
                symbol='diamond',
                size=15,
                color='orange',
                line=dict(width=2, color='white')
            ),
            name=f'POC ({poc:.2f})',
            hovertemplate=f'POC: {poc:.2f}<br>Volume: {histogram[poc]:,.0f}<extra></extra>'
        ))
    
    # 添加 POMD 标记
    if pomd is not None and pomd in histogram:
        fig.add_trace(go.Scatter(
            x=[histogram[pomd]],
            y=[pomd],
            mode='markers',
            marker=dict(
                symbol='star',
                size=15,
                color='purple',
                line=dict(width=2, color='white')
            ),
            name=f'POMD ({pomd:.2f})',
            hovertemplate=f'POMD: {pomd:.2f}<br>Volume: {histogram[pomd]:,.0f}<extra></extra>'
        ))
    
    # 添加当前价格线
    if current_price is not None:
        fig.add_hline(
            y=current_price,
            line_dash="dash",
            line_color="green",
            line_width=2,
            annotation_text=f"Current: {current_price:.2f}",
            annotation_position="right"
        )
    
    # 添加 VAH/VAL 线
    if vah is not None:
        fig.add_hline(
            y=vah,
            line_dash="dot",
            line_color="blue",
            line_width=1,
            annotation_text=f"VAH: {vah:.2f}",
            annotation_position="left"
        )
    
    if val is not None:
        fig.add_hline(
            y=val,
            line_dash="dot",
            line_color="blue",
            line_width=1,
            annotation_text=f"VAL: {val:.2f}",
            annotation_position="left"
        )
    
    # 布局设置
    fig.update_layout(
        title=dict(
            text=title,
            font=dict(size=16)
        ),
        xaxis_title="Volume",
        yaxis_title="Price",
        height=500,
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        margin=dict(l=60, r=20, t=60, b=40)
    )
    
    return fig


def create_market_profile_with_aggressor(
    histogram: Dict[float, float],
    aggressor_histogram: Dict[float, Dict],
    current_price: float = None,
    title: str = "Market Profile with Aggressor"
) -> go.Figure:
    """
    创建带有 Aggressor 数据的 Market Profile
    
    显示买卖双方的成交分布
    """
    if not histogram and not aggressor_histogram:
        fig = go.Figure()
        fig.add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
        return fig
    
    # 使用 aggressor_histogram 如果有的话
    if aggressor_histogram:
        sorted_prices = sorted(aggressor_histogram.keys())
        buy_volumes = [aggressor_histogram[p].get('buy', 0) for p in sorted_prices]
        sell_volumes = [-aggressor_histogram[p].get('sell', 0) for p in sorted_prices]  # 负数显示在左边
    else:
        sorted_prices = sorted(histogram.keys())
        buy_volumes = [histogram[p] / 2 for p in sorted_prices]
        sell_volumes = [-histogram[p] / 2 for p in sorted_prices]
    
    # 计算 VAH/VAL/POC
    if histogram:
        vah, val, _ = calculate_consensus_band(histogram)
        poc = calculate_poc(histogram)
    else:
        # 从 aggressor_histogram 构建 histogram
        hist = {p: d.get('buy', 0) + d.get('sell', 0) for p, d in aggressor_histogram.items()}
        vah, val, _ = calculate_consensus_band(hist)
        poc = calculate_poc(hist)
    
    # 计算 POMD
    pomd = None
    if aggressor_histogram:
        ws_vol = sum(d.get('buy', 0) + d.get('sell', 0) for d in aggressor_histogram.values())
        pomd = calculate_pomd(aggressor_histogram, total_volume=ws_vol)
    
    # Tails
    if histogram:
        tails = calculate_tails(histogram, vah, val)
    else:
        hist = {p: d.get('buy', 0) + d.get('sell', 0) for p, d in aggressor_histogram.items()}
        tails = calculate_tails(hist, vah, val)
    
    # 创建图表
    fig = go.Figure()
    
    # 买方条形图（右边，正数）
    fig.add_trace(go.Bar(
        y=sorted_prices,
        x=buy_volumes,
        orientation='h',
        marker_color='rgba(34, 197, 94, 0.7)',  # 绿色
        name='Aggressive Buy',
        hovertemplate='Price: %{y:.2f}<br>Buy: %{x:,.0f}<extra></extra>'
    ))
    
    # 卖方条形图（左边，负数）
    fig.add_trace(go.Bar(
        y=sorted_prices,
        x=sell_volumes,
        orientation='h',
        marker_color='rgba(239, 68, 68, 0.7)',  # 红色
        name='Aggressive Sell',
        hovertemplate='Price: %{y:.2f}<br>Sell: %{customdata:,.0f}<extra></extra>',
        customdata=[-v for v in sell_volumes]
    ))
    
    # 添加 POC 标记
    if poc is not None:
        fig.add_hline(
            y=poc,
            line_dash="solid",
            line_color="orange",
            line_width=2,
            annotation_text=f"POC: {poc:.2f}",
            annotation_position="right"
        )
    
    # 添加 POMD 标记
    if pomd is not None:
        fig.add_hline(
            y=pomd,
            line_dash="dash",
            line_color="purple",
            line_width=2,
            annotation_text=f"POMD: {pomd:.2f}",
            annotation_position="left"
        )
    
    # 添加当前价格
    if current_price is not None:
        fig.add_hline(
            y=current_price,
            line_dash="dash",
            line_color="white",
            line_width=2,
            annotation_text=f"Current: {current_price:.2f}",
            annotation_position="right"
        )
    
    # VAH/VAL 区域
    if vah is not None and val is not None:
        fig.add_hrect(
            y0=val, y1=vah,
            fillcolor="rgba(59, 130, 246, 0.1)",
            line_width=0,
            annotation_text="Value Area",
            annotation_position="top left"
        )
    
    # 布局
    fig.update_layout(
        title=dict(
            text=title,
            font=dict(size=16)
        ),
        xaxis_title="Volume (← Sell | Buy →)",
        yaxis_title="Price",
        height=500,
        barmode='overlay',
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        margin=dict(l=60, r=20, t=60, b=40)
    )
    
    return fig


def create_profile_summary_metrics(
    histogram: Dict[float, float],
    aggressor_histogram: Dict[float, Dict] = None,
    current_price: float = None
) -> Dict:
    """
    计算 Market Profile 摘要指标
    
    Returns:
        {
            'poc': float,
            'vah': float,
            'val': float,
            'band_width': float,
            'pomd': float,
            'upper_tail': list,
            'lower_tail': list,
            'price_in_value_area': bool,
            'price_position': str  # 'above_va', 'in_va', 'below_va', 'at_poc'
        }
    """
    if not histogram:
        return None
    
    vah, val, mid = calculate_consensus_band(histogram)
    poc = calculate_poc(histogram)
    tails = calculate_tails(histogram, vah, val)
    
    pomd = None
    if aggressor_histogram:
        ws_vol = sum(d.get('buy', 0) + d.get('sell', 0) for d in aggressor_histogram.values())
        pomd = calculate_pomd(aggressor_histogram, total_volume=ws_vol)
    
    # 判断当前价格位置
    price_position = "unknown"
    price_in_va = False
    if current_price is not None and vah is not None and val is not None:
        if abs(current_price - poc) < 0.01 if poc else False:
            price_position = "at_poc"
            price_in_va = True
        elif val <= current_price <= vah:
            price_position = "in_va"
            price_in_va = True
        elif current_price > vah:
            price_position = "above_va"
        else:
            price_position = "below_va"
    
    return {
        'poc': poc,
        'vah': vah,
        'val': val,
        'band_width': (vah - val) if vah and val else None,
        'mid_probability': mid,
        'pomd': pomd,
        'upper_tail': tails['upper_tail'],
        'lower_tail': tails['lower_tail'],
        'price_in_value_area': price_in_va,
        'price_position': price_position,
        'total_volume': sum(histogram.values()),
        'price_levels': len(histogram)
    }


# 测试
if __name__ == "__main__":
    print("🧪 Testing Market Profile Chart")
    
    # 模拟数据
    test_histogram = {
        0.58: 100,
        0.59: 150,
        0.60: 300,
        0.61: 500,
        0.62: 800,
        0.63: 1200,
        0.64: 1800,  # POC
        0.65: 1500,
        0.66: 1000,
        0.67: 600,
        0.68: 300,
        0.69: 150,
        0.70: 80,
    }
    
    test_aggressor = {
        0.62: {'buy': 400, 'sell': 400},
        0.63: {'buy': 700, 'sell': 500},
        0.64: {'buy': 1000, 'sell': 800},  # 争议点
        0.65: {'buy': 1200, 'sell': 300},  # 买方推进
        0.66: {'buy': 600, 'sell': 400},
    }
    
    # 测试摘要
    summary = create_profile_summary_metrics(
        test_histogram,
        test_aggressor,
        current_price=0.65
    )
    
    print(f"\n📊 Profile Summary:")
    print(f"   POC: {summary['poc']}")
    print(f"   Value Area: [{summary['val']}, {summary['vah']}]")
    print(f"   Band Width: {summary['band_width']:.2f}")
    print(f"   POMD: {summary['pomd']}")
    print(f"   Upper Tail: {summary['upper_tail']}")
    print(f"   Lower Tail: {summary['lower_tail']}")
    print(f"   Price Position: {summary['price_position']}")
    
    print("\n✅ Test completed!")
