from pinecone import Pinecone

pc = Pinecone(api_key='...')
index = pc.Index('internal_docs_chatbot')

def score_internal(vec, industry):
    return index.query(vector=vec, top_k=8, filter={'industry': industry})
