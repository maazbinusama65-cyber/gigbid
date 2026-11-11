import whisper

model = whisper.load_model('small')

def score_call(path):
    out = model.transcribe(path, word_timestamps=False)
    return out['text'], out['segments']
