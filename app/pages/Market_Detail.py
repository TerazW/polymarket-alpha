import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from sqlalchemy import text
import sys
import os

# 添加项目根目录到 Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from utils.db import get_session

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
                m.categories,
                m.volume_24h,
                m.current_price,
                dm.status,
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
            ORDER BY date ASC
        """)
        result = session.execute(query, {'token_id': token_id})
        df = pd.DataFrame(result.fetchall(), columns=result.keys())
        return df
    except Exception as e:
        return pd.DataFrame()
    finally:
        session.close()


def get_lifecycle_phases(token_id: str):
    """获取 lifecycle phases 数据"""
    session = get_session()
    try:
        query = text("""
            SELECT 
                phase_number,
                phase_start,
                phase_end,
                is_valid,
                validity_reason,
                va_high,
                va_low,
                band_width,
                poc,
                pomd,
                ui,
                cer,
                trade_count,
                total_volume,
                price_at_end,
                status
            FROM lifecycle_phases
            WHERE token_id = :token_id
            ORDER BY phase_number ASC
        """)
        result = session.execute(query, {'token_id': token_id})
        df = pd.DataFrame(result.fetchall(), columns=result.keys())
        return df
    except Exception as e:
        return pd.DataFrame()
    finally:
        session.close()


def get_status_color(status: str) -> str:
    """获取状态对应的颜色"""
    if status and 'Informed' in status:
        return '#28a745'  # 绿色
    elif status and 'Fragmented' in status:
        return '#ffc107'  # 黄色
    elif status and 'Noisy' in status:
        return '#dc3545'  # 红色
    return '#6c757d'  # 灰色


def create_consensus_band_chart(va_high, va_low, current_price, pomd):
    """创建共识带可视化（当前）"""
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
        
        # VAH 线
        fig.add_hline(
            y=va_high * 100, 
            line_dash="dash", 
            line_color="blue",
            annotation_text=f"VAH: {va_high*100:.1f}%",
            annotation_position="right"
        )
        
        # VAL 线
        fig.add_hline(
            y=va_low * 100, 
            line_dash="dash", 
            line_color="blue",
            annotation_text=f"VAL: {va_low*100:.1f}%",
            annotation_position="right"
        )
    
    # 当前价格线
    if current_price is not None:
        fig.add_hline(
            y=current_price * 100, 
            line_color="green",
            line_width=3,
            annotation_text=f"Current: {current_price*100:.1f}%",
            annotation_position="left"
        )
    
    # POMD 点
    if pomd is not None:
        fig.add_hline(
            y=pomd * 100, 
            line_dash="dot", 
            line_color="red",
            annotation_text=f"POMD: {pomd*100:.1f}%",
            annotation_position="right"
        )
    
    fig.update_layout(
        title="Current Consensus Band",
        yaxis_title="Probability (%)",
        yaxis=dict(range=[0, 100]),
        xaxis=dict(showticklabels=False),
        height=400,
        showlegend=False
    )
    
    return fig


def create_evolution_band_chart(phases_df, current_price=None):
    """
    创建 Evolution Band 可视化
    显示每个 phase 的 band 演变
    """
    if phases_df.empty:
        return None
    
    fig = go.Figure()
    
    # 颜色方案：从浅到深
    colors = [
        'rgba(66, 133, 244, 0.2)',   # Phase 1 - 最浅
        'rgba(66, 133, 244, 0.4)',   # Phase 2
        'rgba(66, 133, 244, 0.6)',   # Phase 3
        'rgba(66, 133, 244, 0.8)',   # Phase 4 - 最深
    ]
    
    border_colors = [
        'rgba(66, 133, 244, 0.4)',
        'rgba(66, 133, 244, 0.6)',
        'rgba(66, 133, 244, 0.8)',
        'rgba(66, 133, 244, 1.0)',
    ]
    
    # 为每个 phase 添加 band
    for idx, row in phases_df.iterrows():
        phase_num = row['phase_number']
        va_high = row['va_high']
        va_low = row['va_low']
        is_valid = row['is_valid']
        
        x_start = phase_num - 0.4
        x_end = phase_num + 0.4
        
        if va_high is not None and va_low is not None:
            # Band 区域
            fill_color = colors[min(phase_num - 1, 3)]
            border_color = border_colors[min(phase_num - 1, 3)]
            
            # 如果不达标，用虚线和灰色
            if not is_valid:
                fill_color = 'rgba(150, 150, 150, 0.2)'
                border_color = 'rgba(150, 150, 150, 0.5)'
            
            fig.add_shape(
                type="rect",
                x0=x_start, x1=x_end,
                y0=va_low * 100, y1=va_high * 100,
                fillcolor=fill_color,
                line=dict(
                    color=border_color, 
                    width=2,
                    dash='dash' if not is_valid else 'solid'
                ),
            )
            
            # POC 标记
            poc = row.get('poc')
            if poc is not None and is_valid:
                fig.add_trace(go.Scatter(
                    x=[phase_num],
                    y=[poc * 100],
                    mode='markers',
                    marker=dict(
                        symbol='diamond',
                        size=10,
                        color='orange',
                    ),
                    name=f'POC P{phase_num}',
                    showlegend=False,
                    hovertemplate=f'Phase {phase_num} POC: {poc*100:.1f}%<extra></extra>'
                ))
    
    # 添加当前价格线
    if current_price is not None:
        fig.add_hline(
            y=current_price * 100,
            line_color="green",
            line_width=2,
            line_dash="dash",
            annotation_text=f"Current: {current_price*100:.1f}%",
            annotation_position="right"
        )
    
    # 更新布局
    fig.update_layout(
        title="📈 Consensus Band Evolution",
        xaxis_title="Phase",
        yaxis_title="Probability (%)",
        xaxis=dict(
            tickmode='array',
            tickvals=[1, 2, 3, 4],
            ticktext=['Phase 1<br>(0-25%)', 'Phase 2<br>(25-50%)', 'Phase 3<br>(50-75%)', 'Phase 4<br>(75-100%)'],
            range=[0.5, 4.5]
        ),
        yaxis=dict(range=[0, 100]),
        height=450,
        showlegend=False,
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
col_header1, col_header2, col_header3 = st.columns([2, 1, 1])

with col_header1:
    # 显示多分类（如果有）
    categories_str = market.get('category', 'Other')
    if market.get('categories'):
        try:
            import json
            cats = json.loads(market['categories']) if isinstance(market['categories'], str) else market['categories']
            if cats:
                categories_str = ', '.join(cats)
        except:
            pass
    
    st.markdown(f"""
    <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
        <span style="background: {status_color}; color: white; padding: 5px 15px; border-radius: 20px; font-weight: bold;">
            {market['status']}
        </span>
        <span style="background: #e9ecef; padding: 5px 15px; border-radius: 20px;">
            {categories_str}
        </span>
    </div>
    """, unsafe_allow_html=True)

with col_header2:
    price_val = market['current_price'] if market['current_price'] else 0
    st.metric("Current Price", f"{price_val*100:.1f}%")

with col_header3:
    st.metric("24h Volume", f"${market['volume_24h']:,.0f}")

st.markdown("---")

# === Tab 布局 ===
tab1, tab2, tab3 = st.tabs(["📈 Current Band", "🔄 Evolution", "📊 History"])

# === Tab 1: Current Consensus Band ===
with tab1:
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

# === Tab 2: Evolution Band ===
with tab2:
    st.subheader("🔄 Consensus Band Evolution")
    st.markdown("*How the market consensus evolved over its lifecycle*")
    
    # 获取 lifecycle phases 数据
    phases_df = get_lifecycle_phases(token_id)
    
    if phases_df.empty:
        st.info("📭 No lifecycle data available yet. Run `python jobs/lifecycle_sync.py --backfill` to generate.")
    else:
        # 显示 Evolution Band 图表
        fig_evolution = create_evolution_band_chart(phases_df, market['current_price'])
        if fig_evolution:
            st.plotly_chart(fig_evolution, use_container_width=True)
        
        # 显示 Phase 详情表格
        st.markdown("**Phase Details:**")
        
        # 准备显示数据
        display_data = []
        for _, row in phases_df.iterrows():
            is_valid = row['is_valid']
            valid_icon = "✅" if is_valid else "⚠️"
            
            bw = row['band_width']
            bw_str = f"{bw*100:.2f}%" if bw else "N/A"
            
            vah = row['va_high']
            val = row['va_low']
            vah_str = f"{vah*100:.1f}%" if vah else "N/A"
            val_str = f"{val*100:.1f}%" if val else "N/A"
            
            ui = row['ui']
            ui_str = f"{ui:.3f}" if ui else "N/A"
            
            display_data.append({
                'Phase': f"Phase {row['phase_number']}",
                'Status': valid_icon,
                'VAH': vah_str,
                'VAL': val_str,
                'Band Width': bw_str,
                'UI': ui_str,
                'Trades': row['trade_count'] or 0,
                'Period': f"{row['phase_start'].strftime('%m/%d') if row['phase_start'] else 'N/A'} - {row['phase_end'].strftime('%m/%d') if row['phase_end'] else 'N/A'}"
            })
        
        st.dataframe(
            pd.DataFrame(display_data),
            use_container_width=True,
            hide_index=True
        )
        
        # 图例说明
        st.markdown("""
        **Legend:**
        - ✅ Valid phase (meets minimum threshold)
        - ⚠️ Insufficient data (dashed border in chart)
        - 🔶 POC (Point of Control) - highest volume price
        """)

# === Tab 3: Historical Trends ===
with tab3:
    st.subheader("📈 Historical Trends")
    
    history_df = get_market_history(token_id, days=30)
    
    if not history_df.empty and len(history_df) > 1:
        metric_tab1, metric_tab2, metric_tab3 = st.tabs(["Band Width", "UI", "CER"])
        
        with metric_tab1:
            fig_bw = px.line(
                history_df, 
                x='date', 
                y='band_width',
                title='Band Width Over Time',
                labels={'band_width': 'Band Width', 'date': 'Date'}
            )
            fig_bw.update_traces(line_color='#4285f4')
            st.plotly_chart(fig_bw, use_container_width=True)
        
        with metric_tab2:
            fig_ui = px.line(
                history_df, 
                x='date', 
                y='ui',
                title='Uncertainty Index Over Time',
                labels={'ui': 'UI', 'date': 'Date'}
            )
            fig_ui.update_traces(line_color='#ea4335')
            st.plotly_chart(fig_ui, use_container_width=True)
        
        with metric_tab3:
            fig_cer = px.line(
                history_df, 
                x='date', 
                y='cer',
                title='Convergence Efficiency Over Time',
                labels={'cer': 'CER', 'date': 'Date'}
            )
            fig_cer.update_traces(line_color='#34a853')
            # 添加参考线
            fig_cer.add_hline(y=1.0, line_dash="dash", line_color="gray", annotation_text="Expected")
            fig_cer.add_hline(y=0.5, line_dash="dot", line_color="red", annotation_text="Warning")
            st.plotly_chart(fig_cer, use_container_width=True)
    else:
        st.info("📊 Historical data will be available after a few days of syncing.")

st.markdown("---")

# === Key Metrics ===
st.subheader("📊 Key Metrics")

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
    if market['cs'] is None:
        st.markdown(create_metric_card(
            "CS (Conviction Score)",
            "N/A",
            "Requires aggressor data",
            is_locked=True
        ), unsafe_allow_html=True)
    else:
        st.markdown(create_metric_card(
            "CS (Conviction Score)",
            cs_value,
            ""
        ), unsafe_allow_html=True)

with col4:
    days_value = str(market['days_to_expiry']) if market['days_to_expiry'] else "N/A"
    st.markdown(create_metric_card(
        "Days to Resolution",
        days_value,
        ""
    ), unsafe_allow_html=True)

st.markdown("---")

# === ECR / ACR 详细信息 ===
with st.expander("📉 Convergence Analysis Details"):
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

# === 锁定指标说明 ===
with st.expander("🔒 About Locked Metrics"):
    st.markdown("""
    The following metrics are currently **locked** because they require **aggressor data** 
    (knowing who is the taker vs maker in each trade):
    
    | Metric | Definition | Why It's Locked |
    |--------|------------|-----------------|
    | **AR** (Aggressive Ratio) | `aggressive_volume / total_volume` | Need TAKER/MAKER info |
    | **Volume Delta** | `aggressive_buy - aggressive_sell` | Need TAKER/MAKER info |
    | **CS** (Conviction Score) | Directional AR | Depends on AR and Delta |
    
    These metrics will unlock when WebSocket data is available.
    Run `python jobs/ws_collector.py` to collect aggressor data.
    """)

# === 返回按钮 ===
st.markdown("---")
col_back1, col_back2, col_back3 = st.columns([1, 1, 1])

with col_back1:
    if st.button("← Back to Home"):
        st.switch_page("Home.py")

with col_back2:
    if st.button("← Back to Markets"):
        st.switch_page("pages/Market.py")

with col_back3:
    # Polymarket 链接
    st.markdown(f"[View on Polymarket ↗](https://polymarket.com/event/{market['market_id']})")