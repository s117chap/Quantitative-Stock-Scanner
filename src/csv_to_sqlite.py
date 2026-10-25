import os
import sqlite3
import pandas as pd
import glob

DATA_DIR = "./stock_database"
DB_PATH = os.path.join(DATA_DIR, "taiwan_stocks.db")

def migrate_to_sqlite():
    print("=" * 50)
    print("啟動資料庫升級：CSV -> SQLite 轉換工程")
    print("=" * 50)
    
    # 建立與 SQLite 的連線
    conn = sqlite3.connect(DB_PATH)
    
    # 1. 轉移全台股清單
    list_path = os.path.join(DATA_DIR, "taiwan_all_stocks_list.csv")
    if os.path.exists(list_path):
        df_list = pd.read_csv(list_path)
        df_list.to_sql('stock_list', conn, if_exists='replace', index=False)
        print(" 股票代號總表已寫入 SQLite [stock_list] 資料表")

    # 2. 轉移股價與法人資料
    price_files = glob.glob(os.path.join(DATA_DIR, "TaiwanStockPrice_*.csv"))
    total_files = len(price_files)
    
    print(f"\n準備轉移 {total_files} 檔股票的歷史資料，這可能需要幾分鐘，請稍候...")
    
    for idx, filepath in enumerate(price_files, 1):
        filename = os.path.basename(filepath)
        stock_id = filename.replace("TaiwanStockPrice_", "").replace(".csv", "")
        
        if idx % 200 == 0:
            print(f"進度：已處理 {idx} / {total_files} 檔...")

        # 讀取股價
        df_price = pd.read_csv(filepath)
        if not df_price.empty:
            df_price['stock_id'] = stock_id # 補上代號欄位
            df_price.to_sql('daily_price', conn, if_exists='append', index=False)
            
        # 讀取法人籌碼
        inst_path = os.path.join(DATA_DIR, f"TaiwanStockInstitutionalInvestorsBuySell_{stock_id}.csv")
        if os.path.exists(inst_path):
            df_inst = pd.read_csv(inst_path)
            if not df_inst.empty:
                df_inst['stock_id'] = stock_id
                df_inst.to_sql('institutional', conn, if_exists='append', index=False)

    # 建立資料庫索引 (Index) 大幅加速未來的查詢速度
    print("\n正在建立資料庫索引以優化查詢速度...")
    cursor = conn.cursor()
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_stock_date ON daily_price (stock_id, date);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_inst_stock_date ON institutional (stock_id, date);")
    conn.commit()
    conn.close()

    print("\n 升級完成！所有資料已成功打包至 taiwan_stocks.db")

if __name__ == "__main__":
    migrate_to_sqlite()
