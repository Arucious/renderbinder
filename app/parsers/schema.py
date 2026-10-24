"""The persisted prompt contract shared by parsers, search, and embeddings."""

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat


class PromptDocument(BaseModel):
    model_config = ConfigDict(extra="allow")
    key: str = Field(min_length=1, max_length=500)
    scope: str = Field(pattern=r"^[a-z][a-z0-9_-]*$", max_length=40)
    text: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=200)
    start: FiniteFloat | None = Field(default=None, ge=0)
    end: FiniteFloat | None = Field(default=None, ge=0)
    provenance: dict = Field(default_factory=dict)
