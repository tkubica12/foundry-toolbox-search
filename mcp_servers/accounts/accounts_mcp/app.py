from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("AccountsMCP", host="0.0.0.0", stateless_http=True)


def account_marker(customer_id: str) -> str:
    return f"ACCT-DEMO-{customer_id.upper()}"


@mcp.tool()
async def get_account_balance(account_id: str, as_of_date: str) -> dict:
    """Return mocked current account balance."""
    return {"account_id": account_id, "as_of_date": as_of_date, "available_balance": 8420.55, "currency": "EUR"}


@mcp.tool()
async def list_recent_transactions(account_id: str, days: int) -> dict:
    """List mocked recent transactions."""
    return {"account_id": account_id, "days": days, "transactions": [{"merchant": "Nordic Utilities", "amount": -94.2}, {"merchant": "Payroll", "amount": 4200.0}]}


@mcp.tool()
async def categorize_transaction(transaction_id: str, merchant_name: str, amount: float) -> dict:
    """Categorize a transaction."""
    category = "income" if amount > 0 else "bills" if "util" in merchant_name.lower() else "spend"
    return {"transaction_id": transaction_id, "category": category}


@mcp.tool()
async def detect_overdraft_risk(customer_id: str, account_id: str, projected_debits: float) -> dict:
    """Assess mocked overdraft risk."""
    risk = projected_debits > 8500
    return {"marker": account_marker(customer_id), "account_id": account_id, "overdraft_risk": risk}


@mcp.tool()
async def create_payment_instruction(account_id: str, beneficiary_iban: str, amount: float) -> dict:
    """Create a mocked payment instruction."""
    return {"account_id": account_id, "payment_id": "PAY-MOCK-001", "beneficiary_iban": beneficiary_iban, "amount": amount, "status": "queued"}


@mcp.tool()
async def validate_iban(iban: str, country_code: str) -> dict:
    """Validate an IBAN format at a mocked level."""
    return {"iban": iban, "country_code": country_code, "valid": iban.upper().startswith(country_code.upper())}


@mcp.tool()
async def get_direct_debits(account_id: str) -> dict:
    """Return mocked direct debits."""
    return {"account_id": account_id, "direct_debits": ["Mortgage", "Insurance", "Streaming"]}


@mcp.tool()
async def summarize_cash_flow(account_id: str, start_date: str, end_date: str) -> dict:
    """Summarize cash flow for a date range."""
    return {"account_id": account_id, "start_date": start_date, "end_date": end_date, "inflows": 6200.0, "outflows": 4150.25}


@mcp.tool()
async def flag_unusual_spend(account_id: str, category: str, amount: float) -> dict:
    """Flag unusually high spend."""
    return {"account_id": account_id, "category": category, "unusual": amount > 1000, "benchmark": 450.0}


@mcp.tool()
async def get_card_status(card_id: str) -> dict:
    """Return card status."""
    return {"card_id": card_id, "status": "active", "contactless_enabled": True}


@mcp.tool()
async def freeze_card(card_id: str, reason: str) -> dict:
    """Mock freezing a card."""
    return {"card_id": card_id, "status": "frozen", "reason": reason}


@mcp.tool()
async def calculate_monthly_fees(account_id: str, month: str) -> dict:
    """Calculate mocked monthly account fees."""
    return {"account_id": account_id, "month": month, "fees": 3.5, "currency": "EUR"}


@mcp.tool()
async def check_account_kyc_status(customer_id: str) -> dict:
    """Return KYC status for current account servicing."""
    return {"marker": account_marker(customer_id), "kyc_status": "current", "next_review": "2027-01-31"}


@mcp.tool()
async def get_savings_sweep_recommendation(customer_id: str, account_id: str, minimum_buffer: float) -> dict:
    """Recommend a sweep from current account to savings."""
    amount = max(0, 8420.55 - minimum_buffer)
    return {"marker": account_marker(customer_id), "account_id": account_id, "recommended_sweep": round(amount, 2)}


@mcp.tool()
async def estimate_foreign_exchange_fee(account_id: str, source_currency: str, target_currency: str, amount: float) -> dict:
    """Estimate FX fee for account transaction."""
    return {"account_id": account_id, "pair": f"{source_currency}/{target_currency}", "fee": round(amount * 0.006, 2)}


