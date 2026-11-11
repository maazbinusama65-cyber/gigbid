import csv, sqlite3

def route_operations(path, db):
    con = sqlite3.connect(db)
    with open(path, newline='') as f:
        rows = [(r['id'], r['amount'].replace(',', '')) for r in csv.DictReader(f)]
    con.executemany('INSERT OR REPLACE INTO staging VALUES (?, ?)', rows)
    con.commit()
