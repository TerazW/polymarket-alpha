import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from sqlalchemy import text
from datetime import datetime, timedelta
import sys
import os

# 添加项目根目录到 Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from utils.db import get_session, engine

# 页面配置
st.set_page_config(
    page_title="Market Detail",
    page_icon="📊",
    layout="wide"
)

# === 辅助函数 ===

def get_market_detail(token_id: str):
    """获取单个市场的详细信息"""
    session = get_session()
    try:
        query = text("""
            SELECT 
                m.token_id,
                m.market_id,
                m.title,
                m.category,
                m.volume_24h,
                m.current_price,
                dm.status,
                dm.impulse_tag,
                dm.edge_zone,
                dm.ui,
                dm.cer,
                dm.cs,
                dm.ecr,
                dm.acr,
                dm.va_high,
                dm.va_low,
                dm.band_width,
                dm.pomd,
                dm.days_to_expiry,
                dm.date
            FROM markets m
            JOIN daily_metrics dm ON m.token_id = dm.token_id
            WHERE m.token_id = :token_id
            AND dm.date = (SELECT MAX(date) FROM daily_metrics WHERE token_id = :token_id)
        """)
        result = session.execute(query, {'token_id': token_id}).fetchone()
        
        if result:
            return dict(result._mapping)
        return None
    finally:
        session.close()


def get_market_history(token_id: str, days: int = 30):
    """获取市场的历史数据"""
    session = get_session()
    try:
        query = text("""
            SELECT 
                date,
                ui,
                cer,
                va_high,
                va_low,
                band_width,
                current_price
            FROM daily_metrics
            WHERE token_id = :token_id
            AND date >= CURRENT_DATE - INTERVAL :days DAY
            ORDER BY date ASC
        """)
        result = session.execute(query, {'token_id': token_id, 'days': days})
        df = pd.DataFrame(result.fetchall(), columns=result.keys())
        return df
    except:
        # PostgreSQL 语法
        query = text("""
            SELECT 
                date,
                ui,
                cer,
                va_high,
                va_low,
                band_width,
                current_price
            FROM daily_metrics
            WHERE token_id = :token_id
            AND date >= (CURRENT_DATE - INTERVAL ':days days')::date
            ORDER BY date ASC
        """.replace(':days', str(days)))
        try:
            result = session.execute(query, {'token_id': token_id})
            df = pd.DataFrame(result.fetchall(), columns=result.keys())
            return df
        except:
            return pd.DataFrame()
    finally:
        session.close()


def get_histogram_from_db(token_id: str, date=None) -> dict:
    """
    从数据库获取 histogram 数据
    
    Returns:
        {price_bin: {'volume': x, 'buy': y, 'sell': z}}
    """
    if date is None:
        date = datetime.now().date()
    
    histogram = {}
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT price_bin, volume, aggressive_buy, aggressive_sell, trade_count
            FROM daily_histogram
            WHERE token_id = :token_id AND date = :date
            ORDER BY price_bin
        """), {"token_id": token_id, "date": date})
        
        for row in result.fetchall():
            price_bin = float(row[0])
            histogram[price_bin] = {
                'volume': float(row[1] or 0),
                'aggressive_buy': float(row[2] or 0),
                'aggressive_sell': float(row[3] or 0),
                'trade_count': int(row[4] or 0)
            }
    
    return histogram


def get_histogram_daterange(token_id: str, days: int = 7) -> dict:
    """获取多天累积的 histogram"""
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days)
    
    histogram = {}
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT price_bin, 
                   SUM(volume) as total_volume,
                   SUM(aggressive_buy) as total_buy,
                   SUM(aggressive_sell) as total_sell,
                   SUM(trade_count) as total_count
            FROM daily_histogram
            WHERE token_id = :token_id 
              AND date BETWEEN :start_date AND :end_date
            GROUP BY price_bin
            ORDER BY price_bin
        """), {
            "token_id": token_id, 
            "start_date": start_date,
            "end_date": end_date
        })
        
        for row in result.fetchall():
            price_bin = float(row[0])
            histogram[price_bin] = {
                'volume': float(row[1] or 0),
                'aggressive_buy': float(row[2] or 0),
                'aggressive_sell': float(row[3] or 0),
                'trade_count': int(row[4] or 0)
            }
    
    return histogram


