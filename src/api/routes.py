import logging
from typing import Annotated

from fastapi import FastAPI, HTTPException
from openai import OpenAIError
from pydantic import BaseModel, StringConstraints

from src.llm.llm_client import LLMClient
from src.prompts.prompt_templates import NO_SOURCES
from src.retrieval.retriever import Retriever


class Question(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class Source(BaseModel):
    citation: int
    source: str
    location: str
    text: str
    score: float


class Answer(BaseModel):
    answer: str
    sources: list[Source]


def create_app(retriever: Retriever, llm: LLMClient) -> FastAPI:
    app = FastAPI(title="RAG")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/query", response_model=Answer)
    def query(payload: Question) -> Answer:
        try:
            hits = retriever.retrieve(payload.question)
            answer = llm.answer(payload.question, hits) if hits else NO_SOURCES
        except OpenAIError as error:
            logging.error("OpenAI request failed (%s)", type(error).__name__)
            raise HTTPException(status_code=502, detail="The model provider request failed.") from error
        sources = [
            Source(citation=index, source=hit.source, location=hit.location, text=hit.text, score=hit.score)
            for index, hit in enumerate(hits, 1)
        ]
        return Answer(answer=answer, sources=sources)

    return app
