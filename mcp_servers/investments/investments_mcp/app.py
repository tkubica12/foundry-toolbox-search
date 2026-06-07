from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("InvestmentsMCP", host="0.0.0.0", stateless_http=True)


def investment_marker(customer_id: str) -> str:
    return f"INV-DEMO-{customer_id.upper()}"


@mcp.tool()
async def get_portfolio_summary(customer_id: str, portfolio_id: str) -> dict:
    """Return mocked portfolio summary."""
    return {"marker": investment_marker(customer_id), "portfolio_id": portfolio_id, "market_value": 248500.0, "currency": "EUR"}


@mcp.tool()
async def calculate_asset_allocation(portfolio_id: str) -> dict:
    """Calculate mocked asset allocation."""
    return {"portfolio_id": portfolio_id, "allocation": {"equity": 62, "fixed_income": 25, "cash": 8, "alternatives": 5}}


@mcp.tool()
async def assess_risk_profile(customer_id: str, horizon_years: int, loss_tolerance_percent: float) -> dict:
    """Assess investor risk profile."""
    profile = "growth" if horizon_years >= 7 and loss_tolerance_percent >= 15 else "balanced"
    return {"marker": investment_marker(customer_id), "risk_profile": profile}


@mcp.tool()
async def recommend_rebalance_trades(portfolio_id: str, target_equity_percent: float) -> dict:
    """Recommend mocked rebalancing trades."""
    return {"portfolio_id": portfolio_id, "trades": [{"action": "sell", "asset": "global_equity_etf", "amount": 12000}, {"action": "buy", "asset": "euro_bond_fund", "amount": 12000}], "target_equity_percent": target_equity_percent}


@mcp.tool()
async def estimate_portfolio_var(portfolio_id: str, confidence_percent: float, horizon_days: int) -> dict:
    """Estimate mocked portfolio value at risk."""
    return {"portfolio_id": portfolio_id, "confidence_percent": confidence_percent, "horizon_days": horizon_days, "var_amount": 18750.0}


@mcp.tool()
async def get_security_quote(symbol: str, exchange: str) -> dict:
    """Return mocked security quote."""
    return {"symbol": symbol, "exchange": exchange, "price": 101.42, "currency": "EUR"}


@mcp.tool()
async def screen_sustainable_funds(region: str, minimum_esg_score: int, asset_class: str) -> dict:
    """Screen mocked sustainable funds."""
    return {"region": region, "asset_class": asset_class, "funds": [{"name": "Nordic ESG Leaders", "esg_score": max(minimum_esg_score, 82)}]}


@mcp.tool()
async def calculate_realized_gain(account_id: str, tax_year: int) -> dict:
    """Calculate mocked realized gains."""
    return {"account_id": account_id, "tax_year": tax_year, "realized_gain": 12450.35, "currency": "EUR"}


@mcp.tool()
async def check_product_suitability(customer_id: str, product_id: str, risk_rating: int) -> dict:
    """Check mocked investment product suitability."""
    suitable = risk_rating <= 4
    return {"marker": investment_marker(customer_id), "product_id": product_id, "suitable": suitable}


@mcp.tool()
async def get_dividend_calendar(portfolio_id: str, next_days: int) -> dict:
    """Return mocked upcoming dividends."""
    return {"portfolio_id": portfolio_id, "next_days": next_days, "dividends": [{"symbol": "EURODIV", "pay_date": "2026-07-12", "amount": 320.0}]}


@mcp.tool()
async def simulate_market_shock(portfolio_id: str, equity_shock_percent: float, rate_shock_bps: int) -> dict:
    """Simulate mocked market shock impact."""
    impact = round(248500 * (equity_shock_percent / 100) * 0.62 - rate_shock_bps * 18, 2)
    return {"portfolio_id": portfolio_id, "estimated_impact": impact, "currency": "EUR"}


@mcp.tool()
async def get_investment_policy_statement(customer_id: str) -> dict:
    """Return mocked investment policy statement summary."""
    return {"marker": investment_marker(customer_id), "objective": "long-term capital growth", "constraints": ["EU UCITS only", "max 70% equity"]}


@mcp.tool()
async def compare_fund_expenses(fund_a: str, fund_b: str, investment_amount: float) -> dict:
    """Compare mocked fund expenses."""
    return {"fund_a": fund_a, "fund_b": fund_b, "annual_cost_difference": round(investment_amount * 0.0025, 2)}


@mcp.tool()
async def calculate_expected_income(portfolio_id: str, next_months: int) -> dict:
    """Calculate mocked expected portfolio income."""
    return {"portfolio_id": portfolio_id, "next_months": next_months, "expected_income": round(next_months * 610.0, 2)}


@mcp.tool()
async def get_model_portfolio(model_name: str, risk_level: str) -> dict:
    """Return mocked model portfolio."""
    return {"model_name": model_name, "risk_level": risk_level, "allocation": {"equity": 55, "bonds": 35, "cash": 10}}


@mcp.tool()
async def assess_concentration_risk(portfolio_id: str, issuer_limit_percent: float) -> dict:
    """Assess mocked issuer concentration risk."""
    return {"portfolio_id": portfolio_id, "issuer_limit_percent": issuer_limit_percent, "breaches": [{"issuer": "Contoso Bank", "weight": 12.4}]}


@mcp.tool()
async def generate_trade_ticket(account_id: str, symbol: str, side: str, quantity: int) -> dict:
    """Generate a mocked trade ticket."""
    return {"account_id": account_id, "ticket_id": "TRD-MOCK-001", "symbol": symbol, "side": side, "quantity": quantity, "status": "created"}


@mcp.tool()
async def get_benchmark_performance(benchmark_id: str, period: str) -> dict:
    """Return mocked benchmark performance."""
    return {"benchmark_id": benchmark_id, "period": period, "return_percent": 7.8}


@mcp.tool()
async def evaluate_liquidity_needs(customer_id: str, required_cash: float, horizon_months: int) -> dict:
    """Evaluate mocked liquidity needs."""
    return {"marker": investment_marker(customer_id), "required_cash": required_cash, "horizon_months": horizon_months, "cash_buffer_ok": required_cash <= 25000}


@mcp.tool()
async def recommend_tax_loss_harvest(portfolio_id: str, minimum_loss: float) -> dict:
    """Recommend mocked tax-loss harvesting candidates."""
    return {"portfolio_id": portfolio_id, "candidates": [{"symbol": "EUROTECH", "unrealized_loss": max(minimum_loss, 1450.0)}]}


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(mcp.session_manager.run())
        yield


app = FastAPI(title="Investments MCP", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "healthy", "service": "investments"})


app.mount("/", mcp.streamable_http_app())