@mcp.tool()
async def get_standing_orders(account_id: str) -> dict:
    """List mocked standing orders."""
    return {"account_id": account_id, "standing_orders": [{"name": "Rent", "amount": 1600.0}, {"name": "Brokerage", "amount": 500.0}]}


@mcp.tool()
async def project_end_of_month_balance(account_id: str, expected_income: float, expected_spend: float) -> dict:
    """Project end-of-month balance."""
    return {"account_id": account_id, "projected_balance": round(8420.55 + expected_income - expected_spend, 2)}


@mcp.tool()
async def find_duplicate_charges(account_id: str, lookback_days: int) -> dict:
    """Find mocked duplicate charges."""
    return {"account_id": account_id, "lookback_days": lookback_days, "duplicates": [{"merchant": "Coffee Bar", "amount": 6.4}]}


@mcp.tool()
async def get_account_alert_preferences(customer_id: str, account_id: str) -> dict:
    """Return account alert preferences."""
    return {"marker": account_marker(customer_id), "account_id": account_id, "alerts": ["low_balance", "large_card_payment"]}


@mcp.tool()
async def recommend_fee_waiver(customer_id: str, account_id: str, relationship_years: int) -> dict:
    """Recommend whether to waive account fees."""
    return {"marker": account_marker(customer_id), "account_id": account_id, "waive_fee": relationship_years >= 3}


def add_mock_account_tool(name: str, description: str) -> None:
    async def tool(customer_id: str, account_id: str, amount: float = 1000.0) -> dict:
        return {
            "marker": account_marker(customer_id),
            "tool": name,
            "account_id": account_id,
            "amount": amount,
            "status": "mocked",
            "currency": "EUR",
        }

    mcp.add_tool(tool, name=name, description=description)


for tool_name, tool_description in [
    ("review_payment_limit", "Review payment limit for a current account."),
    ("increase_transfer_limit", "Mock increasing transfer limit."),
    ("assess_salary_pattern", "Assess salary pattern in current account transactions."),
    ("detect_subscription_spend", "Detect recurring subscription spend."),
    ("summarize_merchant_spend", "Summarize spend by merchant."),
    ("review_chargeback_case", "Review card chargeback case."),
    ("create_card_replacement", "Create mocked card replacement order."),
    ("estimate_cash_withdrawal_fee", "Estimate cash withdrawal fee."),
    ("review_joint_account_access", "Review joint account access status."),
    ("check_sepa_reachability", "Check SEPA reachability for a beneficiary."),
    ("validate_payment_reference", "Validate payment reference format."),
    ("assess_fraud_alert", "Assess mocked fraud alert."),
    ("review_account_closure_readiness", "Review account closure readiness."),
    ("calculate_interest_on_positive_balance", "Calculate interest on positive balance."),
    ("recommend_budget_category_limit", "Recommend budget category limit."),
    ("detect_income_interruption", "Detect income interruption risk."),
    ("review_cash_deposit_pattern", "Review cash deposit pattern."),
    ("estimate_international_transfer_time", "Estimate international transfer time."),
    ("check_beneficiary_risk", "Check beneficiary risk score."),
    ("review_power_of_attorney", "Review power of attorney on account."),
    ("summarize_monthly_statement", "Summarize monthly current account statement."),
    ("detect_round_number_transfers", "Detect round-number transfer pattern."),
    ("review_account_package_fit", "Review current account package fit."),
    ("estimate_atm_rebate", "Estimate ATM fee rebate."),
    ("check_dormancy_risk", "Check account dormancy risk."),
    ("review_negative_balance_history", "Review negative balance history."),
    ("recommend_alert_threshold", "Recommend balance alert threshold."),
    ("assess_travel_notice_need", "Assess whether travel notice is needed."),
    ("review_cashback_eligibility", "Review cashback eligibility."),
    ("summarize_account_health", "Summarize mocked account health."),
]:
    add_mock_account_tool(tool_name, tool_description)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(mcp.session_manager.run())
        yield


app = FastAPI(title="Accounts MCP", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "healthy", "service": "accounts"})


app.mount("/", mcp.streamable_http_app())
