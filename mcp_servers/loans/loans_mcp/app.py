from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("LoansMCP", host="0.0.0.0", stateless_http=True)


def loan_marker(customer_id: str) -> str:
    return f"LOAN-DEMO-{customer_id.upper()}"


@mcp.tool()
async def get_mortgage_affordability(customer_id: str, annual_income: float, monthly_debt: float) -> dict:
    """Estimate mortgage affordability for a customer.

    Args:
        customer_id: Customer identifier.
        annual_income: Gross yearly income.
        monthly_debt: Existing monthly debt payments.
    """
    max_payment = round((annual_income / 12 * 0.36) - monthly_debt, 2)
    return {"marker": loan_marker(customer_id), "max_monthly_payment": max(max_payment, 0), "currency": "EUR"}


@mcp.tool()
async def quote_personal_loan(customer_id: str, amount: float, term_months: int) -> dict:
    """Quote a mocked personal loan rate and payment."""
    apr = 6.4 if amount < 25000 else 7.1
    payment = round((amount * (1 + apr / 100)) / term_months, 2)
    return {"marker": loan_marker(customer_id), "apr_percent": apr, "monthly_payment": payment}


@mcp.tool()
async def check_loan_eligibility(customer_id: str, product_type: str, credit_score: int) -> dict:
    """Check high-level eligibility for a loan product."""
    eligible = credit_score >= 680
    return {"marker": loan_marker(customer_id), "product_type": product_type, "eligible": eligible, "reason": "mock credit policy"}


@mcp.tool()
async def get_loan_balance(loan_id: str, as_of_date: str) -> dict:
    """Return current mocked balance for a loan."""
    return {"loan_id": loan_id, "as_of_date": as_of_date, "outstanding_balance": 184250.75, "currency": "EUR"}


@mcp.tool()
async def calculate_early_repayment_fee(loan_id: str, repayment_amount: float) -> dict:
    """Calculate a mocked early repayment fee."""
    return {"loan_id": loan_id, "fee": round(repayment_amount * 0.01, 2), "currency": "EUR"}


@mcp.tool()
async def summarize_repayment_schedule(loan_id: str, months: int) -> dict:
    """Summarize upcoming repayment schedule."""
    return {"loan_id": loan_id, "months": months, "monthly_payment": 1234.56, "next_due_date": "2026-07-01"}


@mcp.tool()
async def assess_refinance_savings(loan_id: str, new_apr_percent: float, remaining_months: int) -> dict:
    """Estimate savings from refinancing."""
    savings = round(max(0, (5.9 - new_apr_percent) * remaining_months * 42), 2)
    return {"loan_id": loan_id, "estimated_savings": savings, "currency": "EUR"}


@mcp.tool()
async def get_collateral_valuation(collateral_id: str, valuation_date: str) -> dict:
    """Return mocked collateral valuation."""
    return {"collateral_id": collateral_id, "valuation_date": valuation_date, "market_value": 310000, "currency": "EUR"}


@mcp.tool()
async def compute_ltv_ratio(loan_id: str, balance: float, collateral_value: float) -> dict:
    """Compute loan-to-value ratio."""
    ratio = round(balance / collateral_value * 100, 2) if collateral_value else 0
    return {"loan_id": loan_id, "ltv_percent": ratio}


@mcp.tool()
async def get_delinquency_status(loan_id: str) -> dict:
    """Return mocked delinquency status."""
    return {"loan_id": loan_id, "days_past_due": 0, "status": "current"}


@mcp.tool()
async def recommend_hardship_options(customer_id: str, loan_id: str, hardship_reason: str) -> dict:
    """Recommend hardship options for a borrower."""
    return {"marker": loan_marker(customer_id), "loan_id": loan_id, "options": ["payment holiday", "term extension"], "reason": hardship_reason}


@mcp.tool()
async def verify_income_document(customer_id: str, document_type: str, monthly_income: float) -> dict:
    """Mock verification of income evidence."""
    return {"marker": loan_marker(customer_id), "document_type": document_type, "verified_income": monthly_income, "confidence": "high"}


@mcp.tool()
async def estimate_debt_to_income(customer_id: str, annual_income: float, monthly_debt: float) -> dict:
    """Calculate debt-to-income ratio."""
    dti = round(monthly_debt / (annual_income / 12) * 100, 2) if annual_income else 0
    return {"marker": loan_marker(customer_id), "dti_percent": dti}


@mcp.tool()
async def get_rate_lock_status(application_id: str) -> dict:
    """Return mocked rate lock status for an application."""
    return {"application_id": application_id, "locked_rate_percent": 4.85, "expires_on": "2026-07-15"}


@mcp.tool()
async def create_loan_application(customer_id: str, product_type: str, requested_amount: float) -> dict:
    """Create a mocked loan application."""
    return {"marker": loan_marker(customer_id), "application_id": f"APP-{customer_id.upper()}-001", "product_type": product_type, "requested_amount": requested_amount}


@mcp.tool()
async def get_application_status(application_id: str) -> dict:
    """Return mocked loan application status."""
    return {"application_id": application_id, "status": "conditional_approval", "pending_items": ["income verification"]}


@mcp.tool()
async def calculate_payoff_quote(loan_id: str, payoff_date: str) -> dict:
    """Calculate mocked loan payoff quote."""
    return {"loan_id": loan_id, "payoff_date": payoff_date, "payoff_amount": 185004.12, "currency": "EUR"}


@mcp.tool()
async def compare_fixed_variable_rates(customer_id: str, amount: float, term_months: int) -> dict:
    """Compare mocked fixed and variable loan options."""
    return {"marker": loan_marker(customer_id), "fixed_apr": 4.95, "variable_start_apr": 4.35, "term_months": term_months, "amount": amount}


@mcp.tool()
async def list_required_loan_documents(product_type: str, customer_segment: str) -> dict:
    """List required documents for a loan product."""
    return {"product_type": product_type, "customer_segment": customer_segment, "documents": ["ID", "income proof", "bank statements", "collateral details"]}


@mcp.tool()
async def simulate_interest_rate_shock(loan_id: str, shock_bps: int) -> dict:
    """Simulate payment impact of an interest-rate shock."""
    delta = round(shock_bps / 100 * 18.5, 2)
    return {"loan_id": loan_id, "shock_bps": shock_bps, "monthly_payment_increase": delta, "currency": "EUR"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(mcp.session_manager.run())
        yield


app = FastAPI(title="Loans MCP", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "healthy", "service": "loans"})


app.mount("/", mcp.streamable_http_app())
