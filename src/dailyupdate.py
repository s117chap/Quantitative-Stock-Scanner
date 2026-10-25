import os
import time
import datetime
import sqlite3
import requests
import pandas as pd
import warnings

warnings.filterwarnings('ignore')
DB_PATH = "./stock_database/taiwan_stocks.db"

def clean_num(x):
    """清洗證交所與櫃買中心帶有逗號的數字字串"""
    if pd.isna(x): return 0.0
    if isinstance(x, str):
        x = x.replace(',', '').replace('--', '0').replace('---', '0').replace('X', '0').strip()
        if x == '': return 0.0
    try:
        return float(x)
    except:
        return 0.0

def get_latest_trading_date():
    """自動判定最近的交易日 (避開六日與提早盤中執行)"""
    now = datetime.datetime.now()
    for i in range(7):
        target = now - datetime.timedelta(days=i)
        # 避開週末
        if target.weekday() >= 5:
            continue
        # 如果是今天，但下午 2 點半前執行，代表收盤資料還沒出，改抓昨天
        if i == 0 and now.hour < 14:
            continue
        return target.strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d")

def update_daily():
    target_date = get_latest_trading_date()
    print("=" * 65)
    print(f"🚀 啟動【機構級】極速每日更新引擎 | 目標日期: {target_date}")
    print("=" * 65)
    
    dt = datetime.datetime.strptime(target_date, "%Y-%m-%d")
    twse_date = dt.strftime("%Y%m%d")          # 證交所格式: YYYYMMDD
    roc_date = f"{dt.year - 1911}/{dt.month:02d}/{dt.day:02d}"  # 櫃買格式: 113/10/15
    
    conn = sqlite3.connect(DB_PATH)
    
    # =========================================================
    # 1. 抓取【上市】全市場股價 (TWSE MI_INDEX)
    # =========================================================
    print("  [1/4] 抓取 上市 (TWSE) 全市場今日股價...")
    url_twse_p = f"https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={twse_date}&type=ALLBUT0999"
    try:
        res = requests.get(url_twse_p, timeout=10).json()
        if res.get('stat') == 'OK':
            fields = next((v for k, v in res.items() if isinstance(v, list) and '證券代號' in v and '收盤價' in v), None)
            if fields:
                data_key = next((k for k, v in res.items() if v == fields)).replace('fields', 'data')
                df = pd.DataFrame(res[data_key], columns=fields)
                
                df_p = pd.DataFrame()
                df_p['stock_id'] = df['證券代號']
                df_p['date'] = target_date
                df_p['open'] = df['開盤價'].apply(clean_num)
                df_p['max'] = df['最高價'].apply(clean_num)
                df_p['min'] = df['最低價'].apply(clean_num)
                df_p['close'] = df['收盤價'].apply(clean_num)
                df_p['Trading_Volume'] = df['成交股數'].apply(clean_num)
                
                # 過濾出純數字的股票代號 (排除權證等)
                df_p = df_p[df_p['stock_id'].str.match(r'^\d{4}$')]
                df_p.to_sql("temp_price", conn, if_exists="replace", index=False)
                conn.execute("INSERT OR REPLACE INTO daily_price (stock_id, date, open, max, min, close, Trading_Volume) SELECT * FROM temp_price")
    except Exception as e:
        print(f"    - 上市股價抓取失敗: {e}")
    time.sleep(1.5)

    # =========================================================
    # 2. 抓取【上市】全市場三大法人 (TWSE T86)
    # =========================================================
    print("  [2/4] 抓取 上市 (TWSE) 全市場土洋籌碼...")
    url_twse_i = f"https://www.twse.com.tw/fund/T86?response=json&date={twse_date}&selectType=ALLBUT0999"
    try:
        res = requests.get(url_twse_i, timeout=10).json()
        if res.get('stat') == 'OK':
            fields = next((v for k, v in res.items() if isinstance(v, list) and '證券代號' in v and '投信買進股數' in v), None)
            if fields:
                data_key = next((k for k, v in res.items() if v == fields)).replace('fields', 'data')
                df = pd.DataFrame(res[data_key], columns=fields)
                df = df[df['證券代號'].str.match(r'^\d{4}$')]
                
                # 尋找對應欄位名稱 (動態防呆)
                f_buy = next((c for c in fields if '外陸資買進' in c or '外資買進' in c), None)
                f_sell = next((c for c in fields if '外陸資賣出' in c or '外資賣出' in c), None)
                t_buy = next((c for c in fields if '投信買進' in c), None)
                t_sell = next((c for c in fields if '投信賣出' in c), None)
                
                all_inst = []
                if f_buy and f_sell:
                    df_f = pd.DataFrame({'stock_id': df['證券代號'], 'date': target_date, 'name': 'Foreign Investor', 
                                         'buy': df[f_buy].apply(clean_num), 'sell': df[f_sell].apply(clean_num)})
                    all_inst.append(df_f)
                if t_buy and t_sell:
                    df_t = pd.DataFrame({'stock_id': df['證券代號'], 'date': target_date, 'name': 'Investment Trust', 
                                         'buy': df[t_buy].apply(clean_num), 'sell': df[t_sell].apply(clean_num)})
                    all_inst.append(df_t)
                
                if all_inst:
                    df_inst = pd.concat(all_inst)
                    df_inst.to_sql("temp_inst", conn, if_exists="replace", index=False)
                    conn.execute("INSERT OR REPLACE INTO institutional (stock_id, date, name, buy, sell) SELECT * FROM temp_inst")
    except Exception as e:
        print(f"    - 上市籌碼抓取失敗: {e}")
    time.sleep(1.5)

    # =========================================================
    # 3. 抓取【上櫃】全市場股價 (TPEx)
    # =========================================================
    print("  [3/4] 抓取 上櫃 (TPEx) 全市場今日股價...")
    url_tpex_p = f"https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php?l=zh-tw&d={roc_date}&se=EW"
    try:
        res = requests.get(url_tpex_p, timeout=10).json()
        if 'aaData' in res and len(res['aaData']) > 0:
            df = pd.DataFrame(res['aaData'])
            df_p = pd.DataFrame()
            df_p['stock_id'] = df[0]
            df_p['date'] = target_date
            df_p['close'] = df[2].apply(clean_num)
            df_p['open'] = df[4].apply(clean_num)
            df_p['max'] = df[5].apply(clean_num)
            df_p['min'] = df[6].apply(clean_num)
            df_p['Trading_Volume'] = df[7].apply(clean_num)
            
            df_p = df_p[df_p['stock_id'].str.match(r'^\d{4}$')]
            df_p.to_sql("temp_price", conn, if_exists="replace", index=False)
            conn.execute("INSERT OR REPLACE INTO daily_price (stock_id, date, open, max, min, close, Trading_Volume) SELECT * FROM temp_price")
    except Exception as e:
        print(f"    - 上櫃股價抓取失敗: {e}")
    time.sleep(1.5)

    # =========================================================
    # 4. 抓取【上櫃】全市場三大法人 (TPEx)
    # =========================================================
    print("  [4/4] 抓取 上櫃 (TPEx) 全市場土洋籌碼...")
    url_tpex_i = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&d={roc_date}"
    try:
        res = requests.get(url_tpex_i, timeout=10).json()
        if 'aaData' in res and len(res['aaData']) > 0:
            df = pd.DataFrame(res['aaData'])
            
            df_f = pd.DataFrame({'stock_id': df[0], 'date': target_date, 'name': 'Foreign Investor', 
                                 'buy': df[2].apply(clean_num), 'sell': df[3].apply(clean_num)})
            df_t = pd.DataFrame({'stock_id': df[0], 'date': target_date, 'name': 'Investment Trust', 
                                 'buy': df[9].apply(clean_num), 'sell': df[10].apply(clean_num)})
            
            df_inst = pd.concat([df_f, df_t])
            df_inst = df_inst[df_inst['stock_id'].str.match(r'^\d{4}$')]
            
            df_inst.to_sql("temp_inst", conn, if_exists="replace", index=False)
            conn.execute("INSERT OR REPLACE INTO institutional (stock_id, date, name, buy, sell) SELECT * FROM temp_inst")
    except Exception as e:
        print(f"    - 上櫃籌碼抓取失敗: {e}")
        
    conn.commit()
    conn.close()
    
    print("\n" + "=" * 65)
    print(f"✅ 更新完成！全台灣 1,990 檔股票【{target_date}】最新行情已匯入資料庫。")
    print("現在你可以立刻執行 stock_scanner_pro_7.py 來掃描最新標的了！")
    print("=" * 65)

if __name__ == "__main__":
    update_daily()
