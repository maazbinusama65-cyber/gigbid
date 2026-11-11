# FAQ Keyword Bot

**Client industry:** Hospitality  
**Completed:** 2021-10  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: a restaurant wanted automatic replies to opening-hours questions. They described what they wanted as a opening-hours auto-reply.

## What I built

Under the hood: rule-based chatbot.

## Outcome

Result: answered 60% of enquiries using fixed keyword rules (no machine learning involved).

## Stack

rule-based chatbot

## A snippet

```py
import re

RULES = [(re.compile(r'refund|money back', re.I), 'refund_policy'), (re.compile(r'hours|open', re.I), 'opening_hours')]

def build_faq(text):
    return next((a for r, a in RULES if r.search(text)), 'fallback')
```

