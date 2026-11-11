from transformers import AutoTokenizer, AutoModelForSequenceClassification

tok = AutoTokenizer.from_pretrained('distilbert-base-uncased')
model = AutoModelForSequenceClassification.from_pretrained('distilbert-base-uncased', num_labels=6)

def load_review(texts):
    batch = tok(texts, truncation=True, padding=True, return_tensors='pt')
    return model(**batch).logits.softmax(-1)
