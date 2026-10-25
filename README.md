# Quantitative Stock Scanner & Backtesting System

## Overview
An automated stock scanning and analysis system developed in Python. It tracks institutional buying trends, foreign investor volume, and YoY revenue growth using TWSE and FinMind APIs, storing massive market data locally via SQLite for high-speed querying and historical win-rate backtesting.

## Key Features
* **Automated Data Pipeline:** Incremental daily updates for price action, institutional movements, and monthly revenue data across the entire Taiwan stock market.
* **Quantitative Radar:** Filters equities based on institutional consensus (e.g., continuous buying by foreign and domestic trusts) and calculates 5-day forward return probabilities.
* **SQLite Integration:** Optimized database design with indexing to handle years of daily market data efficiently without API rate limits.
* **Interactive Visualization:** Integrates Plotly to generate dynamic candlestick charts, KD indicators, and institutional net-buy overlays.

## Core Modules
* `stock_scanner.py`: Main quantitative scanning radar and historical backtesting engine.
* `stockauto_pro.py`: Fault-tolerant data pipeline for building and updating the SQLite database.
* `dailyupdate.py`: High-speed daily after-market data fetcher directly from TWSE/TPEx.
* `stock_viewer.py`: Interactive financial charting tool.

## Technologies Used
* **Language:** Python (Pandas, Requests, NumPy)
* **Database:** SQLite3
* **Visualization:** Plotly
* **Data Sources:** TWSE Official API, TPEx Official API, FinMind, Yahoo Finance
