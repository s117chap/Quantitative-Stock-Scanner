import os
import sqlite3
import pandas as pd
import numpy as np
import warnings
import yfinance as yf
import logging

warnings.filterwarnings('ignore')
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

# 解決終端機中英文字元對齊跑版的問題 (針對截圖中的排版錯亂)
pd.set_option('display.unicode.east_asian_width', True)
pd.set_option('display.unicode.ambiguous_as_wide', True)

DB_PATH = "./stock_database/taiwan_stocks.db"

def fetch_macro_indicators():
    print("=" * 70)
    print("🌍 總體經濟指標即時掃描 (資料來源: Yahoo Finance)")
    print("-" * 70)
    macros = {"國際原油 (WTI)": "CL=F", "國際黃金 (Gold)": "GC=F"}
    for name, ticker in macros.items():
        try:
            df = yf.download(ticker, period="3mo", progress=False)
            if df.empty: continue
            
            if isinstance(df.columns, pd.MultiIndex):
                close_series = df['Close', ticker].squeeze()
            else:
                close_series = df['Close'].squeeze()
                
            ma20_series = close_series.rolling(window=20).mean()
            price = float(close_series.iloc[-1])
            ma20 = float(ma20_series.iloc[-1])
            trend = "🔴 高於均線 (偏多/強勢)" if price > ma20 else "🟢 低於均線 (偏空/弱勢)"
            print(f"  - {name:12s} | 最新價: {price:7.2f} | 20日均線: {ma20:7.2f} | {trend}")
        except Exception:
            pass
    print("=" * 70 + "\n")

def scan_stock_sqlite(stock_id, conn):
    query_price = f"""
    SELECT 
        p.date, p.open, p.max as high, p.min as low, p.close, p.Trading_Volume as volume,
        SUM(CASE WHEN i.name LIKE '%Investment%' OR i.name LIKE '%投信%' THEN (i.buy - i.sell) ELSE 0 END) as Investment_Trust,
        SUM(CASE WHEN i.name LIKE '%Foreign%' OR i.name LIKE '%外陸資%' OR i.name LIKE '%外資%' THEN (i.buy - i.sell) ELSE 0 END) as Foreign_Investor
    FROM daily_price p
    LEFT JOIN institutional i ON p.stock_id = i.stock_id AND p.date = i.date
    WHERE p.stock_id = '{stock_id}'
    GROUP BY p.date
    ORDER BY p.date
    """
    
    query_rev = f"SELECT date, revenue FROM month_revenue WHERE stock_id = '{stock_id}' ORDER BY date DESC LIMIT 13"
    
    try:
        df = pd.read_sql(query_price, conn)
        df_rev = pd.read_sql(query_rev, conn)
        
        if df.empty or len(df) < 15:
            return None
            
        df = df.fillna(0)
            
        # 計算連買天數與累計張數
        df['投信買超_bool'] = df['Investment_Trust'] > 0
        df['外資買超_bool'] = df['Foreign_Investor'] > 0
        
        df['投信連買2天'] = df['投信買超_bool'].rolling(window=2).sum() >= 2
        df['投信連買3天'] = df['投信買超_bool'].rolling(window=3).sum() >= 3
        df['外資連買2天'] = df['外資買超_bool'].rolling(window=2).sum() >= 2
        df['外資連買3天'] = df['外資買超_bool'].rolling(window=3).sum() >= 3
        
        trust_2d_sum = df['Investment_Trust'].tail(2).sum()
        trust_3d_sum = df['Investment_Trust'].tail(3).sum()
        foreign_2d_sum = df['Foreign_Investor'].tail(2).sum()
        foreign_3d_sum = df['Foreign_Investor'].tail(3).sum()
        
        # 歷史回測：計算「土洋同買」後，未來 5 天的上漲機率與平均報酬
        df['fwd_5d_ret'] = df['close'].shift(-5) / df['close'] - 1
        signal_mask = (df['Investment_Trust'] > 0) & (df['Foreign_Investor'] > 0)
        past_signals = df[signal_mask & df['fwd_5d_ret'].notna()]
        
        win_rate = 0.0
        avg_ret = 0.0
        if len(past_signals) > 0:
            win_rate = (past_signals['fwd_5d_ret'] > 0).mean() * 100
            avg_ret = past_signals['fwd_5d_ret'].mean() * 100
        
        volume_3d = df['volume'].tail(3).sum()
        latest = df.iloc[-1]
        
        yoy = 0
        if len(df_rev) >= 13:
            latest_rev = float(df_rev.iloc[0]['revenue'])
            last_year_rev = float(df_rev.iloc[12]['revenue'])
            if last_year_rev > 0:
                yoy = ((latest_rev / last_year_rev) - 1) * 100
                    
        return {
            '代號': str(stock_id),
            '日期': latest['date'],
            '收盤價': round(latest['close'], 2),
            '營收YoY(%)': round(yoy, 1),
            '投信買超(張)': round(latest['Investment_Trust'] / 1000, 1),
            '外資買超(張)': round(latest['Foreign_Investor'] / 1000, 1),
            
            '投信連買2天': bool(latest['投信連買2天']),
            '投信連買3天': bool(latest['投信連買3天']),
            '外資連買2天': bool(latest['外資連買2天']),
            '外資連買3天': bool(latest['外資連買3天']),
            
            '投信2日買超(張)': round(trust_2d_sum / 1000, 1),
            '投信3日買超(張)': round(trust_3d_sum / 1000, 1),
            '外資2日買超(張)': round(foreign_2d_sum / 1000, 1),
            '外資3日買超(張)': round(foreign_3d_sum / 1000, 1),
            
            '近3日成交量(張)': int(volume_3d / 1000),
            '勝率(%)': round(win_rate, 1),
            '平均報酬(%)': round(avg_ret, 1)
        }
    except Exception:
        return None

