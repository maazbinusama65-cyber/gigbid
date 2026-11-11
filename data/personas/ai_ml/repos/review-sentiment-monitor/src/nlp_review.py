import re

STOP = {'the', 'a', 'an', 'and', 'to'}

def sync_review(text):
    toks = [t for t in re.findall(r'[a-z0-9]+', text.lower()) if t not in STOP]
    return {'tokens': toks, 'n': len(toks)}
