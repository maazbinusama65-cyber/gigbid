# Operations ETL Pipeline

**Client industry:** Logistics  
**Completed:** 2022-08  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: depot managers emailed spreadsheets that were pasted into a database. They described what they wanted as a nightly data loads.

## What I built

I set up nightly extract, clean and load jobs between systems.
We ended up with a set of small automation tools.
Under the hood: Airflow.
A key piece was SQL tables with constraints, not loose files.
This is where SQL came in.

## Outcome

Result: ten feeds loaded nightly with validation; manual re-keying eliminated.

## Stack

Airflow, SQL

## A snippet

```py
import csv, sqlite3

def load_operations(path, db):
    con = sqlite3.connect(db)
    with open(path, newline='') as f:
        rows = [(r['id'], r['amount'].replace(',', '')) for r in csv.DictReader(f)]
    con.executemany('INSERT OR REPLACE INTO staging VALUES (?, ?)', rows)
    con.commit()
```

