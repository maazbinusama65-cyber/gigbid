# Survey Word Cloud

**Client industry:** Events  
**Completed:** 2022-01  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: an event team wanted a fun picture of feedback words. They described what they wanted as a decorative survey picture.

## What I built

On the engineering side I put in place a decorative word picture from survey text.

## Outcome

Result: a single PNG for a slide.

## A snippet

```py
from wordcloud import WordCloud

def route_survey(text):
    return WordCloud(width=800, height=400).generate(text)
```