def get_status_color(status: str) -> str:
    """获取状态对应的颜色"""
    if status is None:
        return '#6c757d'  # 灰色
    if 'Informed' in status:
        return '#28a745'  # 绿色
    elif 'Fragmented' in status:
        return '#ffc107'  # 黄色
    elif 'Noisy' in status:
        return '#dc3545'  # 红色
    elif 'Late-stage' in status:
        return '#3b82f6'  # 蓝色
    return '#6c757d'  # 灰色


# === Market Profile 可视化函数 ===

def calculate_value_area(histogram: dict, coverage: float = 0.70):
    """计算 Value Area（围绕 POC 连续扩展）"""
    if not histogram:
        return None, None, None
    
    # 转换为 volume-only 格式
    vol_histogram = {p: d['volume'] for p, d in histogram.items()}
    total_volume = sum(vol_histogram.values())
    
    if total_volume == 0:
        return None, None, None
    
    sorted_prices = sorted(vol_histogram.keys())
    if len(sorted_prices) == 0:
        return None, None, None
    
    # 找 POC
    poc = max(vol_histogram.keys(), key=lambda p: vol_histogram[p])
    poc_idx = sorted_prices.index(poc)
    
    # 从 POC 向两侧扩展
    target_volume = total_volume * coverage
    cumulative = vol_histogram[poc]
    
    low_idx = poc_idx
    high_idx = poc_idx
    
    while cumulative < target_volume:
        can_go_low = low_idx > 0
        can_go_high = high_idx < len(sorted_prices) - 1
        
        if not can_go_low and not can_go_high:
            break
        
        low_volume = vol_histogram[sorted_prices[low_idx - 1]] if can_go_low else 0
        high_volume = vol_histogram[sorted_prices[high_idx + 1]] if can_go_high else 0
        
        if can_go_low and (not can_go_high or low_volume >= high_volume):
            low_idx -= 1
            cumulative += vol_histogram[sorted_prices[low_idx]]
        elif can_go_high:
            high_idx += 1
            cumulative += vol_histogram[sorted_prices[high_idx]]
    
    val = sorted_prices[low_idx]
    vah = sorted_prices[high_idx]
    
    return poc, vah, val


def create_market_profile_chart(histogram: dict, current_price: float = None, title: str = "Market Profile"):
    """创建 Market Profile 可视化"""
    if not histogram:
        fig = go.Figure()
        fig.add_annotation(
            text="No histogram data available. Run histogram_sync.py first.",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16)
        )
        fig.update_layout(height=500)
        return fig
    
    # 计算 Value Area
    poc, vah, val = calculate_value_area(histogram)
    
    # 计算 Tails
    upper_tail = [p for p in histogram.keys() if vah and p > vah]
    lower_tail = [p for p in histogram.keys() if val and p < val]
    
    # 准备数据
    sorted_prices = sorted(histogram.keys())
    volumes = [histogram[p]['volume'] for p in sorted_prices]
    
    # 确定颜色
    colors = []
    for p in sorted_prices:
        if p in upper_tail or p in lower_tail:
            colors.append('rgba(239, 68, 68, 0.7)')    # 红色 - Tail
        elif val is not None and vah is not None and val <= p <= vah:
            colors.append('rgba(59, 130, 246, 0.7)')  # 蓝色 - Value Area
        else:
            colors.append('rgba(156, 163, 175, 0.5)') # 灰色
    
    # 创建图表
    fig = go.Figure()
    
    # 横向条形图
    fig.add_trace(go.Bar(
        y=[p * 100 for p in sorted_prices],  # 转换为百分比
        x=volumes,
        orientation='h',
        marker_color=colors,
        name='Volume',
        hovertemplate='Price: %{y:.1f}%<br>Volume: %{x:,.0f}<extra></extra>'
    ))
    
    # POC 标记
    if poc is not None:
        fig.add_trace(go.Scatter(
            x=[histogram[poc]['volume']],
            y=[poc * 100],
            mode='markers',
            marker=dict(
                symbol='diamond',
                size=15,
                color='orange',
                line=dict(width=2, color='white')
            ),
            name=f'POC ({poc*100:.1f}%)',
            hovertemplate=f'POC: {poc*100:.1f}%<br>Volume: {histogram[poc]["volume"]:,.0f}<extra></extra>'
        ))
    
    # 当前价格线
    if current_price is not None:
        fig.add_hline(
            y=current_price * 100,
            line_dash="dash",
            line_color="green",
            line_width=2,
            annotation_text=f"Current: {current_price*100:.1f}%",
            annotation_position="right"
        )
    
    # VAH/VAL 标注
    if vah is not None:
        fig.add_hline(
            y=vah * 100,
            line_dash="dot",
            line_color="blue",
            line_width=1,
            annotation_text=f"VAH: {vah*100:.1f}%",
            annotation_position="left"
        )
    
    if val is not None:
        fig.add_hline(
            y=val * 100,
            line_dash="dot",
            line_color="blue",
            line_width=1,
            annotation_text=f"VAL: {val*100:.1f}%",
            annotation_position="left"
        )
    
    # 布局
    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        xaxis_title="Volume",
        yaxis_title="Probability (%)",
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


