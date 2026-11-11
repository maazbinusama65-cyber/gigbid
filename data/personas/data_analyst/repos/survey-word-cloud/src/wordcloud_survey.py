from wordcloud import WordCloud

def score_survey(text):
    return WordCloud(width=800, height=400).generate(text)
