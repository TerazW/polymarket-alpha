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
    page_title="Market Sensemaking",
    page_icon="🌤️",
    layout="wide"
)

# 标题
st.title("🌤️ Market Sensemaking")
st.markdown("**Prediction Market Weather Report** - Know what's worth your attention")

# 获取数据
@st.cache_data(ttl=600)  # 缓存 10 分钟
def load_markets():
    session = get_session()
    try:
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

# 加载数据
try:
    df = load_markets()
    
    if df.empty:
        st.warning("⚠️ No data available. Run `python jobs/sync.py --markets 100` to fetch data.")
        st.stop()
    
    # 顶部统计
    col1, col2, col3, col4 = st.columns(4)
    
    informed_count = len(df[df['status'].str.contains('Informed', na=False)])
    fragmented_count = len(df[df['status'].str.contains('Fragmented', na=False)])
    noisy_count = len(df[df['status'].str.contains('Noisy', na=False)])
    
    col1.metric("🟢 Informed", informed_count)
    col2.metric("🟡 Fragmented", fragmented_count)
    col3.metric("🔴 Noisy", noisy_count)
    col4.metric("Total Markets", len(df))
    
    st.markdown("---")
    
    # 筛选和搜索
    col_filter1, col_filter2, col_filter3 = st.columns([2, 2, 3])
    
    with col_filter1:
        status_filter = st.multiselect(
            "Filter by Status",
            options=["🟢 Informed", "🟡 Fragmented", "🔴 Noisy"],
            default=[]
        )
    
    with col_filter2:
        sort_by = st.selectbox(
            "Sort by",
            options=["Volume (High to Low)", "Volume (Low to High)", 
                    "Price (High to Low)", "Price (Low to High)",
                    "UI (High to Low)", "UI (Low to High)",
                    "CER (High to Low)", "CER (Low to High)",
                    "Band Width (High to Low)", "Band Width (Low to High)"],
            index=0
        )
    
    with col_filter3:
        search_term = st.text_input("🔍 Search markets", placeholder="Type to filter by keyword...")
    
    # 应用筛选
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
    
    # 排序
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
    
    # 显示结果数量
    st.markdown(f"**Showing {len(df_filtered)} of {len(df)} markets**")
    
    # 分页设置
    items_per_page = 20
    total_pages = max(1, (len(df_filtered) - 1) // items_per_page + 1)
    
    if 'page' not in st.session_state:
        st.session_state.page = 1
    
    # 分页控制
    col_page1, col_page2, col_page3 = st.columns([1, 2, 1])
    
    with col_page1:
        if st.button("⬅️ Previous", disabled=(st.session_state.page == 1)):
            st.session_state.page -= 1
            st.rerun()
    
    with col_page2:
        page_input = st.number_input(
            f"Page (1-{total_pages})", 
            min_value=1, 
            max_value=total_pages,
            value=st.session_state.page,
            key="page_selector"
        )
        if page_input != st.session_state.page:
            st.session_state.page = page_input
            st.rerun()
    
    with col_page3:
        if st.button("Next ➡️", disabled=(st.session_state.page == total_pages)):
            st.session_state.page += 1
            st.rerun()
    
    # 计算当前页数据
    start_idx = (st.session_state.page - 1) * items_per_page
    end_idx = min(start_idx + items_per_page, len(df_filtered))
    df_page = df_filtered.iloc[start_idx:end_idx]
    
    # 显示表格
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
                help="Uncertainty Index - lower = more certain"
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
        index=0
    )
    
    if selected_market != "-- Select a market --":
        # 保存选中的 token_id 到 session_state，然后跳转
        st.session_state.selected_token_id = market_dict[selected_market]
        st.switch_page("pages/Market_Detail.py")
    
    # 状态说明
    with st.expander("ℹ️ What do these metrics mean?"):
        st.markdown("""
        ### Status Definitions
        
        **🟢 Informed:** Market has formed stable consensus.
        - Low UI (< 0.30): Narrow consensus band
        - High CER (≥ 0.80): Healthy convergence
        
        **🟡 Fragmented:** Market understanding is divided.
        - Moderate metrics that don't meet Informed criteria
        
        **🔴 Noisy:** Market lacks stable cognitive structure.
        - High UI (≥ 0.50): Wide disagreement
        - Low CER (< 0.40): Poor convergence
        
        ---
        
        ### Metrics Guide
        
        | Metric | Name | Description |
        |--------|------|-------------|
        | **UI** | Uncertainty Index | `band_width / mid_probability` - Lower = more certain |
        | **CER** | Convergence Efficiency | `ACR / ECR` - How efficiently the market is converging |
        | **BW** | Band Width | `VAH - VAL` - Width of 70% consensus band |
        | **CS** | Conviction Score | 🔒 Locked (requires aggressor data) |
        
        ---
        
        ### ECR / ACR / CER Explained
        
        - **ECR** (Expected Convergence Rate): `distance_to_certainty / days_remaining`
        - **ACR** (Actual Convergence Rate): `(band_width_7d_ago - band_width_now) / 7`
        - **CER** (Convergence Efficiency): `ACR / ECR`
          - CER > 1.0: Converging faster than expected ✅
          - CER ≈ 0.8-1.0: Normal convergence
          - CER < 0.5: Convergence blocked ⚠️
        """)
    
    # 数据统计
    with st.expander("📊 Data Statistics"):
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**Status Distribution:**")
            status_dist = df['status'].value_counts()
            for status, count in status_dist.items():
                st.write(f"{status}: {count}")
        
        with col2:
            st.markdown("**Volume Statistics:**")
            st.write(f"Total 24h Volume: ${df['volume_24h'].sum():,.0f}")
            st.write(f"Average Volume: ${df['volume_24h'].mean():,.0f}")
            st.write(f"Median Volume: ${df['volume_24h'].median():,.0f}")
    
    # 下载数据
    csv = df_filtered.to_csv(index=False)
    st.download_button(
        label="📥 Download filtered data as CSV",
        data=csv,
        file_name="polymarket_analysis.csv",
        mime="text/csv"
    )
    
except Exception as e:
    st.error(f"Error loading data: {e}")
    import traceback
    st.code(traceback.format_exc())
    st.info("Make sure you've run `python jobs/sync.py --migrate --markets 100` first.")