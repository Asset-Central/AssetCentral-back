from typing import Literal

from pydantic import BaseModel


class FinancialProfileData(BaseModel):
    age: int | None = None
    monthly_income_ars: float | None = None
    savings_capacity_ars: float | None = None
    risk_aversion: Literal["bajo", "medio", "alto"] | None = None
    investment_horizon_months: int | None = None
    goals: list[str] | None = None
    currency_preference: Literal["ARS", "USD", "ambas"] | None = None


class UserFinancialProfile(BaseModel):
    profile: FinancialProfileData


class UpsertFinancialProfileRequest(BaseModel):
    profile: FinancialProfileData
