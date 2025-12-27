import streamlit as st
import pandas as pd
from sqlalchemy import text
import sys
import os

# 添加项目根目录到 path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
                token_id,
                status,
                ui,
                cer,
                cs,
                current_price,
                date
            FROM daily_metrics
            WHERE date = (SELECT MAX(date) FROM daily_metrics)
            ORDER BY 
                CASE 
                    WHEN status LIKE '%Informed%' THEN 1
                    WHEN status LIKE '%Fragmented%' THEN 2
                    ELSE 3
                END
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
    
    informed_count = len(df[df['status'].str.contains('Informed')])
    fragmented_count = len(df[df['status'].str.contains('Fragmented')])
    noisy_count = len(df[df['status'].str.contains('Noisy')])
    
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
        mask = df['status'].isin(status_filter)
        df_filtered = df[mask]
    else:
        df_filtered = df
    
    # 显示表格
    st.dataframe(
        df_filtered[['token_id', 'status', 'ui', 'cs', 'current_price']],
        use_container_width=True,
        column_config={
            "token_id": "Market",
            "status": "Status",
            "ui": st.column_config.NumberColumn("UI", format="%.4f"),
            "cs": st.column_config.NumberColumn("CS", format="%.4f"),
            "current_price": st.column_config.NumberColumn("Price", format="%.2f%%")
        }
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
    st.info("Make sure you've run `python jobs/sync.py` first.")