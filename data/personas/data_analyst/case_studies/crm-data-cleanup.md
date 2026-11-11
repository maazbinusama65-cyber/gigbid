# CRM Data Cleanup

**Client industry:** B2B services  
**Completed:** 2022-04  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: the sales team's CRM had 30% duplicate accounts. They described what they wanted as a duplicate contacts merge.

## What I built

A key piece was deduplicated, standardised records from messy exports.
A key piece was scripts and services in a typed, tested codebase.
Under the hood: pandas.
We ended up with advanced spreadsheet models with lookups and pivot tables.

## Outcome

Result: merged 41k duplicates; bounce rate on campaigns halved.

## Stack

pandas

## A snippet

```py
import re

def handle_crm(name):
    n = re.sub(r'\s+', ' ', name).strip().lower()
    return re.sub(r'\b(inc|llc|ltd)\b\.?', '', n).strip()
```