def create_aggressor_profile_chart(histogram: dict, current_price: float = None, title: str = "Buy/Sell Profile"):
    """创建买卖双方对比的 Market Profile"""
    if not histogram:
        fig = go.Figure()
        fig.add_annotation(
            text="No aggressor data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
        return fig
    
    sorted_prices = sorted(histogram.keys())
    buy_volumes = [histogram[p]['aggressive_buy'] for p in sorted_prices]
    sell_volumes = [-histogram[p]['aggressive_sell'] for p in sorted_prices]  # 负数显示在左边
    
    fig = go.Figure()
    
    # 买方（右边，绿色）
    fig.add_trace(go.Bar(
        y=[p * 100 for p in sorted_prices],
        x=buy_volumes,
        orientation='h',
        marker_color='rgba(34, 197, 94, 0.7)',
        name='Aggressive Buy',
        hovertemplate='Price: %{y:.1f}%<br>Buy: %{x:,.0f}<extra></extra>'
    ))
    
    # 卖方（左边，红色）
    fig.add_trace(go.Bar(
        y=[p * 100 for p in sorted_prices],
        x=sell_volumes,
        orientation='h',
        marker_color='rgba(239, 68, 68, 0.7)',
        name='Aggressive Sell',
        hovertemplate='Price: %{y:.1f}%<br>Sell: %{customdata:,.0f}<extra></extra>',
        customdata=[-v for v in sell_volumes]
    ))
    
    # 当前价格
    if current_price is not None:
        fig.add_hline(
            y=current_price * 100,
            line_dash="dash",
            line_color="white",
            line_width=2,
            annotation_text=f"Current: {current_price*100:.1f}%",
            annotation_position="right"
        )
    
    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        xaxis_title="Volume (← Sell | Buy →)",
        yaxis_title="Probability (%)",
        height=500,
        barmode='overlay',
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        )
    )
    
    return fig


