import os
import sqlite3
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import warnings
warnings.filterwarnings('ignore')

DB_PATH = "./stock_database/taiwan_stocks.db"

def fetch_data_from_db(stock_id):
    """從 SQLite 高速撈取單一股票的股價與法人資料"""
    if not os.path.exists(DB_PATH):
        print("找不到 taiwan_stocks.db，請先執行 csv_to_sqlite.py 進行升級。")
        return None

    conn = sqlite3.connect(DB_PATH)
    
    # 撈取股價
    query_price = f"SELECT date, open, max as high, min as low, close, Trading_Volume as volume FROM daily_price WHERE stock_id = '{stock_id}' ORDER BY date"
    df_price = pd.read_sql(query_price, conn)
    
    # 撈取法人 (修正：利用 SQL 直接計算 buy - sell 得到淨買賣超)
    query_inst = f"SELECT date, name, (buy - sell) as buy_sell FROM institutional WHERE stock_id = '{stock_id}'"
    df_inst_raw = pd.read_sql(query_inst, conn)
    conn.close()

    if df_price.empty:
        return None

    df_inst = pd.DataFrame()
    if not df_inst_raw.empty:
        df_inst = df_inst_raw.pivot_table(
            index='date', columns='name', values='buy_sell', aggfunc='sum'
        ).fillna(0).reset_index()

    # 合併兩張表
    df = pd.merge(df_price, df_inst, on='date', how='left').fillna(0)
    return df

def plot_stock_chart(stock_id, df):
    """使用 Plotly 繪製專業 K 線圖、籌碼圖與 KD 指標"""
    # --- 1. 計算均線與 KD 指標 ---
    df['MA5'] = df['close'].rolling(window=5).mean()
    df['MA20'] = df['close'].rolling(window=20).mean()

    # 計算 9日 KD
    df['9D_High'] = df['high'].rolling(window=9).max()
    df['9D_Low'] = df['low'].rolling(window=9).min()
    denom = df['9D_High'] - df['9D_Low']
    df['RSV'] = np.where(denom == 0, 50, 100 * (df['close'] - df['9D_Low']) / denom)
    df['RSV'] = pd.Series(df['RSV']).fillna(50)
    df['K'] = df['RSV'].ewm(com=2, adjust=False).mean()
    df['D'] = df['K'].ewm(com=2, adjust=False).mean()

    # --- 2. 建立四個子圖版面 ---
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, 
        vertical_spacing=0.03, row_heights=[0.5, 0.15, 0.15, 0.2],
        subplot_titles=(f"{stock_id} 股價走勢與均線", "成交量", "投信與外資淨買賣超(股)", "日線 KD 指標")
    )

    # (1) K 線圖與均線
    fig.add_trace(go.Candlestick(
        x=df['date'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
        name='K線', increasing_line_color='red', decreasing_line_color='green'
    ), row=1, col=1)

    fig.add_trace(go.Scatter(x=df['date'], y=df['MA5'], name='5日均線(MA5)', line=dict(color='blue', width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['date'], y=df['MA20'], name='20日均線(MA20)', line=dict(color='orange', width=1)), row=1, col=1)

    # (2) 成交量
    colors_vol = ['red' if close >= open else 'green' for close, open in zip(df['close'], df['open'])]
    fig.add_trace(go.Bar(x=df['date'], y=df['volume'], name='成交量', marker_color=colors_vol), row=2, col=1)

    # (3) 法人籌碼
    if 'Investment Trust' in df.columns and 'Foreign Investor' in df.columns:
        fig.add_trace(go.Bar(x=df['date'], y=df['Investment Trust'], name='投信淨買賣', marker_color='purple'), row=3, col=1)
        fig.add_trace(go.Bar(x=df['date'], y=df['Foreign Investor'], name='外資淨買賣', marker_color='cyan'), row=3, col=1)

    # (4) KD 指標
    fig.add_trace(go.Scatter(x=df['date'], y=df['K'], name='K值', line=dict(color='orange', width=1.5)), row=4, col=1)
    fig.add_trace(go.Scatter(x=df['date'], y=df['D'], name='D值', line=dict(color='dodgerblue', width=1.5)), row=4, col=1)
    
    # 畫上 80 (超買) 與 20 (超賣) 輔助線
    fig.add_hline(y=80, line_dash="dot", line_color="red", line_width=1, row=4, col=1, opacity=0.5)
    fig.add_hline(y=20, line_dash="dot", line_color="green", line_width=1, row=4, col=1, opacity=0.5)

    # 設定圖表外觀
    fig.update_layout(
        title=f"【專屬量化系統】{stock_id} 綜合分析圖表 (含 KD)",
        height=1000, hovermode="x unified", template="plotly_dark"
    )
    # 確保所有子圖的 K 線底部拉桿被隱藏，保持畫面乾淨
    fig.update_xaxes(rangeslider=dict(visible=False))
    
    fig.show()

if __name__ == "__main__":
    print("=" * 50)
    target_stock = input("請輸入你想查看圖表的股票代號 (例如 6488, 2330)：")
    data = fetch_data_from_db(target_stock)
    
    if data is not None:
        plot_stock_chart(target_stock, data)
    else:
        print(f"找不到 {target_stock} 的資料。")
