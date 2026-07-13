import sqlite3

conn = sqlite3.connect('E:\\\\" + 'E:\\ETF_Surge\\\\backend\\\\data\\\\portfolio.db' + '\\\"')
cur = conn.cursor()

# Set tracked_index for 007467 to 000300 (沪深300)
cur.execute('UPDATE portfolio_etfs SET tracked_index = "000300" WHERE symbol = "007467"')
print(f'Updated tracked_index for 007467 to 000300')

# Verify
cur.execute('SELECT tracked_index FROM portfolio_etfs WHERE symbol = "007467"')
print('007467 tracked_index:', cur.fetchone())

conn.commit()
conn.close()