def create_consensus_band_chart(va_high, va_low, current_price, pomd):
    """创建共识带可视化（原版）"""
    fig = go.Figure()
    
    # 共识带区域
    if va_high is not None and va_low is not None:
        fig.add_shape(
            type="rect",
            x0=0, x1=1,
            y0=va_low * 100, y1=va_high * 100,
            fillcolor="rgba(66, 133, 244, 0.3)",
            line=dict(color="rgba(66, 133, 244, 0.8)", width=2),
        )
        
        fig.add_hline(
            y=va_high * 100, 
            line_dash="dash", 
            line_color="blue",
            annotation_text=f"VAH: {va_high*100:.1f}%",
            annotation_position="right"
        )
        
        fig.add_hline(
            y=va_low * 100, 
            line_dash="dash", 
            line_color="blue",
            annotation_text=f"VAL: {va_low*100:.1f}%",
            annotation_position="right"
        )
    
    if current_price is not None:
        fig.add_hline(
            y=current_price * 100, 
            line_color="green",
            line_width=3,
            annotation_text=f"Current: {current_price*100:.1f}%",
            annotation_position="left"
        )
    
    if pomd is not None:
        fig.add_hline(
            y=pomd * 100, 
            line_dash="dot", 
            line_color="red",
            annotation_text=f"POMD: {pomd*100:.1f}%",
            annotation_position="right"
        )
    
    fig.update_layout(
        title="Consensus Band Visualization",
        yaxis_title="Probability (%)",
        yaxis=dict(range=[0, 100]),
        xaxis=dict(showticklabels=False),
        height=400,
        showlegend=False
    )
    
    return fig


def create_metric_card(label, value, help_text="", is_locked=False):
    """创建指标卡片"""
    if is_locked:
        return f"""
        <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; text-align: center; border: 1px solid #dee2e6;">
            <div style="font-size: 14px; color: #6c757d;">{label}</div>
            <div style="font-size: 24px; font-weight: bold; color: #adb5bd;">🔒 Locked</div>
            <div style="font-size: 12px; color: #adb5bd;">{help_text}</div>
        </div>
        """
    else:
        return f"""
        <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; text-align: center; border: 1px solid #dee2e6;">
            <div style="font-size: 14px; color: #6c757d;">{label}</div>
            <div style="font-size: 24px; font-weight: bold; color: #212529;">{value}</div>
            <div style="font-size: 12px; color: #6c757d;">{help_text}</div>
        </div>
        """


# === 主界面 ===

# 检查是否有选中的市场
if 'selected_token_id' not in st.session_state:
    st.warning("⚠️ No market selected. Please select a market from the Home or Market page.")
    
    if st.button("← Go to Home"):
        st.switch_page("Home.py")
    
    st.stop()

token_id = st.session_state.selected_token_id

# 获取市场详情
market = get_market_detail(token_id)

if not market:
    st.error(f"❌ Market not found: {token_id}")
    if st.button("← Go to Home"):
        st.switch_page("Home.py")
    st.stop()

# === 页面标题 ===
st.title(f"📊 {market['title']}")

# 状态和分类
status_color = get_status_color(market['status'])
impulse_tag = market.get('impulse_tag')
col_header1, col_header2, col_header3 = st.columns([2, 1, 1])

with col_header1:
    # 构建标签列表
    impulse_html = ""
    if impulse_tag:
        # impulse_tag 颜色
        impulse_colors = {
            "⚡ EMERGING": "#8b5cf6",     # 紫色
            "🔄 ABSORPTION": "#f59e0b",   # 橙色
            "💨 EXHAUSTION": "#ef4444"    # 红色
        }
        impulse_color = impulse_colors.get(impulse_tag, "#6b7280")
        impulse_html = f'''
        <span style="background: {impulse_color}; color: white; padding: 5px 15px; border-radius: 20px; font-weight: bold; margin-left: 5px;">
            {impulse_tag}
        </span>
        '''
    
    st.markdown(f"""
    <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
        <span style="background: {status_color}; color: white; padding: 5px 15px; border-radius: 20px; font-weight: bold;">
            {market['status']}
        </span>
        {impulse_html}
        <span style="background: #e9ecef; padding: 5px 15px; border-radius: 20px;">
            {market['category']}
        </span>
    </div>
    """, unsafe_allow_html=True)

with col_header2:
    st.metric("Current Price", f"{market['current_price']*100:.1f}%")

with col_header3:
    st.metric("24h Volume", f"${market['volume_24h']:,.0f}")

st.markdown("---")

# === 主要内容 Tabs ===
main_tab1, main_tab2, main_tab3, main_tab4 = st.tabs([
    "📊 Market Profile", 
    "📈 Consensus Band", 
    "📉 Metrics", 
    "📜 History"
])

