import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key="lm-studio")
vec = client.embeddings.create(model=os.environ["EMBED_MODEL"], input=["test"]).data[0].embedding
print("dimension:", len(vec))

