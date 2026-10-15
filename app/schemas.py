"""Request and response models for the leads API."""
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

Status = Literal["new", "contacted", "qualified", "won", "lost"]

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _clean_email(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    v = v.strip()
    if v and not EMAIL_RE.match(v):
        raise ValueError("mail ID must look like name@domain.com")
    return v.lower()


def _clean_phone(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    v = v.strip()
    if v and len(re.sub(r"\D", "", v)) < 7:
        raise ValueError("phone number needs at least 7 digits")
    return v


class LeadBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    phone: str = Field("", max_length=30)
    email: str = Field("", max_length=254)
    address: str = Field("", max_length=500)
    status: Status = "new"
    source: str = Field("Website", max_length=60)

    @field_validator("name", "address", "source")
    @classmethod
    def strip_text(cls, v: str) -> str:
        return v.strip()

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return _clean_email(v)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str) -> str:
        return _clean_phone(v)


class LeadCreate(LeadBase):
    @model_validator(mode="after")
    def needs_contact(self):
        if not self.name:
            raise ValueError("customer name is required")
        if not self.phone and not self.email:
            raise ValueError("add a phone number or a mail ID")
        return self


class LeadUpdate(BaseModel):
    """Partial update: only the fields sent are changed."""
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    phone: Optional[str] = Field(None, max_length=30)
    email: Optional[str] = Field(None, max_length=254)
    address: Optional[str] = Field(None, max_length=500)
    status: Optional[Status] = None
    source: Optional[str] = Field(None, max_length=60)

    @field_validator("name", "address", "source")
    @classmethod
    def strip_text(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v is not None else v

    @field_validator("email")
    @classmethod
    def check_email(cls, v: Optional[str]) -> Optional[str]:
        return _clean_email(v)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: Optional[str]) -> Optional[str]:
        return _clean_phone(v)


class Lead(LeadBase):
    id: int
    created_at: str
    updated_at: str


class PipelineStats(BaseModel):
    total: int
    new: int = 0
    contacted: int = 0
    qualified: int = 0
    won: int = 0
    lost: int = 0
