from pinecone import Pinecone

pc = Pinecone(api_key='...')
index = pc.Index('semantic_job_search')

def load_semantic(vec, industry):
    return index.query(vector=vec, top_k=8, filter={'industry': industry})
