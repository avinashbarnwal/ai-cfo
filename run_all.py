"""Run every POC agent on synthetic data and print a one-line scorecard.

    python run_all.py              # all agents
    python run_all.py --verbose    # full output per agent
    AGENT_OFFLINE=1 python run_all.py   # skip Claude calls
"""
import importlib
import json
import sys

AGENTS = {
    "Order to Cash": [
        ("order_to_cash.collections.agent", "CollectionsAgent"),
        ("order_to_cash.cash_application.agent", "CashApplicationAgent"),
        ("order_to_cash.deductions.agent", "DeductionsAgent"),
        ("order_to_cash.credit.agent", "CreditAgent"),
        ("order_to_cash.einvoicing.agent", "EInvoicingAgent"),
    ],
    "Accounts Payable": [
        ("accounts_payable.ap_automation.agent", "APAutomationAgent"),
        ("accounts_payable.supplier_portal.agent", "SupplierPortalAgent"),
        ("accounts_payable.vendor_payments.agent", "VendorPaymentsAgent"),
    ],
    "Close & Reconciliation": [
        ("close_reconciliation.financial_close.agent", "FinancialCloseAgent"),
        ("close_reconciliation.balance_sheet_reconciliation.agent", "BalanceSheetReconAgent"),
        ("close_reconciliation.daily_revenue_reconciliation.agent", "DailyRevenueReconAgent"),
        ("close_reconciliation.intercompany.agent", "IntercompanyAgent"),
    ],
    "Consolidation & Reporting": [
        ("consolidation_reporting.financial_consolidation.agent", "FinancialConsolidationAgent"),
        ("consolidation_reporting.financial_reporting.agent", "FinancialReportingAgent"),
    ],
    "Treasury & Risk": [
        ("treasury_risk.cash_management.agent", "CashManagementAgent"),
        ("treasury_risk.cash_forecasting.agent", "CashForecastingAgent"),
        ("treasury_risk.treasury_payments.agent", "TreasuryPaymentsAgent"),
    ],
    "B2B Payments": [
        ("b2b_payments.payment_gateway.agent", "PaymentGatewayAgent"),
        ("b2b_payments.surcharge_management.agent", "SurchargeAgent"),
        ("b2b_payments.interchange_fee_optimizer.agent", "InterchangeOptimizerAgent"),
    ],
}


def main(verbose: bool = False) -> None:
    for cat, items in AGENTS.items():
        print(f"\n## {cat}")
        for mod, cls in items:
            agent = getattr(importlib.import_module(mod), cls)()
            res = agent.run(agent.sample_data())
            if verbose:
                res.show()
            else:
                print(f"  - {res.agent}: {json.dumps(res.summary, default=str)[:160]}")


if __name__ == "__main__":
    main("--verbose" in sys.argv)
