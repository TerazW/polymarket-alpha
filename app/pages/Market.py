import streamlit as st
import pandas as pd
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
    page_title="Markets by Category",
    page_icon="🗂️",
    layout="wide"
)

# 标题
st.title("🗂️ Markets by Category")
st.markdown("**Browse markets organized by category** - Click any market to view details")

# === 辅助函数 ===

@st.cache_data(ttl=600)
def get_all_categories():
    """获取所有可用的分类"""
    session = get_session()
    try:
        query = text("""
            SELECT DISTINCT category
            FROM markets
            WHERE category IS NOT NULL AND category != ''
            ORDER BY category
        """)
        result = session.execute(query)
        categories = [row[0] for row in result.fetchall()]
        return categories
    finally:
        session.close()

@st.cache_data(ttl=600)
def load_markets_by_category(category=None):
    """加载市场数据，可选按分类筛选"""
    session = get_session()
    try:
        if category and category != "ALL":
            query = text("""
                SELECT 
                    dm.token_id,
                    m.market_id,
                    m.title as market_name,
                    m.category,
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
                    dm.current_price,
                    m.volume_24h,
                    dm.date,
                    dm.days_to_expiry
                FROM daily_metrics dm
                JOIN markets m ON dm.token_id = m.token_id
                WHERE dm.date = (SELECT MAX(date) FROM daily_metrics)
                  AND m.category = :category
                ORDER BY m.volume_24h DESC
            """)
            result = session.execute(query, {'category': category})
        else:
            query = text("""
                SELECT 
                    dm.token_id,
                    m.market_id,
                    m.title as market_name,
                    m.category,
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
                    dm.current_price,
                    m.volume_24h,
                    dm.date,
                    dm.days_to_expiry
                FROM daily_metrics dm
                JOIN markets m ON dm.token_id = m.token_id
                WHERE dm.date = (SELECT MAX(date) FROM daily_metrics)
                ORDER BY m.volume_24h DESC
            """)
            result = session.execute(query)
        
        df = pd.DataFrame(result.fetchall(), columns=result.keys())
        return df
    finally:
        session.close()

# === 主界面 ===

