"""Pod B internal intermediate representation (NOT a shared contract).
Both extractors (rules, LLM) produce an `Extraction`; resolver.py turns it into an OrderDraft."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Mention(BaseModel):
    raw: str                                   # transcript span
    product_text: str                          # what the customer called it
    sku_hint: Optional[str] = None             # LLM may propose a SKU; resolver re-validates
    quantity: Optional[float] = None
    unit: Optional[str] = None                 # spoken unit (Unit value) or None = count
    action: Literal["add", "set", "remove"] = "add"
    increment: bool = False                    # "rajoute 2 ... en plus" on top of history
    conditional: Optional[str] = None


class Extraction(BaseModel):
    mentions: list[Mention] = Field(default_factory=list)
    history_ref: Optional[str] = None          # "last" | "lundi".."dimanche"
    price_questions: list[str] = Field(default_factory=list)
    delivery_hint: Optional[str] = None        # "demain", "jeudi"...
    extractor: Literal["llm", "rules"] = "rules"