def main():
    fetch_macro_indicators()
    
    print("🚀 啟動【多維度籌碼與基本面】終極選股雷達 (含歷史勝率回測)...")
    print("正在全市場掃描中，請稍候...\n")
    
    if not os.path.exists(DB_PATH):
        print("資料庫不存在，請先完成建檔。")
        return

    conn = sqlite3.connect(DB_PATH)
    df_list = pd.read_sql("SELECT stock_id, name FROM stock_list", conn)
    df_list['stock_id'] = df_list['stock_id'].astype(str)
    stock_ids = df_list['stock_id'].tolist()

    all_results = []
    total = len(stock_ids)
    
    for idx, stock_id in enumerate(stock_ids, 1):
        if idx % 100 == 0:
            print(f"  [掃描進度] 已掃描 {idx}/{total} 檔...", end='\r')
            
        result = scan_stock_sqlite(stock_id, conn)
        if result:
            all_results.append(result)
            
    print(f"  [掃描進度] 掃描完成！處理了 {total} 檔股票。      ")
    conn.close()

    if not all_results:
        print("查無有效股票資料。")
        return
        
    df_all = pd.DataFrame(all_results)
    df_all['代號'] = df_all['代號'].astype(str)
    df_merged = pd.merge(df_all, df_list, left_on='代號', right_on='stock_id', how='left')
    
    # ---------------------------------------------------------
    # 排行榜產生區 (加入勝率與報酬率)
    # ---------------------------------------------------------
    display_cols = ['代號', 'name', '收盤價', '買超張數', '勝率(%)', '平均報酬(%)', '營收YoY(%)']
    
    # 1. 外資連買2天 (依2日總合排序)
    df_f2 = df_merged[df_merged['外資連買2天'] == True].copy()
    df_f2['買超張數'] = df_f2['外資2日買超(張)']
    df_f2 = df_f2.sort_values('買超張數', ascending=False).head(15)[display_cols].rename(columns={'name':'名稱'})

    # 2. 外資連買3天 (依3日總合排序)
    df_f3 = df_merged[df_merged['外資連買3天'] == True].copy()
    df_f3['買超張數'] = df_f3['外資3日買超(張)']
    df_f3 = df_f3.sort_values('買超張數', ascending=False).head(15)[display_cols].rename(columns={'name':'名稱'})

    # 3. 投信連買2天 (依2日總合排序)
    df_t2 = df_merged[df_merged['投信連買2天'] == True].copy()
    df_t2['買超張數'] = df_t2['投信2日買超(張)']
    df_t2 = df_t2.sort_values('買超張數', ascending=False).head(15)[display_cols].rename(columns={'name':'名稱'})

    # 4. 投信連買3天 (依3日總合排序)
    df_t3 = df_merged[df_merged['投信連買3天'] == True].copy()
    df_t3['買超張數'] = df_t3['投信3日買超(張)']
    df_t3 = df_t3.sort_values('買超張數', ascending=False).head(15)[display_cols].rename(columns={'name':'名稱'})

    # 5. 終極名單：土洋共識 2日連買 (投信與外資都連買2天)
    cond_both_2d = (df_merged['投信連買2天'] == True) & (df_merged['外資連買2天'] == True)
    df_both_2d = df_merged[cond_both_2d].copy()
    df_both_2d['買超張數'] = df_both_2d['投信2日買超(張)'] + df_both_2d['外資2日買超(張)']
    df_both_2d = df_both_2d.sort_values('買超張數', ascending=False).head(20)[display_cols].rename(columns={'name':'名稱'})

    # 6. 終極名單：土洋共識 3日連買 (投信與外資都連買3天)
    cond_both_3d = (df_merged['投信連買3天'] == True) & (df_merged['外資連買3天'] == True)
    df_both_3d = df_merged[cond_both_3d].copy()
    df_both_3d['買超張數'] = df_both_3d['投信3日買超(張)'] + df_both_3d['外資3日買超(張)']
    df_both_3d = df_both_3d.sort_values('買超張數', ascending=False).head(20)[display_cols].rename(columns={'name':'名稱'})

    # ================= 輸出報表 =================
    print("\n" + "="*70)
    print("一、 【外資動能】外資連買 2 天 (依近2日買超總合排序)")
    print("-" * 70)
    if df_f2.empty: print("無符合標的。")
    else: print(df_f2.to_string(index=False))

    print("\n" + "="*70)
    print("二、 【外資動能】外資連買 3 天 (依近3日買超總合排序)")
    print("-" * 70)
    if df_f3.empty: print("無符合標的。")
    else: print(df_f3.to_string(index=False))

    print("\n" + "="*70)
    print("三、 【投信動能】投信連買 2 天 (依近2日買超總合排序)")
    print("-" * 70)
    if df_t2.empty: print("無符合標的。")
    else: print(df_t2.to_string(index=False))

    print("\n" + "="*70)
    print("四、 【投信動能】投信連買 3 天 (依近3日買超總合排序)")
    print("-" * 70)
    if df_t3.empty: print("無符合標的。")
    else: print(df_t3.to_string(index=False))

    print("\n" + "="*70)
    print("⭐ 五、 【土洋共識 2日】外資與投信皆「連買 2 天」(依合買總量排序)")
    print("-" * 70)
    if df_both_2d.empty: print("今日無土洋連2日共識標的。")
    else: print(df_both_2d.to_string(index=False))

    print("\n" + "="*70)
    print("🏆 六、 【土洋共識 3日】外資與投信皆「連買 3 天」(依合買總量排序)")
    print("-" * 70)
    if df_both_3d.empty: print("今日無土洋連3日共識標的。")
    else: print(df_both_3d.to_string(index=False))
    
    print("\n" + "="*70)
    print("📊 掃描報告產出完畢！勝率與報酬率為該股歷史發生「土洋同買」後5日之回測數據。")
    print("="*70)

if __name__ == "__main__":
    main()