try:
    # 获取所有分类
    categories = get_all_categories()
    
    if not categories:
        st.warning("⚠️ No categories found. Make sure you've run the sync with category support.")
        st.info("Run: `python jobs/sync.py --migrate --markets 100`")
        st.stop()
    
    # === 侧边栏：分类选择 ===
    st.sidebar.header("📂 Filter by Category")
    
    # 添加 ALL 选项
    category_options = ["ALL"] + categories
    selected_category = st.sidebar.selectbox(
        "Select a category",
        options=category_options,
        index=0
    )
    
    # 显示分类统计
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Category Distribution:**")
    
    session = get_session()
    try:
        stats_query = text("""
            SELECT category, COUNT(*) as count
            FROM markets
            WHERE category IS NOT NULL AND category != ''
            GROUP BY category
            ORDER BY count DESC
        """)
        stats_result = session.execute(stats_query)
        for cat, count in stats_result.fetchall():
            emoji = "📁" if cat != selected_category else "📂"
            st.sidebar.write(f"{emoji} {cat}: {count}")
    finally:
        session.close()
    
    # === 主区域：加载数据 ===
    df = load_markets_by_category(selected_category)
    
    if df.empty:
        st.warning(f"⚠️ No markets found in category: {selected_category}")
        st.stop()
    
    # === 顶部统计 ===
    col1, col2, col3, col4 = st.columns(4)
    
    informed_count = len(df[df['status'].str.contains('Informed', na=False)])
    fragmented_count = len(df[df['status'].str.contains('Fragmented', na=False)])
    noisy_count = len(df[df['status'].str.contains('Noisy', na=False)])
    
    col1.metric("🟢 Informed", informed_count)
    col2.metric("🟡 Fragmented", fragmented_count)
    col3.metric("🔴 Noisy", noisy_count)
    col4.metric("Total Markets", len(df))
    
    st.markdown("---")
    
    # === 筛选和排序 ===
    col_filter1, col_filter2, col_filter3 = st.columns([2, 2, 3])
    
    with col_filter1:
        status_filter = st.multiselect(
            "Filter by Status",
            options=["🟢 Informed", "🟡 Fragmented", "🔴 Noisy"],
            default=[]
        )
    
    with col_filter2:
        sort_options = [
            "Volume (High to Low)",
            "Volume (Low to High)",
            "Price (High to Low)",
            "Price (Low to High)",
            "UI (High to Low)",
            "UI (Low to High)",
            "CER (High to Low)",
            "CER (Low to High)",
            "Band Width (High to Low)",
            "Band Width (Low to High)"
        ]
        sort_by = st.selectbox(
            "Sort by",
            options=sort_options,
            index=0
        )
    
    with col_filter3:
        search_term = st.text_input("🔍 Search markets", placeholder="Type to filter by keyword...")
    
    # === 应用筛选 ===
    df_filtered = df.copy()
    
    # 状态筛选
    if status_filter:
        filter_keywords = [s.split(' ')[1] for s in status_filter]
        mask = df_filtered['status'].str.contains('|'.join(filter_keywords), na=False)
        df_filtered = df_filtered[mask]
    
    # 搜索筛选
    if search_term:
        mask = df_filtered['market_name'].str.contains(search_term, case=False, na=False)
        df_filtered = df_filtered[mask]
    
    # === 排序 ===
    if "Volume" in sort_by:
        ascending = "Low to High" in sort_by
        df_filtered = df_filtered.sort_values('volume_24h', ascending=ascending)
    elif "Price" in sort_by:
        ascending = "Low to High" in sort_by
        df_filtered = df_filtered.sort_values('current_price', ascending=ascending)
    elif "UI" in sort_by:
        ascending = "Low to High" in sort_by
        df_filtered = df_filtered.sort_values('ui', ascending=ascending, na_position='last')
    elif "CER" in sort_by:
        ascending = "Low to High" in sort_by
        df_filtered = df_filtered.sort_values('cer', ascending=ascending, na_position='last')
    elif "Band Width" in sort_by:
        ascending = "Low to High" in sort_by
        df_filtered = df_filtered.sort_values('band_width', ascending=ascending, na_position='last')
    
    # === 显示结果数量 ===
    category_text = f"in {selected_category}" if selected_category != "ALL" else "across all categories"
    st.markdown(f"**Showing {len(df_filtered)} of {len(df)} markets {category_text}**")
    
    # === 分页设置 ===
    items_per_page = 20
    total_pages = max(1, (len(df_filtered) - 1) // items_per_page + 1)
    
    if 'market_page' not in st.session_state:
        st.session_state.market_page = 1
    
    # 分页控制
    col_page1, col_page2, col_page3 = st.columns([1, 2, 1])
    
    with col_page1:
        if st.button("⬅️ Previous", disabled=(st.session_state.market_page == 1), key="prev_btn"):
            st.session_state.market_page -= 1
            st.rerun()
    
    with col_page2:
        page_input = st.number_input(
            f"Page (1-{total_pages})", 
            min_value=1, 
            max_value=total_pages,
            value=st.session_state.market_page,
            key="market_page_selector"
        )
        if page_input != st.session_state.market_page:
            st.session_state.market_page = page_input
            st.rerun()
    
    with col_page3:
        if st.button("Next ➡️", disabled=(st.session_state.market_page == total_pages), key="next_btn"):
            st.session_state.market_page += 1
            st.rerun()
    
    # === 计算当前页数据 ===
    start_idx = (st.session_state.market_page - 1) * items_per_page
    end_idx = min(start_idx + items_per_page, len(df_filtered))
    df_page = df_filtered.iloc[start_idx:end_idx]
    
    # === 显示表格 ===
    st.dataframe(
        df_page[['market_name', 'category', 'status', 'ui', 'cs', 'cer', 'band_width', 'current_price', 'volume_24h']],
        use_container_width=True,
        column_config={
            "market_name": st.column_config.TextColumn(
                "Market",
                width="large"
            ),
            "category": st.column_config.TextColumn(
                "Category",
                width="small"
            ),
            "status": st.column_config.TextColumn(
                "Status",
                width="small"
            ),
            "ui": st.column_config.NumberColumn(
                "UI", 
                format="%.3f",
                help="Uncertainty Index"
            ),
            "cs": st.column_config.TextColumn(
                "CS",
                help="🔒 Locked (requires aggressor data)"
            ),
            "cer": st.column_config.NumberColumn(
                "CER", 
                format="%.3f",
                help="Convergence Efficiency Ratio"
            ),
            "band_width": st.column_config.NumberColumn(
                "BW", 
                format="%.3f",
                help="Band Width (VAH - VAL)"
            ),
            "current_price": st.column_config.NumberColumn(
                "Price", 
                format="%.1f%%",
                help="Current market price"
            ),
            "volume_24h": st.column_config.NumberColumn(
                "24h Volume",
                format="$%.0f",
                help="Trading volume in last 24 hours"
            )
        },
        hide_index=True
    )
    
    # === 市场详情选择 ===
    st.markdown("---")
    st.subheader("📊 View Market Details")
    
    # 创建市场选择下拉菜单
    market_options = df_filtered[['token_id', 'market_name']].drop_duplicates()
    market_dict = dict(zip(market_options['market_name'], market_options['token_id']))
    
    selected_market = st.selectbox(
        "Select a market to view details",
        options=["-- Select a market --"] + list(market_dict.keys()),
        index=0,
        key="market_detail_selector"
    )
    
    if selected_market != "-- Select a market --":
        # 保存选中的 token_id 到 session_state，然后跳转
        st.session_state.selected_token_id = market_dict[selected_market]
        st.switch_page("pages/Market_Detail.py")
    
    # === 扩展信息 ===
    with st.expander("ℹ️ About Categories"):
        st.markdown("""
        Markets are organized by their native Polymarket categories:
        
        - **Politics**: Elections, government policy, political events
        - **Sports**: Professional sports, tournaments, championships
        - **Crypto**: Cryptocurrency prices, DeFi events, blockchain
        - **Finance**: Financial markets, interest rates, economic indicators
        - **Business**: Company performance, corporate events
        - **Tech**: Technology releases, AI developments
        - **Science**: Scientific discoveries, space exploration
        - **Geopolitics**: International relations, conflicts
        """)
    
    with st.expander("📊 Metrics Guide"):
        st.markdown("""
        | Metric | Name | Description |
        |--------|------|-------------|
        | **UI** | Uncertainty Index | Band width relative to price - Lower = more certain |
        | **CER** | Convergence Efficiency | How efficiently market converges - Higher = healthier |
        | **BW** | Band Width | Width of 70% consensus band (VAH - VAL) |
        | **CS** | Conviction Score | 🔒 Locked (requires aggressor data) |
        
        **Status Classification:**
        - 🟢 **Informed**: UI < 0.30 AND CER ≥ 0.80
        - 🔴 **Noisy**: UI ≥ 0.50 OR CER < 0.40
        - 🟡 **Fragmented**: Everything else
        """)
    
    # === 下载数据 ===
    csv = df_filtered.to_csv(index=False)
    st.download_button(
        label=f"📥 Download {selected_category} markets as CSV",
        data=csv,
        file_name=f"polymarket_{selected_category.lower()}_markets.csv",
        mime="text/csv"
    )

except Exception as e:
    st.error(f"Error loading data: {e}")
    import traceback
    st.code(traceback.format_exc())
    st.info("Make sure you've run `python jobs/sync.py --migrate --markets 100` with category support.")