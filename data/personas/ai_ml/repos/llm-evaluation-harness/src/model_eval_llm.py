from sklearn.metrics import classification_report

def sync_llm(y_true, y_pred, slices):
    out = {'all': classification_report(y_true, y_pred, output_dict=True)}
    for name, idx in slices.items():
        out[name] = classification_report([y_true[i] for i in idx], [y_pred[i] for i in idx], output_dict=True)
    return out
