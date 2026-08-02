"""Region-specific transaction costs.

Costs are the difference between a strategy that looks profitable and one that
is. They are modelled per venue because the *structure* differs, not just the
rate: India charges securities transaction tax on both sides for delivery but
sell-side only for intraday, and levies GST on the brokerage itself; the US
charges regulatory fees on sells only; China charges stamp duty on sells only.
A single "10 bps" assumption gets all three wrong.

Every rate below is a **default that will drift**. Rates are exposed as dataclass
fields with the schedule date noted so they can be updated without touching
logic. Do not treat them as current — verify against the exchange's published
schedule before relying on results.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..core.instrument import Instrument
from ..core.money import to_decimal
from .orders import Side


@dataclass(frozen=True)
class CostBreakdown:
    """Itemised cost of a single execution, in the instrument's currency."""

    commission: Decimal = Decimal("0")
    securities_tax: Decimal = Decimal("0")     # STT (IN), stamp duty (CN/HK)
    exchange_fee: Decimal = Decimal("0")
    regulatory_fee: Decimal = Decimal("0")     # SEBI (IN), SEC/FINRA (US)
    stamp_duty: Decimal = Decimal("0")
    gst: Decimal = Decimal("0")

    @property
    def taxes(self) -> Decimal:
        return self.securities_tax + self.stamp_duty + self.gst

    @property
    def fees(self) -> Decimal:
        return self.exchange_fee + self.regulatory_fee

    @property
    def total(self) -> Decimal:
        return self.commission + self.taxes + self.fees

    def __add__(self, other: CostBreakdown) -> CostBreakdown:
        return CostBreakdown(
            commission=self.commission + other.commission,
            securities_tax=self.securities_tax + other.securities_tax,
            exchange_fee=self.exchange_fee + other.exchange_fee,
            regulatory_fee=self.regulatory_fee + other.regulatory_fee,
            stamp_duty=self.stamp_duty + other.stamp_duty,
            gst=self.gst + other.gst,
        )


class CostModel:
    """Base cost model. Subclasses implement :meth:`compute`."""

    region: str = "??"

    def compute(
        self,
        instrument: Instrument,
        side: Side,
        quantity: Decimal,
        price: Decimal,
        *,
        intraday: bool = False,
    ) -> CostBreakdown:  # pragma: no cover - abstract
        raise NotImplementedError

    @staticmethod
    def turnover(instrument: Instrument, quantity: Decimal, price: Decimal) -> Decimal:
        return instrument.contract_value(to_decimal(price), to_decimal(quantity))


@dataclass(frozen=True)
class IndiaCostModel(CostModel):
    """NSE/BSE cash equity costs (schedule as published for FY2024-25).

    Notable structure: STT is charged on **both** legs for delivery trades but
    only the sell leg for intraday; stamp duty is **buy-side only**; and 18% GST
    applies to brokerage plus exchange and SEBI charges, not to STT or stamp
    duty.
    """

    region: str = "IN"
    brokerage_rate: Decimal = Decimal("0.0003")        # 0.03%
    brokerage_cap: Decimal = Decimal("20")             # capped at Rs 20/order
    delivery_brokerage_rate: Decimal = Decimal("0")    # free at discount brokers
    stt_delivery: Decimal = Decimal("0.001")           # 0.1%, both legs
    stt_intraday_sell: Decimal = Decimal("0.00025")    # 0.025%, sell leg only
    exchange_txn_rate: Decimal = Decimal("0.0000297")  # NSE 0.00297%
    sebi_rate: Decimal = Decimal("0.000001")           # Rs 10 per crore
    stamp_delivery_buy: Decimal = Decimal("0.00015")   # 0.015%, buy only
    stamp_intraday_buy: Decimal = Decimal("0.00003")   # 0.003%, buy only
    gst_rate: Decimal = Decimal("0.18")

    def compute(
        self,
        instrument: Instrument,
        side: Side,
        quantity: Decimal,
        price: Decimal,
        *,
        intraday: bool = False,
    ) -> CostBreakdown:
        turnover = self.turnover(instrument, quantity, price)

        if intraday:
            brokerage = min(turnover * self.brokerage_rate, self.brokerage_cap)
            stt = turnover * self.stt_intraday_sell if side is Side.SELL else Decimal("0")
            stamp = turnover * self.stamp_intraday_buy if side is Side.BUY else Decimal("0")
        else:
            brokerage = min(
                turnover * self.delivery_brokerage_rate, self.brokerage_cap
            ) if self.delivery_brokerage_rate > 0 else Decimal("0")
            stt = turnover * self.stt_delivery
            stamp = turnover * self.stamp_delivery_buy if side is Side.BUY else Decimal("0")

        exchange = turnover * self.exchange_txn_rate
        sebi = turnover * self.sebi_rate
        gst = (brokerage + exchange + sebi) * self.gst_rate

        return CostBreakdown(
            commission=brokerage,
            securities_tax=stt,
            exchange_fee=exchange,
            regulatory_fee=sebi,
            stamp_duty=stamp,
            gst=gst,
        )


