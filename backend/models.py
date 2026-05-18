"""Pydantic schemas for the API."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Opportunity(BaseModel):
    """A single undervalued 0DTE option contract."""

    symbol: str = Field(..., description="Contract symbol, e.g. SPY250514C00525000")
    underlying: str
    underlying_price: float
    expiration: str = Field(..., description="ISO date, e.g. 2026-05-14")
    strike: float
    option_type: Literal["call", "put"]

    bid: float
    ask: float
    mid: float
    last: float
    volume: int
    open_interest: int

    market_iv: Optional[float] = Field(None, description="IV implied by the market mid (decimal)")
    reference_iv: float = Field(..., description="Reference IV used for fair value (decimal)")
    fair_value: float = Field(..., description="Black-Scholes fair value at reference IV")
    edge_abs: float = Field(..., description="fair_value − ask  (USD per share, x100 per contract)")
    edge_pct: float = Field(..., description="(fair_value − ask) / ask")

    delta: float
    gamma: float
    theta_per_day: float
    vega_per_volpt: float

    minutes_to_expiry: int
    score: float = Field(..., description="Composite score; higher = better candidate")


class TradePlan(BaseModel):
    """Exactly how to execute the trade for profit."""

    action: Literal["BUY_TO_OPEN"]
    contract_symbol: str
    side_human: str
    limit_price: float
    suggested_contracts: int
    cost_per_contract_usd: float
    total_cost_usd: float
    max_loss_usd: float
    breakeven_underlying_price: float
    target_exit_price: float = Field(..., description="Suggested take-profit limit price")
    target_profit_usd: float
    stop_loss_price: float
    stop_loss_usd: float
    rationale: str
    steps: list[str]


class Coaching(BaseModel):
    """Beginner-friendly coaching guidance for a specific opportunity."""

    action_summary: str = Field(..., description="e.g. 'Buy a CALL at $1.25'")
    why: str = Field(..., description="Plain-English reason this looks promising")
    entry_instruction: str = Field(..., description="Exactly how to enter the trade")
    expected_profit: str = Field(..., description="Profit target in human terms")
    max_risk: str = Field(..., description="Worst-case scenario")
    exit_plan: str = Field(..., description="When and how to close")
    watch_list: list[str] = Field(default_factory=list,
        description="Things to monitor while the trade is open")
    urgency: Literal["high", "medium", "low"] = Field(
        ..., description="How time-sensitive is this trade")
    confidence: Literal["strong", "moderate", "speculative"] = Field(
        ..., description="Overall confidence level")


class OpportunityWithPlan(BaseModel):
    opportunity: Opportunity
    plan: TradePlan
    coaching: Coaching


class RejectedContract(BaseModel):
    """A contract that was scanned but did not pass filters."""
    symbol: str
    underlying: str
    strike: float
    option_type: Literal["call", "put"]
    bid: float
    ask: float
    volume: int
    open_interest: int
    rejection_reason: str = Field(..., description="Short machine-readable reason code")
    rejection_detail: str = Field(..., description="Human-readable explanation")
    lesson: str = Field(..., description="Educational tip about why this matters")


class RejectionSummary(BaseModel):
    """Aggregate rejection stats with educational context."""
    total_contracts_scanned: int
    total_rejected: int
    total_passed: int
    by_reason: dict[str, int] = Field(default_factory=dict,
        description="Count of rejections per reason code")
    samples: list[RejectedContract] = Field(default_factory=list,
        description="Up to 5 sample rejections per reason for the UI")


class ScanResponse(BaseModel):
    generated_at: str
    risk_free_rate: float
    tickers_scanned: list[str]
    count: int
    results: list[OpportunityWithPlan]
    notes: list[str] = Field(default_factory=list)
    rejection_summary: Optional[RejectionSummary] = None
