"""
Market Sensemaking - 主页面 v2.1
修复 HTML 渲染和空白问题
"""

import streamlit as st
import json
from datetime import datetime
from sqlalchemy import text
import sys
import os

# 添加项目路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from utils.db import get_session

# === 页面配置 ===
st.set_page_config(
    page_title="Market Sensemaking",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# === 自定义 CSS ===
st.markdown("""
<style>
/* 隐藏 Streamlit 默认元素 */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}
[data-testid="stSidebar"] {display: none;}
[data-testid="collapsedControl"] {display: none;}

/* 减少顶部空白 */
.block-container {
    padding-top: 1rem !important;
    padding-bottom: 1rem !important;
}

/* 全局背景 */
.stApp {
    background: #f8f9fa;
}

/* 统计卡片 */
.stat-card {
    background: white;
    border-radius: 12px;
    padding: 16px 20px;
    border: 1px solid #e9ecef;
    text-align: center;
}

/* 市场卡片 */
.market-card {
    background: white;
    border-radius: 12px;
    padding: 16px;
    border: 1px solid #e9ecef;
    margin-bottom: 8px;
    min-height: 160px;
    transition: all 0.2s;
}

.market-card:hover {
    border-color: #228be6;
    box-shadow: 0 4px 12px rgba(34, 139, 230, 0.15);
}

.card-title {
    font-size: 14px;
    font-weight: 600;
    color: #1a1a2e;
    line-height: 1.4;
    margin-bottom: 10px;
    height: 40px;
    overflow: hidden;
}

.card-tags {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-bottom: 10px;
}

.status-tag {
    padding: 4px 8px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
}

.card-price-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
}

.card-price {
    font-size: 20px;
    font-weight: 700;
    color: #1a1a2e;
}

.card-volume {
    font-size: 12px;
    color: #868e96;
}

.card-category {
    font-size: 11px;
    color: #adb5bd;
    background: #f8f9fa;
    padding: 4px 8px;
    border-radius: 6px;
    display: inline-block;
}

/* 详情页指标卡片 */
.metric-card {
    background: white;
    padding: 20px;
    border-radius: 12px;
    border: 1px solid #e9ecef;
    text-align: center;
}

.metric-label {
    font-size: 13px;
    color: #868e96;
}

.metric-value {
    font-size: 28px;
    font-weight: 700;
    color: #1a1a2e;
}

/* 生命周期卡片 */
.phase-card {
    background: white;
    padding: 16px;
    border-radius: 12px;
    border: 1px solid #e9ecef;
}

.phase-card-inactive {
    background: #f8f9fa;
    padding: 16px;
    border-radius: 12px;
    border: 1px solid #e9ecef;
}
</style>
""", unsafe_allow_html=True)

# === 数据库查询函数 ===
@st.cache_data(ttl=60)
def get_all_markets():
    """获取所有市场数据"""
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
                d.status,
                d.impulse_tag,
                d.ui,
                d.cer,
                d.cs,
                d.band_width,
                d.va_high,
                d.va_low,
                d.pomd
            FROM markets m
            LEFT JOIN daily_metrics d ON m.token_id = d.token_id 
                AND d.date = (SELECT MAX(date) FROM daily_metrics WHERE token_id = m.token_id)
            WHERE m.closed = false OR m.closed IS NULL
            ORDER BY m.volume_24h DESC
        """)
        result = session.execute(query).fetchall()
        
        markets = []
        for row in result:
            categories = []
            if row[4]:
                try:
                    categories = json.loads(row[4]) if isinstance(row[4], str) else row[4]
                except:
                    categories = []
            
            markets.append({
                'token_id': row[0],
                'market_id': row[1],
                'title': row[2],
                'category': row[3] or 'Other',
                'categories': categories,
                'volume_24h': float(row[5] or 0),
                'current_price': float(row[6] or 0),
                'status': row[7] or 'Unknown',
                'impulse_tag': row[8],
                'ui': row[9],
                'cer': row[10],
                'cs': row[11],
                'band_width': row[12],
                'va_high': row[13],
                'va_low': row[14],
                'pomd': row[15]
            })
        
        return markets
    finally:
        session.close()

@st.cache_data(ttl=300)
def get_categories():
    """获取所有分类"""
    session = get_session()
    try:
        query = text("""
            SELECT DISTINCT category, COUNT(*) as count
            FROM markets
            WHERE (closed = false OR closed IS NULL)
            AND category IS NOT NULL
            GROUP BY category
            ORDER BY count DESC
        """)
        result = session.execute(query).fetchall()
        return [{'name': row[0], 'count': row[1]} for row in result]
    finally:
        session.close()

def get_status_stats(markets):
    """计算状态统计"""
    stats = {'Informed': 0, 'Fragmented': 0, 'Noisy': 0}
    for m in markets:
        status = m.get('status', '')
        if status:
            # 处理带 emoji 的状态值（如 "🟡 Fragmented"）
            status_lower = status.lower()
            if 'informed' in status_lower:
                stats['Informed'] += 1
            elif 'fragmented' in status_lower:
                stats['Fragmented'] += 1
            elif 'noisy' in status_lower:
                stats['Noisy'] += 1
    return stats

def clean_status(status):
    """清理状态值，提取纯文本"""
    if not status:
        return 'Unknown'
    status_lower = status.lower()
    if 'informed' in status_lower:
        return 'Informed'
    elif 'fragmented' in status_lower:
        return 'Fragmented'
    elif 'noisy' in status_lower:
        return 'Noisy'
    return 'Unknown'

def format_volume(vol):
    """格式化交易量"""
    if vol >= 1_000_000:
        return f"${vol/1_000_000:.1f}M"
    elif vol >= 1_000:
        return f"${vol/1_000:.0f}K"
    else:
        return f"${vol:.0f}"

# === 颜色配置 ===
STATUS_COLORS = {
    'Informed': ('#d3f9d8', '#2b8a3e'),
    'Fragmented': ('#fff3bf', '#e67700'),
    'Noisy': ('#ffe3e3', '#c92a2a'),
    'Unknown': ('#e9ecef', '#868e96')
}

IMPULSE_COLORS = {
    '⚡ EMERGING': ('#e5dbff', '#7048e8'),
    '🔄 ABSORPTION': ('#fff4e6', '#e8590c'),
    '💨 EXHAUSTION': ('#ffe3e3', '#c92a2a')
}

# === 检查是否是详情页模式 ===
query_params = st.query_params
if 'market' in query_params:
    # ==================== 详情页模式 ====================
    token_id = query_params['market']
    
    markets = get_all_markets()
    market = next((m for m in markets if m['token_id'] == token_id), None)
    
    if market:
        import plotly.graph_objects as go
        
        # 返回按钮
        if st.button("← Back to Markets"):
            st.query_params.clear()
            st.rerun()
        
        # === 顶部：市场标题 + 状态 ===
        status = clean_status(market.get('status'))
        bg, color = STATUS_COLORS.get(status, STATUS_COLORS['Unknown'])
        
        st.markdown(f"### Market: **{market['title']}**")
        
        # 状态行
        status_html = f'''
<div style="display:flex;align-items:center;gap:12px;margin:8px 0 20px 0;">
<span style="font-size:15px;color:#495057;">Status:</span>
<span style="background:{bg};color:{color};padding:6px 16px;border-radius:20px;font-weight:600;font-size:14px;">{status}</span>
'''
        impulse = market.get('impulse_tag')
        if impulse:
            imp_bg, imp_color = IMPULSE_COLORS.get(impulse, ('#e9ecef', '#868e96'))
            status_html += f'<span style="background:{imp_bg};color:{imp_color};padding:6px 16px;border-radius:20px;font-weight:600;font-size:14px;">{impulse}</span>'
        
        status_html += f'<span style="color:#868e96;font-size:14px;margin-left:auto;">{market["category"]} · {format_volume(market["volume_24h"])} Vol</span></div>'
        st.markdown(status_html, unsafe_allow_html=True)
        
        # === Consensus Band Evolution 图表 ===
        st.markdown("#### Consensus Band Evolution")
        
        # 获取生命周期数据
        session = get_session()
        try:
            lifecycle_query = text("""
                SELECT phase_number, is_valid, va_high, va_low, band_width, poc, ui, cer, cs, status
                FROM lifecycle_phases
                WHERE token_id = :tid
                ORDER BY phase_number
            """)
            lifecycle_data = session.execute(lifecycle_query, {'tid': token_id}).fetchall()
        finally:
            session.close()
        
        # 创建 Evolution Band 图表
        fig = go.Figure()
        
        # 定义每个阶段的位置
        phase_positions = [10, 30, 50, 70]  # Phase 1-4 的 x 位置
        phase_width = 12  # 每个阶段的宽度
        
        # 添加阶段数据
        valid_phases = []
        for phase in lifecycle_data if lifecycle_data else []:
            phase_num = phase[0]
            is_valid = phase[1]
            if is_valid and phase_num <= 4:
                va_h = float(phase[2]) if phase[2] else None
                va_l = float(phase[3]) if phase[3] else None
                poc = float(phase[5]) if phase[5] else None
                if va_h is not None and va_l is not None:
                    valid_phases.append({
                        'num': phase_num,
                        'va_high': va_h,
                        'va_low': va_l,
                        'poc': poc,
                        'ui': phase[6],
                        'status': phase[9]
                    })
        
        # 如果没有生命周期数据，使用当前数据作为单个阶段
        if not valid_phases:
            va_h = market.get('va_high')
            va_l = market.get('va_low')
            if va_h is not None and va_l is not None:
                valid_phases = [{
                    'num': 1,
                    'va_high': float(va_h),
                    'va_low': float(va_l),
                    'poc': None,
                    'ui': market.get('ui'),
                    'status': status
                }]
        
        # 绘制每个阶段的 band
        for p in valid_phases:
            idx = p['num'] - 1
            if idx < len(phase_positions):
                x_center = phase_positions[idx]
                va_h = p['va_high'] * 100
                va_l = p['va_low'] * 100
                mid = (va_h + va_l) / 2
                
                # 绘制类似小提琴的形状（菱形/椭圆形）
                # 使用多边形近似椭圆
                shape_x = []
                shape_y = []
                
                # 从底部到顶部，宽度变化
                steps = 20
                for i in range(steps + 1):
                    t = i / steps
                    y = va_l + (va_h - va_l) * t
                    # 椭圆宽度：中间最宽，两端最窄
                    width_factor = 1 - (2 * t - 1) ** 2  # 在中点最大
                    width = phase_width * 0.5 * (0.3 + 0.7 * width_factor)
                    shape_x.append(x_center - width)
                    shape_y.append(y)
                
                for i in range(steps, -1, -1):
                    t = i / steps
                    y = va_l + (va_h - va_l) * t
                    width_factor = 1 - (2 * t - 1) ** 2
                    width = phase_width * 0.5 * (0.3 + 0.7 * width_factor)
                    shape_x.append(x_center + width)
                    shape_y.append(y)
                
                # 获取状态颜色
                p_status = clean_status(p.get('status'))
                _, p_color = STATUS_COLORS.get(p_status, STATUS_COLORS['Unknown'])
                
                fig.add_trace(go.Scatter(
                    x=shape_x,
                    y=shape_y,
                    fill='toself',
                    fillcolor=f'rgba(59, 130, 246, 0.3)',
                    line=dict(color='rgba(59, 130, 246, 0.8)', width=2),
                    name=f'Phase {p["num"]}',
                    hoverinfo='text',
                    hovertext=f'Phase {p["num"]}<br>Band: {va_l:.0f}% - {va_h:.0f}%<br>Width: {va_h-va_l:.1f}%'
                ))
                
                # 添加 POC 线（深色中心线）
                if p.get('poc'):
                    poc_y = p['poc'] * 100
                    fig.add_shape(
                        type="line",
                        x0=x_center - phase_width * 0.4,
                        x1=x_center + phase_width * 0.4,
                        y0=poc_y, y1=poc_y,
                        line=dict(color='rgba(30, 64, 175, 0.9)', width=3)
                    )
        
        # 添加当前价格线（如果存在）
        current_price = market.get('current_price')
        if current_price and valid_phases:
            fig.add_hline(
                y=current_price * 100,
                line_dash="dash",
                line_color="#22c55e",
                line_width=2,
                annotation_text=f"Current: {current_price*100:.0f}%",
                annotation_position="right"
            )
        
        # 添加 Resolution 区域（如果价格接近确定性）
        if current_price and current_price > 0.9:
            fig.add_shape(
                type="rect",
                x0=85, x1=100,
                y0=90, y1=100,
                fillcolor="rgba(34, 197, 94, 0.4)",
                line=dict(color="rgba(34, 197, 94, 0.8)", width=2),
            )
            fig.add_annotation(x=92.5, y=95, text="Resolution", showarrow=False, font=dict(size=11))
        elif current_price and current_price < 0.1:
            fig.add_shape(
                type="rect",
                x0=85, x1=100,
                y0=0, y1=10,
                fillcolor="rgba(239, 68, 68, 0.4)",
                line=dict(color="rgba(239, 68, 68, 0.8)", width=2),
            )
            fig.add_annotation(x=92.5, y=5, text="Resolution", showarrow=False, font=dict(size=11))
        
        # 添加阶段标签
        for i, pos in enumerate(phase_positions):
            fig.add_annotation(
                x=pos, y=-8,
                text=f"Phase {i+1}",
                showarrow=False,
                font=dict(size=12, color='#495057')
            )
        
        # 布局
        fig.update_layout(
            xaxis=dict(
                range=[0, 100],
                showticklabels=False,
                showgrid=False,
                zeroline=False
            ),
            yaxis=dict(
                title="Probability %",
                range=[-15, 105],
                ticksuffix="%",
                gridcolor='rgba(0,0,0,0.1)'
            ),
            height=350,
            showlegend=False,
            margin=dict(l=50, r=50, t=20, b=50),
            plot_bgcolor='#f8fafc'
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
        # === Key Metrics ===
        st.markdown("#### Key Metrics")
        
        col1, col2, col3 = st.columns(3)
        
        ui = market.get('ui')
        cer = market.get('cer')
        cs = market.get('cs')
        
        # UI 指标解读
        if ui is not None:
            if ui < 0.30:
                ui_label = "Low Uncertainty"
                ui_icon = "✅"
                ui_desc = "低不确定性"
            elif ui < 0.50:
                ui_label = "Moderate"
                ui_icon = "➖"
                ui_desc = "中等不确定性"
            else:
                ui_label = "High Uncertainty"
                ui_icon = "⚠️"
                ui_desc = "高不确定性"
        else:
            ui_label = "—"
            ui_icon = "—"
            ui_desc = ""
        
        # CER 指标解读
        if cer is not None:
            if cer >= 0.80:
                cer_label = "Fast Convergence"
                cer_icon = "✅"
                cer_desc = "快速收敛"
            elif cer >= 0.40:
                cer_label = "Normal"
                cer_icon = "➖"
                cer_desc = "正常收敛"
            else:
                cer_label = "Slow/Diverging"
                cer_icon = "⚠️"
                cer_desc = "缓慢/发散"
        else:
            cer_label = "—"
            cer_icon = "—"
            cer_desc = ""
        
        # CS 指标解读
        if cs is not None:
            if cs >= 0.50:
                cs_label = "Strong Conviction"
                cs_icon = "✅"
                cs_desc = "强信念"
            elif cs >= 0.25:
                cs_label = "Moderate"
                cs_icon = "➖"
                cs_desc = "中等信念"
            else:
                cs_label = "Weak"
                cs_icon = "⚠️"
                cs_desc = "弱信念"
        else:
            cs_label = "—"
            cs_icon = "—"
            cs_desc = ""
        
        with col1:
            with st.container(border=True):
                st.markdown(f'''
<div style="padding:8px;">
<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
<span style="color:#3b82f6;font-weight:700;font-size:16px;">UI</span>
<span style="color:#495057;">Uncertainty Index:</span>
<span style="font-weight:700;font-size:18px;">{f"{ui:.2f}" if ui is not None else "—"}</span>
<span style="color:#868e96;font-size:13px;">{ui_desc}</span>
</div>
<div style="display:flex;align-items:center;gap:6px;">
<span>{ui_icon}</span>
<span style="color:#6b7280;font-size:13px;">{ui_label}</span>
</div>
</div>
''', unsafe_allow_html=True)
        
        with col2:
            with st.container(border=True):
                st.markdown(f'''
<div style="padding:8px;">
<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
<span style="color:#8b5cf6;font-weight:700;font-size:16px;">CER</span>
<span style="color:#495057;">Convergence Rate:</span>
<span style="font-weight:700;font-size:18px;">{f"{cer:.2f}" if cer is not None else "—"}</span>
<span style="color:#868e96;font-size:13px;">{cer_desc}</span>
</div>
<div style="display:flex;align-items:center;gap:6px;">
<span>{cer_icon}</span>
<span style="color:#6b7280;font-size:13px;">{cer_label}</span>
</div>
</div>
''', unsafe_allow_html=True)
        
        with col3:
            with st.container(border=True):
                st.markdown(f'''
<div style="padding:8px;">
<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
<span style="color:#f59e0b;font-weight:700;font-size:16px;">CS</span>
<span style="color:#495057;">Conviction Score:</span>
<span style="font-weight:700;font-size:18px;">{f"{cs:.2f}" if cs is not None else "—"}</span>
<span style="color:#868e96;font-size:13px;">{cs_desc}</span>
</div>
<div style="display:flex;align-items:center;gap:6px;">
<span>{cs_icon}</span>
<span style="color:#6b7280;font-size:13px;">{cs_label}</span>
</div>
</div>
''', unsafe_allow_html=True)
        
        # === 附加信息 ===
        st.markdown("")
        with st.expander("📊 Additional Details", expanded=False):
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("**Band Information**")
                va_high = market.get('va_high')
                va_low = market.get('va_low')
                bw = market.get('band_width')
                pomd = market.get('pomd')
                
                st.write(f"• VAH (Value Area High): {f'{va_high*100:.1f}%' if va_high else '—'}")
                st.write(f"• VAL (Value Area Low): {f'{va_low*100:.1f}%' if va_low else '—'}")
                st.write(f"• Band Width: {f'{bw*100:.1f}%' if bw else '—'}")
                st.write(f"• POMD: {f'{pomd*100:.1f}%' if pomd else '—'}")
            
            with col2:
                st.markdown("**Market Info**")
                st.write(f"• Current Price: {market['current_price']*100:.1f}%")
                st.write(f"• 24h Volume: {format_volume(market['volume_24h'])}")
                st.write(f"• Category: {market['category']}")
                st.write(f"• Token ID: `{token_id[:20]}...`")
        
    else:
        st.error("Market not found")
        if st.button("← Back to Markets"):
            st.query_params.clear()
            st.rerun()

else:
    # ==================== 主页模式 ====================
    
    # 顶部 Logo
    st.markdown("### 📊 Market Sensemaking")
    
    # 加载数据
    markets = get_all_markets()
    categories = get_categories()
    stats = get_status_stats(markets)
    
    # === 统计卡片 ===
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        with st.container(border=True):
            st.markdown(f"<div style='text-align:center;'><span style='font-size:28px;font-weight:700;color:#2b8a3e;'>{stats['Informed']}</span><br><span style='font-size:13px;color:#868e96;'>🟢 Informed</span></div>", unsafe_allow_html=True)
    
    with col2:
        with st.container(border=True):
            st.markdown(f"<div style='text-align:center;'><span style='font-size:28px;font-weight:700;color:#e67700;'>{stats['Fragmented']}</span><br><span style='font-size:13px;color:#868e96;'>🟡 Fragmented</span></div>", unsafe_allow_html=True)
    
    with col3:
        with st.container(border=True):
            st.markdown(f"<div style='text-align:center;'><span style='font-size:28px;font-weight:700;color:#c92a2a;'>{stats['Noisy']}</span><br><span style='font-size:13px;color:#868e96;'>🔴 Noisy</span></div>", unsafe_allow_html=True)
    
    with col4:
        with st.container(border=True):
            st.markdown(f"<div style='text-align:center;'><span style='font-size:28px;font-weight:700;color:#1a1a2e;'>{len(markets)}</span><br><span style='font-size:13px;color:#868e96;'>Total Markets</span></div>", unsafe_allow_html=True)
    
    st.markdown("")
    
    # === 分类标签 ===
    if 'selected_category' not in st.session_state:
        st.session_state.selected_category = 'All'
    if 'show_filters' not in st.session_state:
        st.session_state.show_filters = False
    
    category_names = ['All'] + [c['name'] for c in categories[:10]]
    
    # 分类按钮行
    cat_cols = st.columns(len(category_names) + 1)
    
    for i, cat in enumerate(category_names):
        with cat_cols[i]:
            is_active = st.session_state.selected_category == cat
            if st.button(cat, key=f"cat_{cat}", type="primary" if is_active else "secondary", use_container_width=True):
                st.session_state.selected_category = cat
                st.session_state.current_page = 1
                st.rerun()
    
    with cat_cols[-1]:
        if st.button("⚙️", key="filter_toggle", help="Filters"):
            st.session_state.show_filters = not st.session_state.show_filters
            st.rerun()
    
    # === 筛选面板 ===
    if st.session_state.show_filters:
        col1, col2, col3 = st.columns(3)
        with col1:
            search_query = st.text_input("🔍 Search", placeholder="Search markets...", key="search", label_visibility="collapsed")
        with col2:
            sort_option = st.selectbox("Sort by", ["Volume (High to Low)", "Volume (Low to High)", "Price (High to Low)", "Price (Low to High)"], key="sort", label_visibility="collapsed")
        with col3:
            status_filter = st.selectbox("Status", ["All", "Informed", "Fragmented", "Noisy"], key="status_filter", label_visibility="collapsed")
    else:
        search_query = ""
        sort_option = "Volume (High to Low)"
        status_filter = "All"
    
    # === 筛选逻辑 ===
    filtered_markets = markets.copy()
    
    if st.session_state.selected_category != 'All':
        filtered_markets = [m for m in filtered_markets if m['category'] == st.session_state.selected_category]
    
    if search_query:
        search_lower = search_query.lower()
        filtered_markets = [m for m in filtered_markets if search_lower in m['title'].lower()]
    
    if status_filter != "All":
        filtered_markets = [m for m in filtered_markets if clean_status(m.get('status')) == status_filter]
    
    # 排序
    if sort_option == "Volume (High to Low)":
        filtered_markets.sort(key=lambda x: x['volume_24h'], reverse=True)
    elif sort_option == "Volume (Low to High)":
        filtered_markets.sort(key=lambda x: x['volume_24h'])
    elif sort_option == "Price (High to Low)":
        filtered_markets.sort(key=lambda x: x['current_price'], reverse=True)
    elif sort_option == "Price (Low to High)":
        filtered_markets.sort(key=lambda x: x['current_price'])
    
    # 显示数量 + 调试信息
    st.markdown(f"**Showing {len(filtered_markets)} markets**")
    
    # 调试：显示实际状态分布
    status_dist = {}
    impulse_dist = {}
    for m in markets:
        s = m.get('status') or 'NULL'
        imp = m.get('impulse_tag') or 'None'
        status_dist[s] = status_dist.get(s, 0) + 1
        if imp != 'None':
            impulse_dist[imp] = impulse_dist.get(imp, 0) + 1
    
    with st.expander("🔍 Debug: Data Distribution", expanded=False):
        st.write("**Status values in database:**", status_dist)
        st.write("**Impulse tags in database:**", impulse_dist if impulse_dist else "No impulse tags found")
    
    # === 分页 ===
    CARDS_PER_PAGE = 20
    total_pages = max(1, (len(filtered_markets) + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE)
    
    if 'current_page' not in st.session_state:
        st.session_state.current_page = 1
    
    start_idx = (st.session_state.current_page - 1) * CARDS_PER_PAGE
    end_idx = start_idx + CARDS_PER_PAGE
    page_markets = filtered_markets[start_idx:end_idx]
    
    # === 市场卡片 ===
    for row_start in range(0, len(page_markets), 4):
        row_markets = page_markets[row_start:row_start + 4]
        cols = st.columns(4)
        
        for i, market in enumerate(row_markets):
            with cols[i]:
                # 清理状态值
                status = clean_status(market.get('status'))
                bg, color = STATUS_COLORS.get(status, STATUS_COLORS['Unknown'])
                
                impulse = market.get('impulse_tag')
                title_short = market['title'][:50] + '...' if len(market['title']) > 50 else market['title']
                
                # 用 st.container 加边框
                with st.container(border=True):
                    # 标题 - 固定两行高度
                    st.markdown(f"<div style='height:48px;overflow:hidden;font-weight:600;font-size:14px;line-height:1.4;'>{title_short}</div>", unsafe_allow_html=True)
                    
                    # 状态标签行
                    tags = f'<span style="background:{bg};color:{color};padding:4px 10px;border-radius:12px;font-size:11px;font-weight:600;display:inline-block;margin-right:4px;">{status}</span>'
                    if impulse:
                        imp_bg, imp_color = IMPULSE_COLORS.get(impulse, ('#e9ecef', '#868e96'))
                        tags += f'<span style="background:{imp_bg};color:{imp_color};padding:4px 10px;border-radius:12px;font-size:11px;font-weight:600;display:inline-block;">{impulse}</span>'
                    st.markdown(f"<div style='margin:8px 0;'>{tags}</div>", unsafe_allow_html=True)
                    
                    # 价格和交易量
                    st.markdown(f"""
<div style='display:flex;justify-content:space-between;align-items:center;margin:8px 0;'>
<span style='font-size:22px;font-weight:700;'>{market['current_price']*100:.0f}%</span>
<span style='color:#868e96;font-size:13px;'>{format_volume(market['volume_24h'])}</span>
</div>
""", unsafe_allow_html=True)
                    
                    # 分类
                    st.markdown(f"<span style='background:#f1f3f5;color:#868e96;padding:3px 8px;border-radius:6px;font-size:11px;'>{market['category']}</span>", unsafe_allow_html=True)
                    
                    # View 按钮
                    if st.button("View →", key=f"view_{market['token_id']}", use_container_width=True):
                        st.query_params['market'] = market['token_id']
                        st.rerun()
    
    # === 分页控制 ===
    if total_pages > 1:
        st.markdown("")
        col1, col2, col3 = st.columns([1, 2, 1])
        
        with col1:
            if st.session_state.current_page > 1:
                if st.button("← Previous"):
                    st.session_state.current_page -= 1
                    st.rerun()
        
        with col2:
            st.markdown(f"<div style='text-align:center;color:#868e96;'>Page {st.session_state.current_page} of {total_pages}</div>", unsafe_allow_html=True)
        
        with col3:
            if st.session_state.current_page < total_pages:
                if st.button("Next →"):
                    st.session_state.current_page += 1
                    st.rerun()