@dataclass(frozen=True)
class USCostModel(CostModel):
    """US cash equity costs.

    Commission defaults to zero (retail norm since 2019). The residual costs are
    regulatory and **sell-side only**: the SEC Section 31 fee and the FINRA
    Trading Activity Fee. The SEC rate is reset by the Commission at least
    annually — the default here is the FY2024 rate of $27.80 per $1,000,000.
    """

    region: str = "US"
    commission_per_share: Decimal = Decimal("0")
    commission_minimum: Decimal = Decimal("0")
    sec_fee_rate: Decimal = Decimal("0.0000278")       # sell side only
    finra_taf_per_share: Decimal = Decimal("0.000166")  # sell side only
    finra_taf_cap: Decimal = Decimal("8.30")

    def compute(
        self,
        instrument: Instrument,
        side: Side,
        quantity: Decimal,
        price: Decimal,
        *,
        intraday: bool = False,
    ) -> CostBreakdown:
        qty = to_decimal(quantity)
        turnover = self.turnover(instrument, qty, price)

        commission = qty * self.commission_per_share
        if self.commission_minimum > 0:
            commission = max(commission, self.commission_minimum)

        if side is Side.SELL:
            sec = turnover * self.sec_fee_rate
            taf = min(qty * self.finra_taf_per_share, self.finra_taf_cap)
        else:
            sec = Decimal("0")
            taf = Decimal("0")

        return CostBreakdown(
            commission=commission,
            regulatory_fee=sec + taf,
        )


@dataclass(frozen=True)
class ChinaCostModel(CostModel):
    """Mainland China A-share costs (SSE/SZSE).

    Stamp duty is **sell-side only** and was halved to 0.05% in August 2023.
    Brokerage carries a per-order minimum of CNY 5, which makes small orders
    disproportionately expensive — the sizing layer respects this via the
    minimum-order-value check.
    """

    region: str = "CN"
    commission_rate: Decimal = Decimal("0.00025")   # 0.025%
    commission_minimum: Decimal = Decimal("5")      # CNY 5 per order
    stamp_duty_sell: Decimal = Decimal("0.0005")    # 0.05%, sell only
    transfer_fee_rate: Decimal = Decimal("0.00001")  # 0.001%, both sides
    handling_fee_rate: Decimal = Decimal("0.0000341")

    def compute(
        self,
        instrument: Instrument,
        side: Side,
        quantity: Decimal,
        price: Decimal,
        *,
        intraday: bool = False,
    ) -> CostBreakdown:
        turnover = self.turnover(instrument, quantity, price)
        commission = max(turnover * self.commission_rate, self.commission_minimum)
        stamp = turnover * self.stamp_duty_sell if side is Side.SELL else Decimal("0")
        transfer = turnover * self.transfer_fee_rate
        handling = turnover * self.handling_fee_rate
        return CostBreakdown(
            commission=commission,
            stamp_duty=stamp,
            exchange_fee=handling,
            regulatory_fee=transfer,
        )


