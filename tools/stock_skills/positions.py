from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .markets import market_from_code


PORTFOLIO_SCHEMA_VERSION = "portfolio-positions-v1"


@dataclass(frozen=True)
class Position:
    code: str
    shares: float
    cost_basis: float
    currency: str
    theme: str
    trade_id: str | None = None
    current_stop: float | None = None
    leverage: float = 1.0

    def __post_init__(self) -> None:
        market_from_code(self.code)  # rejects malformed / unsupported codes
        if self.shares <= 0:
            raise ValueError(f"{self.code} share count must be positive")
        if self.cost_basis <= 0:
            raise ValueError(f"{self.code} cost basis must be positive")
        if not self.theme:
            raise ValueError(f"{self.code} requires an explicit theme")
        if self.leverage <= 0:
            raise ValueError(f"{self.code} leverage must be positive")
        if self.current_stop is not None and self.current_stop <= 0:
            raise ValueError(f"{self.code} stop must be positive when supplied")


@dataclass(frozen=True)
class HeatReport:
    """Book-level exposure. Positions without a stop are reported, never assumed safe."""

    nav: float
    equity_value: float
    cash_value: float
    portfolio_open_risk_pct: float
    theme_open_risk_pct: dict[str, float]
    theme_weight_pct: dict[str, float]
    position_weight_pct: dict[str, float]
    missing_prices: tuple[str, ...]
    missing_stops: tuple[str, ...]
    breached_stops: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.missing_prices and not self.missing_stops and not self.breached_stops


@dataclass(frozen=True)
class Portfolio:
    as_of: str
    base_currency: str
    fx_rates: dict[str, float]
    cash: dict[str, float]
    positions: tuple[Position, ...]
    schema_version: str = PORTFOLIO_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PORTFOLIO_SCHEMA_VERSION:
            raise ValueError(f"Unsupported portfolio schema: {self.schema_version!r}")
        codes = [position.code for position in self.positions]
        if len(codes) != len(set(codes)):
            raise ValueError("Portfolio contains duplicate position codes")
        for currency in {p.currency for p in self.positions} | set(self.cash):
            if currency not in self.fx_rates:
                raise ValueError(f"Missing FX rate for {currency}")
        if self.fx_rates.get(self.base_currency) != 1.0:
            raise ValueError(f"Base currency {self.base_currency} must have FX rate 1.0")

    def codes(self) -> tuple[str, ...]:
        return tuple(position.code for position in self.positions)

    def _base(self, amount: float, currency: str) -> float:
        return amount * self.fx_rates[currency]

    def cash_value(self) -> float:
        return sum(self._base(amount, currency) for currency, amount in self.cash.items())

    def heat(self, prices: Mapping[str, float]) -> HeatReport:
        """Compute NAV and open-risk heat from a live price map.

        Open risk is weight-times-loss-to-stop expressed against NAV, so it is directly
        comparable with the portfolio and theme limits.  A position whose price or stop is
        unavailable contributes nothing and is listed instead: an incomplete book must read
        as incomplete, never as a lower risk number.

        A price at or below the stop is a *breach*, not a zero-risk position: the exit should
        already have happened, and there is no defined loss-to-stop left to measure. Scoring it
        as 0 would quietly report the riskiest state in the book as the safest, so it is listed
        and makes the whole report incomplete until the position is exited or re-stopped.
        """

        missing_prices: list[str] = []
        missing_stops: list[str] = []
        breached_stops: list[str] = []
        equity = 0.0
        risk_by_theme: dict[str, float] = {}
        value_by_theme: dict[str, float] = {}
        value_by_code: dict[str, float] = {}
        total_risk = 0.0

        for position in self.positions:
            price = prices.get(position.code)
            if price is None or price <= 0:
                missing_prices.append(position.code)
                continue
            value = self._base(price * position.shares, position.currency)
            equity += value
            value_by_code[position.code] = value
            value_by_theme[position.theme] = value_by_theme.get(position.theme, 0.0) + value
            if position.current_stop is None:
                missing_stops.append(position.code)
                continue
            if price <= position.current_stop:
                breached_stops.append(position.code)
                continue
            risk = self._base(
                (price - position.current_stop) * position.shares, position.currency
            )
            total_risk += risk
            risk_by_theme[position.theme] = risk_by_theme.get(position.theme, 0.0) + risk

        cash = self.cash_value()
        nav = equity + cash
        if nav <= 0:
            raise ValueError("Portfolio NAV must be positive")

        pct = lambda value: round(value / nav * 100, 4)  # noqa: E731
        return HeatReport(
            nav=round(nav, 2),
            equity_value=round(equity, 2),
            cash_value=round(cash, 2),
            portfolio_open_risk_pct=pct(total_risk),
            theme_open_risk_pct={k: pct(v) for k, v in sorted(risk_by_theme.items())},
            theme_weight_pct={k: pct(v) for k, v in sorted(value_by_theme.items())},
            position_weight_pct={k: pct(v) for k, v in sorted(value_by_code.items())},
            missing_prices=tuple(sorted(missing_prices)),
            missing_stops=tuple(sorted(missing_stops)),
            breached_stops=tuple(sorted(breached_stops)),
        )

    def theme_of(self, code: str) -> str | None:
        for position in self.positions:
            if position.code == code:
                return position.theme
        return None


def portfolio_from_record(payload: dict[str, Any]) -> Portfolio:
    if not isinstance(payload, dict):
        raise ValueError("Portfolio payload must be an object")
    rows = payload.get("positions", [])
    if not isinstance(rows, list):
        raise ValueError("Portfolio positions must be a list")
    return Portfolio(
        as_of=str(payload["as_of"]),
        base_currency=str(payload.get("base_currency", "CNY")),
        fx_rates={str(k): float(v) for k, v in (payload.get("fx_rates") or {}).items()},
        cash={str(k): float(v) for k, v in (payload.get("cash") or {}).items()},
        positions=tuple(
            Position(
                code=str(row["code"]),
                shares=float(row["shares"]),
                cost_basis=float(row["cost_basis"]),
                currency=str(row["currency"]),
                theme=str(row["theme"]),
                trade_id=None if row.get("trade_id") in {None, ""} else str(row["trade_id"]),
                current_stop=(
                    None if row.get("current_stop") is None else float(row["current_stop"])
                ),
                leverage=float(row.get("leverage", 1.0)),
            )
            for row in rows
        ),
        schema_version=str(payload.get("schema_version", PORTFOLIO_SCHEMA_VERSION)),
    )


def load_portfolio(path: str | Path) -> Portfolio:
    return portfolio_from_record(json.loads(Path(path).read_text(encoding="utf-8")))
