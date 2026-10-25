import os
import time
import datetime
import requests
import pandas as pd
import sqlite3
from FinMind.data import DataLoader
import warnings
warnings.filterwarnings('ignore')

# ==============================================================================
# 1. 系統設定
# ==============================================================================
DATA_DIR = "./stock_database"
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "taiwan_stocks.db")

END_DATE = datetime.date.today().strftime("%Y-%m-%d")
START_DATE = (datetime.date.today() - datetime.timedelta(days=3 * 365)).strftime("%Y-%m-%d")

FINMIND_TOKEN = ""
dl = DataLoader()
if FINMIND_TOKEN.strip():
    dl.login_by_token(api_token=FINMIND_TOKEN.strip())

# ==============================================================================
# 2. SQLite 連線與建立必要表格
# ==============================================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_list (
            stock_id TEXT PRIMARY KEY,
            name TEXT,
            market TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_price (
            stock_id TEXT, date TEXT, open REAL, max REAL, min REAL, close REAL, Trading_Volume REAL,
            UNIQUE(stock_id, date)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS institutional (
            stock_id TEXT, date TEXT, name TEXT, buy REAL, sell REAL,
            UNIQUE(stock_id, date, name)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS month_revenue (
            stock_id TEXT, date TEXT, revenue REAL, revenue_month INTEGER, revenue_year INTEGER,
            UNIQUE(stock_id, date)
        )
    """)
    conn.commit()
    return conn

# ==============================================================================
# 3. 獲取全台股清單
# ==============================================================================
def get_all_taiwan_stocks(conn):
    try:
        df_cached = pd.read_sql("SELECT stock_id FROM stock_list", conn)
        if not df_cached.empty:
            print(f"[清單載入] 讀取資料庫全台股清單，共 {len(df_cached)} 檔。")
            return df_cached['stock_id'].astype(str).tolist()
    except Exception:
        pass

    print("[清單抓取] 正在向證交所與櫃買中心抓取最新上市、上櫃代號...")
    stock_list = []
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        df_twse = pd.read_html(requests.get("https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", headers=headers, timeout=15).text)[0]
        for val in df_twse.iloc[1:, 0].dropna():
            parts = str(val).split('\u3000')
            if len(parts) >= 2 and len(parts[0].strip()) == 4 and parts[0].strip().isdigit():
                stock_list.append({'stock_id': parts[0].strip(), 'name': parts[1].strip(), 'market': '上市'})
    except Exception as e:
        print(f"  [上市清單警告] {e}")

    try:
        df_tpex = pd.read_html(requests.get("https://isin.twse.com.tw/isin/C_public.jsp?strMode=4", headers=headers, timeout=15).text)[0]
        for val in df_tpex.iloc[1:, 0].dropna():
            parts = str(val).split('\u3000')
            if len(parts) >= 2 and len(parts[0].strip()) == 4 and parts[0].strip().isdigit():
                stock_list.append({'stock_id': parts[0].strip(), 'name': parts[1].strip(), 'market': '上櫃'})
    except Exception as e:
        print(f"  [上櫃清單警告] {e}")

    if not stock_list:
        return ["2330", "3711", "6488", "2327", "3374", "5483", "8299", "2317", "2454"]

    df_all = pd.DataFrame(stock_list).drop_duplicates(subset=['stock_id'])
    for _, row in df_all.iterrows():
        conn.execute("""
            INSERT INTO stock_list (stock_id, name, market) 
            VALUES (?, ?, ?) 
            ON CONFLICT(stock_id) DO UPDATE SET name=excluded.name, market=excluded.market
        """, (row['stock_id'], row['name'], row['market']))
    conn.commit()
    print(f"[清單完成] 成功建檔，共 {len(df_all)} 檔。")
    return df_all['stock_id'].astype(str).tolist()

# ==============================================================================
# 4. 增量更新與動態防呆寫入模組
# ==============================================================================
def fetch_incremental_data(fetch_func, table_name, stock_id, conn, desc):
    start_date = START_DATE
    try:
        query = f"SELECT MAX(date) FROM {table_name} WHERE stock_id = '{stock_id}'"
        cursor = conn.cursor()
        cursor.execute(query)
        last_date = cursor.fetchone()[0]
        
        if last_date:
            if last_date >= END_DATE:
                return True 
            next_day = datetime.datetime.strptime(last_date, "%Y-%m-%d") + datetime.timedelta(days=1)
            start_date = next_day.strftime("%Y-%m-%d")
            if start_date > END_DATE:
                return True
    except Exception:
        pass

    while True:
        try:
            print(f"  [抓取] {desc} (補齊區間: {start_date} ~ {END_DATE})...")
            df_new = fetch_func(stock_id=stock_id, start_date=start_date, end_date=END_DATE)

            if df_new is None or df_new.empty:
                return True

            df_new['stock_id'] = stock_id
            
            # 動態比對 SQLite 表格欄位，剔除無用欄位
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table_name})")
            valid_columns = [row[1] for row in cursor.fetchall()]
            df_new = df_new[[c for c in df_new.columns if c in valid_columns]]
            
            cols = ",".join(df_new.columns)
            placeholders = ",".join(["?"] * len(df_new.columns))
            sql = f"INSERT OR IGNORE INTO {table_name} ({cols}) VALUES ({placeholders})"
            
            cursor.executemany(sql, df_new.to_records(index=False).tolist())
            conn.commit()
            time.sleep(1.2)
            return True

        except Exception as e:
            err_msg = str(e)
            if "reach the upper limit" in err_msg:
                print(f"\n⚠️ 觸發 FinMind 免費版每小時 API 請求上限！自動暫停 60 分鐘冷卻...")
                for remaining in range(60, 0, -1):
                    print(f"  [休眠中] 剩餘 {remaining} 分鐘...", end='\r')
                    time.sleep(60)
                print("\n✅ 冷卻結束，繼續抓取！")
                continue
            else:
                print(f"  [異常] {desc} 抓取略過: {err_msg}")
                return False

# ==============================================================================
# 5. 主排程迴圈
# ==============================================================================
def main():
    print("=" * 60)
    print("🚀 啟動量化資料庫擴充計畫 (高容錯不斷線版)")
    print("=" * 60)

    conn = init_db()
    all_stocks = get_all_taiwan_stocks(conn)

    priority_stocks = ["2330", "3711", "6488", "2327", "3374", "5483", "8299", "2317", "2454"]
    sorted_stocks = priority_stocks + [s for s in all_stocks if s not in priority_stocks]
    total_count = len(sorted_stocks)

    for idx, stock_id in enumerate(sorted_stocks, 1):
        print(f"\n[{idx}/{total_count}] 處理個股: {stock_id}")

        # 終極防護罩：即使單一股票報錯，也會印出警告並繼續執行下一檔
        try:
            fetch_incremental_data(dl.taiwan_stock_daily, "daily_price", stock_id, conn, f"股價歷史")
            fetch_incremental_data(dl.taiwan_stock_institutional_investors, "institutional", stock_id, conn, f"三大法人")
            fetch_incremental_data(dl.taiwan_stock_month_revenue, "month_revenue", stock_id, conn, f"月營收表")
        except Exception as e:
            print(f"  [跳過] {stock_id} 發生未預期錯誤，程式自動略過並繼續執行下一檔。({e})")
            continue

    conn.execute("CREATE INDEX IF NOT EXISTS idx_rev_stock_date ON month_revenue (stock_id, date);")
    conn.commit()
    conn.close()

    print("\n" + "=" * 60)
    print("🎉 升級完成！資料庫已成功擴充【股價】、【籌碼】與【基本面營收】。")
    print("=" * 60)

if __name__ == "__main__":
    main()
