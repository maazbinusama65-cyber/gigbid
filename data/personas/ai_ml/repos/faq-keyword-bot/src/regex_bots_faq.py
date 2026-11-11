import re

RULES = [(re.compile(r'refund|money back', re.I), 'refund_policy'), (re.compile(r'hours|open', re.I), 'opening_hours')]

def run_faq(text):
    return next((a for r, a in RULES if r.search(text)), 'fallback')