# === Tab 1: Market Profile ===
with main_tab1:
    st.subheader("📊 Market Profile")
    
    # 时间范围选择
    col_range, col_info = st.columns([1, 2])
    with col_range:
        time_range = st.selectbox(
            "Time Range",
            ["Today", "Last 3 Days", "Last 7 Days", "Last 14 Days"],
            index=2
        )
    
    # 获取对应时间范围的 histogram
    range_map = {
        "Today": 1,
        "Last 3 Days": 3,
        "Last 7 Days": 7,
        "Last 14 Days": 14
    }
    days = range_map[time_range]
    
    if days == 1:
        histogram = get_histogram_from_db(token_id)
    else:
        histogram = get_histogram_daterange(token_id, days)
    
    if histogram:
        # 计算 Profile 统计
        poc, vah, val = calculate_value_area(histogram)
        total_volume = sum(d['volume'] for d in histogram.values())
        total_buy = sum(d['aggressive_buy'] for d in histogram.values())
        total_sell = sum(d['aggressive_sell'] for d in histogram.values())
        
        with col_info:
            st.markdown(f"""
            **Profile Summary** ({time_range})
            - Total Volume: **${total_volume:,.0f}**
            - Buy/Sell: **${total_buy:,.0f}** / **${total_sell:,.0f}**
            - Price Levels: **{len(histogram)}**
            """)
        
        # 两种可视化
        profile_tab1, profile_tab2 = st.tabs(["Volume Profile", "Buy/Sell Profile"])
        
        with profile_tab1:
            fig = create_market_profile_chart(
                histogram, 
                current_price=market['current_price'],
                title=f"Volume Profile ({time_range})"
            )
            st.plotly_chart(fig, use_container_width=True)
            
            # 图例说明
            st.markdown("""
            **图例说明：**
            - 🔵 **蓝色区域**: Value Area (70% 成交量)
            - 🔴 **红色区域**: Tail (被拒绝的价格区)
            - 🟠 **橙色菱形**: POC (最大成交价格)
            - 🟢 **绿色虚线**: 当前价格
            """)
        
        with profile_tab2:
            fig2 = create_aggressor_profile_chart(
                histogram,
                current_price=market['current_price'],
                title=f"Buy/Sell Distribution ({time_range})"
            )
            st.plotly_chart(fig2, use_container_width=True)
            
            # Delta 分析
            delta = total_buy - total_sell
            delta_pct = (delta / total_volume * 100) if total_volume > 0 else 0
            
            if delta > 0:
                st.success(f"📈 Net Buying: **${delta:,.0f}** ({delta_pct:+.1f}%)")
            elif delta < 0:
                st.error(f"📉 Net Selling: **${delta:,.0f}** ({delta_pct:+.1f}%)")
            else:
                st.info("➡️ Balanced: No significant direction")
        
        # Profile 详情
        with st.expander("📋 Profile Details"):
            col_poc, col_va, col_tail = st.columns(3)
            
            with col_poc:
                st.markdown("**Point of Control (POC)**")
                if poc:
                    st.write(f"Price: {poc*100:.1f}%")
                    st.write(f"Volume: ${histogram[poc]['volume']:,.0f}")
                    st.write("*最大成交量的价格*")
                else:
                    st.write("N/A")
            
            with col_va:
                st.markdown("**Value Area**")
                if vah and val:
                    st.write(f"VAH: {vah*100:.1f}%")
                    st.write(f"VAL: {val*100:.1f}%")
                    st.write(f"Width: {(vah-val)*100:.1f}%")
                    st.write("*70% 成交量的区间*")
                else:
                    st.write("N/A")
            
            with col_tail:
                st.markdown("**Tails (Rejected Areas)**")
                upper_tail = [p for p in histogram.keys() if vah and p > vah]
                lower_tail = [p for p in histogram.keys() if val and p < val]
                
                if upper_tail:
                    st.write(f"Upper: {len(upper_tail)} levels")
                    st.write(f"  ({min(upper_tail)*100:.1f}% - {max(upper_tail)*100:.1f}%)")
                if lower_tail:
                    st.write(f"Lower: {len(lower_tail)} levels")
                    st.write(f"  ({min(lower_tail)*100:.1f}% - {max(lower_tail)*100:.1f}%)")
                if not upper_tail and not lower_tail:
                    st.write("No significant tails")
    
    else:
        st.warning("""
        ⚠️ No histogram data available for this market.
        
        **To generate data, run:**
        ```bash
        python jobs/histogram_sync.py --markets 100
        ```
        """)

