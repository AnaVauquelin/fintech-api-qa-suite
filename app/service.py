from typing import Dict, List, Optional
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="FinTech VAT & Payment Gateway Mock")

VAT_RATES = {
    "NL": 0.21,
    "DE": 0.19,
    "ES": 0.21,
    "PL": 0.23,
}

PROCESSED_KEYS: Dict[str, dict] = {}
TRANSACTIONS: List[dict] = []


class InvoiceRequest(BaseModel):
    tenant_id: str = Field(..., min_length=3)
    country_code: str = Field(..., min_length=2, max_length=2)
    net_amount: float = Field(..., gt=0)
    currency: str = Field(default="EUR", pattern="^(EUR|USD|GBP)$")
    reverse_charge: bool = False


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/invoices/calculate")
def create_invoice(
    payload: InvoiceRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
):
    if not x_tenant_id or x_tenant_id != payload.tenant_id:
        raise HTTPException(status_code=403, detail="Tenant isolation violation")

    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Missing Idempotency-Key header")

    cache_key = f"{x_tenant_id}:{idempotency_key}"
    if cache_key in PROCESSED_KEYS:
        cached = PROCESSED_KEYS[cache_key].copy()
        cached["idempotent_replay"] = True
        return cached

    country = payload.country_code.upper()
    if country not in VAT_RATES:
        raise HTTPException(status_code=422, detail=f"Unsupported jurisdiction: {country}")

    vat_rate = 0.0 if payload.reverse_charge else VAT_RATES[country]
    vat_amount = round(payload.net_amount * vat_rate, 2)
    gross_amount = round(payload.net_amount + vat_amount, 2)

    record = {
        "invoice_id": f"INV-{len(TRANSACTIONS) + 1001}",
        "tenant_id": payload.tenant_id,
        "country_code": country,
        "net_amount": payload.net_amount,
        "vat_rate": vat_rate,
        "vat_amount": vat_amount,
        "gross_amount": gross_amount,
        "currency": payload.currency,
        "idempotent_replay": False,
    }
    PROCESSED_KEYS[cache_key] = record
    TRANSACTIONS.append(record)
    return record


@app.get("/v1/invoices")
def list_invoices(x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID")):
    if not x_tenant_id:
        raise HTTPException(status_code=401, detail="Unauthorized tenant")
    return [tx for tx in TRANSACTIONS if tx["tenant_id"] == x_tenant_id]
