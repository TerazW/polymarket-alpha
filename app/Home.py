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
                m.title as market_name,
                dm.status,
                dm.ui,
                dm.cer,
                dm.cs,
                dm.current_price,
                m.volume_24h,
                dm.date
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
        st.warning("⚠️ No data available. Run `python jobs/sync.py` to fetch data.")
        st.stop()
    
    # 状态统计
    col1, col2, col3, col4 = st.columns(4)
    
    informed_count = len(df[df['status'].str.contains('Informed', na=False)])
    fragmented_count = len(df[df['status'].str.contains('Fragmented', na=False)])
    noisy_count = len(df[df['status'].str.contains('Noisy', na=False)])
    
    col1.metric("🟢 Informed", informed_count)
    col2.metric("🟡 Fragmented", fragmented_count)
    col3.metric("🔴 Noisy", noisy_count)
    col4.metric("Total Markets", len(df))
    
    st.markdown("---")
    
    # 筛选器
    col_filter1, col_filter2 = st.columns([1, 3])
    
    with col_filter1:
        status_filter = st.multiselect(
            "Filter by Status",
            options=["🟢 Informed", "🟡 Fragmented", "🔴 Noisy"],
            default=[]
        )
    
    # 应用筛选
    if status_filter:
        # 移除 emoji 进行匹配
        filter_keywords = [s.split(' ')[1] for s in status_filter]
        mask = df['status'].str.contains('|'.join(filter_keywords), na=False)
        df_filtered = df[mask]
    else:
        df_filtered = df
    
    # 显示表格
    st.dataframe(
        df_filtered[['market_name', 'status', 'ui', 'cs', 'current_price']],
        use_container_width=True,
        column_config={
            "market_name": st.column_config.TextColumn(
                "Market",
                width="large"
            ),
            "status": st.column_config.TextColumn(
                "Status",
                width="medium"
            ),
            "ui": st.column_config.NumberColumn(
                "UI", 
                format="%.4f",
                help="Uncertainty Index"
            ),
            "cs": st.column_config.NumberColumn(
                "CS", 
                format="%.4f",
                help="Conviction Score"
            ),
            "current_price": st.column_config.NumberColumn(
                "Price", 
                format="%.2f%%",
                help="Current market price"
            )
        },
        hide_index=True
    )
    
    # 状态说明
    with st.expander("ℹ️ What do these statuses mean?"):
        st.markdown("""
        **🟢 Informed:** Market has formed stable consensus. Information is well-digested.
        
        **🟡 Fragmented:** Market understanding is divided. Requires careful analysis.
        
        **🔴 Noisy:** Market lacks stable cognitive structure. Not worth attention now.
        """)
    
except Exception as e:
    st.error(f"Error loading data: {e}")
    import traceback
    st.code(traceback.format_exc())
    st.info("Make sure you've run `python jobs/sync.py` first.")