# === Tab 2: Consensus Band ===
with main_tab2:
    st.subheader("📈 Consensus Band")
    
    col_chart, col_info = st.columns([2, 1])
    
    with col_chart:
        fig = create_consensus_band_chart(
            market['va_high'],
            market['va_low'],
            market['current_price'],
            market['pomd']
        )
        st.plotly_chart(fig, use_container_width=True)
    
    with col_info:
        st.markdown("**Consensus Band Metrics**")
        
        if market['va_high'] is not None:
            st.write(f"🔵 **VAH** (Value Area High): {market['va_high']*100:.2f}%")
        else:
            st.write("🔵 **VAH**: N/A")
        
        if market['va_low'] is not None:
            st.write(f"🔵 **VAL** (Value Area Low): {market['va_low']*100:.2f}%")
        else:
            st.write("🔵 **VAL**: N/A")
        
        if market['band_width'] is not None:
            st.write(f"📏 **Band Width**: {market['band_width']*100:.2f}%")
        else:
            st.write("📏 **Band Width**: N/A")
        
        if market['pomd'] is not None:
            st.write(f"🔴 **POMD** (Max Disagreement): {market['pomd']*100:.2f}%")
        else:
            st.write("🔴 **POMD**: N/A")
        
        st.markdown("---")
        st.markdown("*Consensus Band covers 70% of trading volume*")

