from openai import OpenAI

from src.prompts.prompt_templates import SYSTEM_PROMPT, render_question
from src.vectordb.vector_store import SearchHit


class LLMClient:
    def __init__(self, client: OpenAI, model: str):
        self.client = client
        self.model = model

    def answer(self, question: str, hits: list[SearchHit]) -> str:
        response = self.client.responses.create(
            model=self.model, instructions=SYSTEM_PROMPT,
            input=render_question(question, hits), store=False,
        )
        return response.output_text or "Model nije vratio odgovor."