@dataclass(frozen=True)
class RussiaCostModel(CostModel):
    """MOEX equity costs: broker commission plus exchange fee, both sides."""

    region: str = "RU"
    commission_rate: Decimal = Decimal("0.0005")     # 0.05%
    commission_minimum: Decimal = Decimal("0")
    exchange_fee_rate: Decimal = Decimal("0.0001")   # 0.01%

    def compute(
        self,
        instrument: Instrument,
        side: Side,
        quantity: Decimal,
        price: Decimal,
        *,
        intraday: bool = False,
    ) -> CostBreakdown:
        turnover = self.turnover(instrument, quantity, price)
        commission = max(turnover * self.commission_rate, self.commission_minimum)
        return CostBreakdown(
            commission=commission,
            exchange_fee=turnover * self.exchange_fee_rate,
        )


@dataclass(frozen=True)
class FlatBpsCostModel(CostModel):
    """Generic fallback: a flat basis-point charge on turnover, both sides."""

    region: str = "XX"
    rate_bps: Decimal = Decimal("10")
    minimum: Decimal = Decimal("0")

    def compute(
        self,
        instrument: Instrument,
        side: Side,
        quantity: Decimal,
        price: Decimal,
        *,
        intraday: bool = False,
    ) -> CostBreakdown:
        turnover = self.turnover(instrument, quantity, price)
        commission = max(turnover * self.rate_bps / Decimal("10000"), self.minimum)
        return CostBreakdown(commission=commission)


_COST_MODELS: dict[str, CostModel] = {
    "IN": IndiaCostModel(),
    "US": USCostModel(),
    "CN": ChinaCostModel(),
    "RU": RussiaCostModel(),
    "HK": FlatBpsCostModel(region="HK", rate_bps=Decimal("15")),
}


def get_cost_model(region: str) -> CostModel:
    """Cost model for a region, falling back to a flat 10 bps for unknown venues."""
    return _COST_MODELS.get(region.upper(), FlatBpsCostModel(region=region.upper()))


def register_cost_model(region: str, model: CostModel) -> None:
    _COST_MODELS[region.upper()] = model


# ---------------------------------------------------------------------------
# Slippage
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SlippageModel:
    """Execution shortfall relative to the reference price.

    Two components, both of which push the fill *against* the trader:

    * a fixed half-spread in basis points, and
    * a square-root market-impact term in the participation rate
      ``order_qty / average_daily_volume``.

    The square-root form is the standard empirical shape (Almgren et al.); the
    coefficient is a tunable default, not a calibrated constant.
    """

    half_spread_bps: Decimal = Decimal("2")
    impact_coefficient: Decimal = Decimal("10")   # bps at 100% participation
    max_slippage_bps: Decimal = Decimal("200")    # safety clamp

    def slippage_bps(self, quantity: Decimal, average_volume: Decimal) -> Decimal:
        """Total adverse move in basis points for an order of ``quantity``."""
        bps = self.half_spread_bps
        avg = to_decimal(average_volume)
        if avg > 0:
            participation = to_decimal(quantity) / avg
            if participation > 0:
                # sqrt via Decimal to keep the whole path exact-ish and float-free.
                bps += self.impact_coefficient * participation.sqrt()
        return min(bps, self.max_slippage_bps)

    def apply(
        self,
        reference_price: Decimal,
        side: Side,
        quantity: Decimal,
        average_volume: Decimal,
    ) -> Decimal:
        """Fill price after slippage: buys pay up, sells receive less."""
        price = to_decimal(reference_price)
        bps = self.slippage_bps(quantity, average_volume)
        adjustment = price * bps / Decimal("10000")
        return price + adjustment * side.sign


ZERO_SLIPPAGE = SlippageModel(
    half_spread_bps=Decimal("0"), impact_coefficient=Decimal("0")
)
