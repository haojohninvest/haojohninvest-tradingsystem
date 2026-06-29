import sqlite3

conn = sqlite3.connect("/home/ubuntu/haojohninvest-tradingsystem/db.sqlite3")
cur = conn.cursor()

cur.execute("SELECT date, COUNT(*) FROM market_data_dailyprice WHERE date >= '2026-01-01' AND date <= '2026-06-01' GROUP BY date ORDER BY date")
rows = cur.fetchall()
for r in rows:
    print(f"{r[0]} : {r[1]}")

conn.close()
