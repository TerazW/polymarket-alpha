"""
Market Sensemaking - 主页面 v3.0
新增：Market Profile Evolution（4 Phase 并排显示）
"""

import streamlit as st
import json
from datetime import datetime, timedelta
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

/* 图例样式 */
.profile-legend {
    display: flex;
    gap: 20px;
    justify-content: center;
    margin: 10px 0;
    font-size: 13px;
}

.legend-item {
    display: flex;
    align-items: center;
    gap: 6px;
}

.legend-dot {
    width: 12px;
    height: 12px;
    border-radius: 2px;
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


@st.cache_data(ttl=120)
def get_phase_histograms(token_id: str):
    """
    从 phase_histogram 表获取所有 Phase 的 histogram 数据
    
    Returns:
        {phase_number: {price_bin: {'volume', 'buy', 'sell'}}}
    """
    session = get_session()
    try:
        result = session.execute(text("""
            SELECT phase_number, price_bin, volume, aggressive_buy, aggressive_sell
            FROM phase_histogram
            WHERE token_id = :token_id
            ORDER BY phase_number, price_bin
        """), {"token_id": token_id}).fetchall()
        
        if not result:
            return {}
        
        from collections import defaultdict
        histograms = defaultdict(dict)
        
        for row in result:
            phase_num = int(row[0])
            price_bin = float(row[1])
            histograms[phase_num][price_bin] = {
                'volume': float(row[2] or 0),
                'buy': float(row[3] or 0),
                'sell': float(row[4] or 0)
            }
        
        return dict(histograms)
        
    except Exception as e:
        # 表可能不存在
        return {}
    finally:
        session.close()


@st.cache_data(ttl=120)
def get_lifecycle_phases(token_id: str):
    """获取 lifecycle phases 元数据"""
    session = get_session()
    try:
        result = session.execute(text("""
            SELECT phase_number, phase_start, phase_end, is_valid, 
                   va_high, va_low, poc, ui, cer, cs, status
            FROM lifecycle_phases
            WHERE token_id = :tid
            ORDER BY phase_number
        """), {'tid': token_id}).fetchall()
        
        phases = []
        for row in result:
            phases.append({
                'phase_number': row[0],
                'phase_start': row[1],
                'phase_end': row[2],
                'is_valid': row[3],
                'va_high': float(row[4]) if row[4] else None,
                'va_low': float(row[5]) if row[5] else None,
                'poc': float(row[6]) if row[6] else None,
                'ui': row[7],
                'cer': row[8],
                'cs': row[9],
                'status': row[10]
            })
        return phases
    except:
        return []
    finally:
        session.close()


def get_status_stats(markets):
    """计算状态统计"""
    stats = {'Informed': 0, 'Fragmented': 0, 'Noisy': 0}
    for m in markets:
        status = m.get('status', '')
        if status:
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
        from plotly.subplots import make_subplots
        
        # 返回按钮
        if st.button("← Back to Markets"):
            st.query_params.clear()
            st.rerun()
        
        # === 顶部：市场标题 + 状态 ===
        status = clean_status(market.get('status'))
        bg, color = STATUS_COLORS.get(status, STATUS_COLORS['Unknown'])
        
        st.markdown(f"### {market['title']}")
        
        # 状态行
        status_html = f'''
<div style="display:flex;align-items:center;gap:12px;margin:8px 0 20px 0;">
<span style="background:{bg};color:{color};padding:6px 16px;border-radius:20px;font-weight:600;font-size:14px;">{status}</span>
'''
        impulse = market.get('impulse_tag')
        if impulse:
            imp_bg, imp_color = IMPULSE_COLORS.get(impulse, ('#e9ecef', '#868e96'))
            status_html += f'<span style="background:{imp_bg};color:{imp_color};padding:6px 16px;border-radius:20px;font-weight:600;font-size:14px;">{impulse}</span>'
        
        status_html += f'''
<span style="font-size:24px;font-weight:700;margin-left:auto;">{market["current_price"]*100:.0f}%</span>
<span style="color:#868e96;font-size:14px;">{market["category"]} · {format_volume(market["volume_24h"])}</span>
</div>'''
        st.markdown(status_html, unsafe_allow_html=True)
        
        # ==================== Market Profile Evolution ====================
        st.markdown("#### Market Profile Evolution")
        
        # 图例（包含所有标识）
        st.markdown("""
<div style="display:flex;gap:20px;justify-content:center;align-items:center;margin:12px 0;font-size:13px;flex-wrap:wrap;">
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
        <span style="color:#8b5cf6;font-size:16px;">★</span>
        <span>POMD</span>
    </div>
    <div style="display:flex;align-items:center;gap:6px;">
        <div style="width:14px;height:2px;border-top:2px dashed #22c55e;"></div>
        <span>Current</span>
    </div>
    <div style="display:flex;align-items:center;gap:6px;">
        <div style="width:14px;height:2px;border-top:2px dotted rgba(59,130,246,0.6);"></div>
        <span>VAH/VAL</span>
    </div>
    <div style="display:flex;align-items:center;gap:6px;">
        <div style="width:14px;height:14px;background:rgba(239,68,68,0.4);border-radius:2px;"></div>
        <span>Tail</span>
    </div>
</div>
""", unsafe_allow_html=True)
        
        # 获取 Phase Histogram 数据
        phase_histograms = get_phase_histograms(token_id)
        lifecycle_phases = get_lifecycle_phases(token_id)
        
        current_price = market.get('current_price')
        
        if phase_histograms:
            # 构建 phase_metadata（从 lifecycle_phases 读取 POC/POMD/VAH/VAL）
            phase_metadata = {}
            current_phase = 4  # 默认最后一个
            now = datetime.now()
            
            for lp in lifecycle_phases:
                phase_num = lp.get('phase_number')
                if phase_num:
                    phase_metadata[phase_num] = {
                        'poc': lp.get('poc'),
                        'pomd': lp.get('pomd'),
                        'vah': lp.get('va_high'),
                        'val': lp.get('va_low'),
                        'status': lp.get('status'),
                        'is_valid': lp.get('is_valid')
                    }
                    
                    # 判断当前 phase
                    if lp.get('phase_start') and lp.get('phase_end'):
                        try:
                            start = lp['phase_start']
                            end = lp['phase_end']
                            if isinstance(start, str):
                                start = datetime.fromisoformat(start.replace('Z', '+00:00')).replace(tzinfo=None)
                            if isinstance(end, str):
                                end = datetime.fromisoformat(end.replace('Z', '+00:00')).replace(tzinfo=None)
                            if start <= now < end:
                                current_phase = phase_num
                        except:
                            pass
            
            # 尝试导入可视化组件
            try:
                from app.components.market_profile_evolution import create_market_profile_evolution
                
                fig = create_market_profile_evolution(
                    phase_histograms=phase_histograms,
                    phase_metadata=phase_metadata,
                    current_price=current_price,
                    current_phase=current_phase,
                    title=""
                )
                
                st.plotly_chart(fig, use_container_width=True)
                
            except ImportError:
                # Fallback: 手动绘制
                st.warning("Market Profile Evolution component not available. Using fallback view.")
                _render_fallback_profile_evolution(phase_histograms, current_price)
        else:
            # 没有 phase_histogram 数据，显示提示
            st.info("📊 No phase histogram data available. Run `lifecycle_sync.py` with `--save-histogram` to collect data.")
            
            # 显示旧的 Consensus Band Evolution 作为备选
            if lifecycle_phases:
                _render_legacy_band_evolution(lifecycle_phases, current_price, market)
        
        st.markdown("")
        
        # === Key Metrics ===
        st.markdown("#### Key Metrics")
        
        col1, col2, col3 = st.columns(3)
        
        ui = market.get('ui')
        cer = market.get('cer')
        cs = market.get('cs')
        
        # UI 指标解读
        if ui is not None:
            if ui < 0.30:
                ui_label, ui_icon, ui_desc = "Low Uncertainty", "✅", "低不确定性"
            elif ui < 0.50:
                ui_label, ui_icon, ui_desc = "Moderate", "➖", "中等不确定性"
            else:
                ui_label, ui_icon, ui_desc = "High Uncertainty", "⚠️", "高不确定性"
        else:
            ui_label, ui_icon, ui_desc = "—", "—", ""
        
        # CER 指标解读
        if cer is not None:
            if cer >= 0.80:
                cer_label, cer_icon, cer_desc = "Fast Convergence", "✅", "快速收敛"
            elif cer >= 0.40:
                cer_label, cer_icon, cer_desc = "Normal", "➖", "正常收敛"
            else:
                cer_label, cer_icon, cer_desc = "Slow/Diverging", "⚠️", "缓慢/发散"
        else:
            cer_label, cer_icon, cer_desc = "—", "—", ""
        
        # CS 指标解读
        if cs is not None:
            if cs >= 0.50:
                cs_label, cs_icon, cs_desc = "Strong Conviction", "✅", "强信念"
            elif cs >= 0.25:
                cs_label, cs_icon, cs_desc = "Moderate", "➖", "中等信念"
            else:
                cs_label, cs_icon, cs_desc = "Weak", "⚠️", "弱信念"
        else:
            cs_label, cs_icon, cs_desc = "—", "—", ""
        
        with col1:
            with st.container(border=True):
                st.markdown(f'''
<div style="padding:8px;">
<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
<span style="color:#3b82f6;font-weight:700;font-size:16px;">UI</span>
<span style="color:#495057;">Uncertainty Index:</span>
<span style="font-weight:700;font-size:18px;">{f"{ui:.2f}" if ui is not None else "—"}</span>
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
    
    # 显示数量
    st.markdown(f"**Showing {len(filtered_markets)} markets**")
    
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
                status = clean_status(market.get('status'))
                bg, color = STATUS_COLORS.get(status, STATUS_COLORS['Unknown'])
                
                impulse = market.get('impulse_tag')
                title_short = market['title'][:50] + '...' if len(market['title']) > 50 else market['title']
                
                with st.container(border=True):
                    st.markdown(f"<div style='height:48px;overflow:hidden;font-weight:600;font-size:14px;line-height:1.4;'>{title_short}</div>", unsafe_allow_html=True)
                    
                    tags = f'<span style="background:{bg};color:{color};padding:4px 10px;border-radius:12px;font-size:11px;font-weight:600;display:inline-block;margin-right:4px;">{status}</span>'
                    if impulse:
                        imp_bg, imp_color = IMPULSE_COLORS.get(impulse, ('#e9ecef', '#868e96'))
                        tags += f'<span style="background:{imp_bg};color:{imp_color};padding:4px 10px;border-radius:12px;font-size:11px;font-weight:600;display:inline-block;">{impulse}</span>'
                    st.markdown(f"<div style='margin:8px 0;'>{tags}</div>", unsafe_allow_html=True)
                    
                    st.markdown(f"""
<div style='display:flex;justify-content:space-between;align-items:center;margin:8px 0;'>
<span style='font-size:22px;font-weight:700;'>{market['current_price']*100:.0f}%</span>
<span style='color:#868e96;font-size:13px;'>{format_volume(market['volume_24h'])}</span>
</div>
""", unsafe_allow_html=True)
                    
                    st.markdown(f"<span style='background:#f1f3f5;color:#868e96;padding:3px 8px;border-radius:6px;font-size:11px;'>{market['category']}</span>", unsafe_allow_html=True)
                    
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


# ==================== Helper Functions ====================

def _render_fallback_profile_evolution(phase_histograms, current_price):
    """Fallback: 使用基础 Plotly 绘制 4 个 Phase"""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    
    fig = make_subplots(
        rows=1, cols=4,
        subplot_titles=['Phase 1', 'Phase 2', 'Phase 3', 'Phase 4'],
        shared_yaxes=True,
        horizontal_spacing=0.02
    )
    
    all_prices = []
    for histogram in phase_histograms.values():
        if histogram:
            all_prices.extend(histogram.keys())
    if current_price:
        all_prices.append(current_price)
    
    if all_prices:
        y_min, y_max = min(all_prices) - 0.02, max(all_prices) + 0.02
    else:
        y_min, y_max = 0, 1
    
    for phase_num in range(1, 5):
        histogram = phase_histograms.get(phase_num, {})
        
        if not histogram:
            fig.add_annotation(
                text="No Data",
                xref=f"x{phase_num}" if phase_num > 1 else "x",
                yref="y",
                x=0.5, y=(y_min + y_max) / 2,
                showarrow=False,
                font=dict(size=14, color='#9ca3af')
            )
            continue
        
        sorted_prices = sorted(histogram.keys())
        buy_vols = [histogram[p].get('buy', 0) for p in sorted_prices]
        sell_vols = [histogram[p].get('sell', 0) for p in sorted_prices]
        total_vols = [histogram[p].get('volume', 0) or (histogram[p].get('buy', 0) + histogram[p].get('sell', 0)) for p in sorted_prices]
        
        # POC
        poc_idx = total_vols.index(max(total_vols)) if total_vols else 0
        poc_price = sorted_prices[poc_idx] if sorted_prices else None
        
        # Buy bars (green)
        fig.add_trace(go.Bar(
            y=sorted_prices, x=buy_vols, orientation='h',
            marker_color='rgba(34, 197, 94, 0.8)',
            showlegend=False
        ), row=1, col=phase_num)
        
        # Sell bars (red)
        fig.add_trace(go.Bar(
            y=sorted_prices, x=sell_vols, orientation='h',
            marker_color='rgba(239, 68, 68, 0.8)',
            showlegend=False
        ), row=1, col=phase_num)
        
        # POC bar (blue)
        if poc_price:
            fig.add_trace(go.Bar(
                y=[poc_price], x=[max(total_vols)], orientation='h',
                marker_color='rgba(59, 130, 246, 1.0)',
                showlegend=False
            ), row=1, col=phase_num)
    
    # Current price line
    if current_price:
        for col in range(1, 5):
            fig.add_hline(y=current_price, line_dash="dash", line_color="#22c55e", line_width=2, row=1, col=col)
    
    fig.update_layout(
        height=450, barmode='overlay', showlegend=False,
        margin=dict(l=60, r=40, t=60, b=40),
        plot_bgcolor='#fafafa'
    )
    
    fig.update_yaxes(range=[y_min, y_max], tickformat='.0%', row=1, col=1)
    for col in range(2, 5):
        fig.update_yaxes(range=[y_min, y_max], showticklabels=False, row=1, col=col)
    
    for col in range(1, 5):
        fig.update_xaxes(showticklabels=False, showgrid=False, row=1, col=col)
    
    st.plotly_chart(fig, use_container_width=True)


def _render_legacy_band_evolution(lifecycle_phases, current_price, market):
    """Legacy: 旧的 Consensus Band Evolution 椭圆图"""
    import plotly.graph_objects as go
    
    fig = go.Figure()
    phase_positions = [10, 30, 50, 70]
    phase_width = 12
    
    valid_phases = []
    for phase in lifecycle_phases:
        if phase.get('is_valid') and phase['phase_number'] <= 4:
            va_h = phase.get('va_high')
            va_l = phase.get('va_low')
            if va_h is not None and va_l is not None:
                valid_phases.append({
                    'num': phase['phase_number'],
                    'va_high': va_h,
                    'va_low': va_l,
                    'poc': phase.get('poc'),
                    'status': phase.get('status')
                })
    
    if not valid_phases:
        va_h = market.get('va_high')
        va_l = market.get('va_low')
        if va_h is not None and va_l is not None:
            valid_phases = [{'num': 1, 'va_high': float(va_h), 'va_low': float(va_l), 'poc': None, 'status': market.get('status')}]
    
    for p in valid_phases:
        idx = p['num'] - 1
        if idx < len(phase_positions):
            x_center = phase_positions[idx]
            va_h = p['va_high'] * 100
            va_l = p['va_low'] * 100
            
            shape_x, shape_y = [], []
            steps = 20
            for i in range(steps + 1):
                t = i / steps
                y = va_l + (va_h - va_l) * t
                width_factor = 1 - (2 * t - 1) ** 2
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
            
            fig.add_trace(go.Scatter(
                x=shape_x, y=shape_y, fill='toself',
                fillcolor='rgba(59, 130, 246, 0.3)',
                line=dict(color='rgba(59, 130, 246, 0.8)', width=2),
                name=f'Phase {p["num"]}',
                hoverinfo='text',
                hovertext=f'Phase {p["num"]}<br>Band: {va_l:.0f}% - {va_h:.0f}%'
            ))
            
            if p.get('poc'):
                poc_y = p['poc'] * 100
                fig.add_shape(
                    type="line",
                    x0=x_center - phase_width * 0.4, x1=x_center + phase_width * 0.4,
                    y0=poc_y, y1=poc_y,
                    line=dict(color='rgba(30, 64, 175, 0.9)', width=3)
                )
    
    if current_price and valid_phases:
        fig.add_hline(y=current_price * 100, line_dash="dash", line_color="#22c55e", line_width=2,
                      annotation_text=f"Current: {current_price*100:.0f}%", annotation_position="right")
    
    for i, pos in enumerate(phase_positions):
        fig.add_annotation(x=pos, y=-8, text=f"Phase {i+1}", showarrow=False, font=dict(size=12, color='#495057'))
    
    fig.update_layout(
        xaxis=dict(range=[0, 100], showticklabels=False, showgrid=False, zeroline=False),
        yaxis=dict(title="Probability %", range=[-15, 105], ticksuffix="%", gridcolor='rgba(0,0,0,0.1)'),
        height=350, showlegend=False, margin=dict(l=50, r=50, t=20, b=50), plot_bgcolor='#f8fafc'
    )
    
    st.plotly_chart(fig, use_container_width=True)