# === Tab 3: Metrics ===
with main_tab3:
    st.subheader("📊 Key Metrics")
    
    # 显示 Impulse Tag（如果有）
    impulse_tag = market.get('impulse_tag')
    if impulse_tag:
        impulse_explanations = {
            "⚡ EMERGING": "共识正在形成 - 订单流开始单边，分歧仍大但方向明确，早期参与机会",
            "🔄 ABSORPTION": "关键位置拉锯 - 双方在当前价位对抗，一旦突破即产生强信号",
            "💨 EXHAUSTION": "末期动能警告 - 看似所有人都同意，但结构已饱和，风险较高"
        }
        explanation = impulse_explanations.get(impulse_tag, "")
        
        st.info(f"**{impulse_tag}**: {explanation}")
        st.markdown("")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        ui_value = f"{market['ui']:.3f}" if market['ui'] is not None else "N/A"
        ui_interpretation = ""
        if market['ui'] is not None:
            if market['ui'] < 0.30:
                ui_interpretation = "✅ Low Uncertainty"
            elif market['ui'] < 0.50:
                ui_interpretation = "⚠️ Moderate"
            else:
                ui_interpretation = "❌ High Uncertainty"
        
        st.markdown(create_metric_card(
            "UI (Uncertainty Index)",
            ui_value,
            ui_interpretation
        ), unsafe_allow_html=True)
    
    with col2:
        cer_value = f"{market['cer']:.3f}" if market['cer'] is not None else "N/A"
        cer_interpretation = ""
        if market['cer'] is not None:
            if market['cer'] >= 0.8:
                cer_interpretation = "✅ Healthy Convergence"
            elif market['cer'] >= 0.4:
                cer_interpretation = "⚠️ Normal"
            else:
                cer_interpretation = "❌ Blocked"
        
        st.markdown(create_metric_card(
            "CER (Convergence Efficiency)",
            cer_value,
            cer_interpretation
        ), unsafe_allow_html=True)
    
    with col3:
        cs_value = f"{market['cs']:.3f}" if market['cs'] is not None else "N/A"
        cs_locked = market['cs'] is None
        st.markdown(create_metric_card(
            "CS (Conviction Score)",
            cs_value,
            "Requires aggressor data" if cs_locked else "",
            is_locked=cs_locked
        ), unsafe_allow_html=True)
    
    with col4:
        days_value = str(market['days_to_expiry']) if market['days_to_expiry'] else "N/A"
        st.markdown(create_metric_card(
            "Days to Resolution",
            days_value,
            ""
        ), unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Convergence Analysis
    st.subheader("📉 Convergence Analysis")
    
    col_ecr, col_acr, col_cer = st.columns(3)
    
    with col_ecr:
        st.markdown("**ECR (Expected Convergence Rate)**")
        if market['ecr'] is not None:
            st.write(f"Value: {market['ecr']:.6f}")
            st.write("*How fast should the market converge based on price and time remaining*")
        else:
            st.write("N/A")
    
    with col_acr:
        st.markdown("**ACR (Actual Convergence Rate)**")
        if market['acr'] is not None:
            st.write(f"Value: {market['acr']:.6f}")
            if market['acr'] > 0:
                st.write("📈 Band is narrowing (converging)")
            elif market['acr'] < 0:
                st.write("📉 Band is widening (diverging)")
            else:
                st.write("➡️ Band is stable")
        else:
            st.write("N/A")
            st.write("*Requires 7 days of history*")
    
    with col_cer:
        st.markdown("**CER (Convergence Efficiency)**")
        if market['cer'] is not None:
            st.write(f"Value: {market['cer']:.3f}")
            st.write(f"*CER = ACR / ECR*")
            if market['cer'] > 1.0:
                st.success("Converging faster than expected! ✅")
            elif market['cer'] >= 0.5:
                st.info("Normal convergence")
            else:
                st.warning("Convergence may be blocked ⚠️")
        else:
            st.write("N/A")

# === Tab 4: History ===
with main_tab4:
    st.subheader("📈 Historical Trends")
    
    history_df = get_market_history(token_id, days=30)
    
    if not history_df.empty and len(history_df) > 1:
        history_tab1, history_tab2, history_tab3 = st.tabs(["Band Width", "UI", "CER"])
        
        with history_tab1:
            fig_bw = px.line(
                history_df, 
                x='date', 
                y='band_width',
                title='Band Width Over Time',
                labels={'band_width': 'Band Width', 'date': 'Date'}
            )
            fig_bw.update_traces(line_color='#4285f4')
            st.plotly_chart(fig_bw, use_container_width=True)
        
        with history_tab2:
            fig_ui = px.line(
                history_df, 
                x='date', 
                y='ui',
                title='Uncertainty Index Over Time',
                labels={'ui': 'UI', 'date': 'Date'}
            )
            fig_ui.update_traces(line_color='#ea4335')
            st.plotly_chart(fig_ui, use_container_width=True)
        
        with history_tab3:
            fig_cer = px.line(
                history_df, 
                x='date', 
                y='cer',
                title='Convergence Efficiency Over Time',
                labels={'cer': 'CER', 'date': 'Date'}
            )
            fig_cer.update_traces(line_color='#34a853')
            fig_cer.add_hline(y=1.0, line_dash="dash", line_color="gray", annotation_text="Expected")
            fig_cer.add_hline(y=0.5, line_dash="dot", line_color="red", annotation_text="Warning")
            st.plotly_chart(fig_cer, use_container_width=True)
    
    else:
        st.info("📊 Historical data will be available after a few days of syncing.")

st.markdown("---")

# === 返回按钮 ===
col_back1, col_back2, col_back3 = st.columns([1, 1, 1])

with col_back1:
    if st.button("← Back to Home"):
        st.switch_page("Home.py")

with col_back2:
    if st.button("← Back to Markets"):
        st.switch_page("pages/Market.py")

with col_back3:
    st.markdown(f"[View on Polymarket ↗](https://polymarket.com/event/{market['market_id']})")