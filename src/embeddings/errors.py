from openai import OpenAIError, RateLimitError


def embedding_error_message(error: OpenAIError) -> str:
    if not isinstance(error, RateLimitError):
        return f"Embedding request failed ({type(error).__name__})."
    if error.code == "credit_balance_exhausted":
        return "OpenAI reports no available prepaid API credits for this key's organization."
    if error.code in {"insufficient_quota", "usage_limit_exceeded", "organization_usage_limit_exceeded"}:
        return "OpenAI API quota is unavailable. Check API billing, credits, and usage limits."
    if error.code in {"organization_spend_limit_exceeded", "project_spend_limit_exceeded"}:
        return "An OpenAI API spend limit was reached. Check organization and project limits."
    if error.code in {"rate_limit_exceeded", "slow_down"}:
        return "OpenAI temporarily throttled embedding requests. Wait before retrying."
    return "OpenAI rejected the embedding request with HTTP 429. Check both API quota and rate limits."
