"""Select the server-side vision model used by room review."""
from dataclasses import dataclass, field

from app.sources.config import secret

PROVIDERS = {
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "claude-sonnet-4-6"),
    "openai": ("OPENAI_API_KEY", "OPENAI_MODEL", "gpt-5.6-terra"),
}


@dataclass(frozen=True)
class ReviewModel:
    provider: str
    name: str
    api_key: str = field(repr=False)

    @property
    def identifier(self):
        return f"{self.provider}:{self.name}"

    def chat(self, *, max_tokens, timeout=30, max_retries=1):
        options = dict(model=self.name, api_key=self.api_key, max_tokens=max_tokens,
                       timeout=timeout, max_retries=max_retries)
        if self.provider == "openai":
            from langchain_openai import ChatOpenAI

            # Responses can pass images returned by the agent's panorama tool.
            return ChatOpenAI(**options, use_responses_api=True, store=False)
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(**options)

    def structured(self, schema, *, max_tokens):
        model = self.chat(max_tokens=max_tokens)
        if self.provider == "openai":
            return model.with_structured_output(schema, method="function_calling")
        return model.with_structured_output(schema)


def resolve_review_model():
    selected = secret("REVIEW_MODEL", required=False)
    if selected:
        provider, _, name = selected.partition(":")
        if provider not in PROVIDERS or not name or ":" in name or any(c.isspace() for c in name):
            return None, "Set REVIEW_MODEL to openai:<model> or anthropic:<model>."
        key = PROVIDERS[provider][0]
        api_key = secret(key, required=False)
        if not api_key:
            return None, f"Set {key} for the selected review model."
        return ReviewModel(provider, name, api_key), None

    for provider, (key, model_var, default) in PROVIDERS.items():
        api_key = secret(key, required=False)
        if api_key:
            return ReviewModel(provider, secret(model_var, required=False) or default, api_key), None
    return None, "Set OPENAI_API_KEY or ANTHROPIC_API_KEY to enable model review."
