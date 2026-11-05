from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RedeemCouponRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_key: UUID
    purchase_amount: float = Field(gt=0, allow_inf_nan=False)


class BookExperienceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    people: int = Field(gt=0)
    request_key: UUID
