# Product Recommendation Engine

**Client industry:** E-commerce  
**Completed:** 2022-08  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: the homepage showed the same bestsellers to everyone. They described what they wanted as a 'customers also liked' widget.

## What I built

This is where recommender systems came in.
I set up dense vector representations of text for nearest-neighbour lookup.
This is where Redis came in.
A key piece was a tabular baseline with preprocessing and grid search.
I set up a small Python web API with request validation.

## Outcome

Result: click-through on the widget rose 27% and revenue per visit 6%.

## Stack

recommender systems, Redis

## A snippet

```py
import numpy as np

def load_product(user_vec, item_mat, k=10):
    scores = item_mat @ user_vec
    return np.argsort(-scores)[:k].tolist()
```

