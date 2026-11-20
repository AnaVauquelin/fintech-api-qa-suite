import os
import uuid

import pytest
import requests
from jsonschema import validate

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")

INVOICE_RESPONSE_SCHEMA = {
    "type": "object",
    "required": [
        "invoice_id",
        "tenant_id",
        "country_code",
        "net_amount",
        "vat_rate",
        "vat_amount",
        "gross_amount",
        "currency",
        "idempotent_replay",
    ],
    "properties": {
        "invoice_id": {"type": "string", "pattern": "^INV-[0-9]+$"},
        "tenant_id": {"type": "string"},
        "country_code": {"type": "string", "minLength": 2, "maxLength": 2},
        "net_amount": {"type": "number", "minimum": 0.01},
        "vat_rate": {"type": "number", "minimum": 0, "maximum": 1},
        "vat_amount": {"type": "number", "minimum": 0},
        "gross_amount": {"type": "number", "minimum": 0.01},
        "currency": {"type": "string", "enum": ["EUR", "USD", "GBP"]},
        "idempotent_replay": {"type": "boolean"},
    },
}


@pytest.mark.parametrize(
    "country,net,reverse_charge,expected_vat,expected_gross",
    [
        ("NL", 100.0, False, 21.0, 121.0),
        ("DE", 200.0, False, 38.0, 238.0),
        ("ES", 150.0, False, 31.5, 181.5),
        ("PL", 100.0, False, 23.0, 123.0),
        ("NL", 500.0, True, 0.0, 500.0),
    ],
)
def test_vat_calculation_and_contract_schema(
    country, net, reverse_charge, expected_vat, expected_gross
):
    tenant = "tenant-marosa-eu"
    headers = {
        "X-Tenant-ID": tenant,
        "Idempotency-Key": str(uuid.uuid4()),
    }
    payload = {
        "tenant_id": tenant,
        "country_code": country,
        "net_amount": net,
        "currency": "EUR",
        "reverse_charge": reverse_charge,
    }
    res = requests.post(f"{BASE_URL}/v1/invoices/calculate", json=payload, headers=headers, timeout=5)
    assert res.status_code == 200
    body = res.json()

    validate(instance=body, schema=INVOICE_RESPONSE_SCHEMA)
    assert body["vat_amount"] == expected_vat
    assert body["gross_amount"] == expected_gross


def test_idempotency_prevents_duplicate_charges():
    tenant = "tenant-adyen-nl"
    idem_key = str(uuid.uuid4())
    headers = {"X-Tenant-ID": tenant, "Idempotency-Key": idem_key}
    payload = {"tenant_id": tenant, "country_code": "NL", "net_amount": 1000.0, "currency": "EUR"}

    first = requests.post(f"{BASE_URL}/v1/invoices/calculate", json=payload, headers=headers, timeout=5)
    second = requests.post(f"{BASE_URL}/v1/invoices/calculate", json=payload, headers=headers, timeout=5)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["idempotent_replay"] is False
    assert second.json()["idempotent_replay"] is True
    assert first.json()["invoice_id"] == second.json()["invoice_id"]


def test_multi_tenant_data_isolation():
    tenant_a = f"tenant-a-{uuid.uuid4().hex[:6]}"
    tenant_b = f"tenant-b-{uuid.uuid4().hex[:6]}"

    requests.post(
        f"{BASE_URL}/v1/invoices/calculate",
        json={"tenant_id": tenant_a, "country_code": "DE", "net_amount": 300.0},
        headers={"X-Tenant-ID": tenant_a, "Idempotency-Key": str(uuid.uuid4())},
        timeout=5,
    )

    res_b = requests.get(f"{BASE_URL}/v1/invoices", headers={"X-Tenant-ID": tenant_b}, timeout=5)
    assert res_b.status_code == 200
    assert res_b.json() == []

    spoof = requests.post(
        f"{BASE_URL}/v1/invoices/calculate",
        json={"tenant_id": tenant_a, "country_code": "DE", "net_amount": 300.0},
        headers={"X-Tenant-ID": tenant_b, "Idempotency-Key": str(uuid.uuid4())},
        timeout=5,
    )
    assert spoof.status_code == 403


@pytest.mark.parametrize(
    "invalid_payload,expected_status",
    [
        ({"tenant_id": "tenant-1", "country_code": "XX", "net_amount": 100.0}, 422),
        ({"tenant_id": "tenant-1", "country_code": "NL", "net_amount": -50.0}, 422),
        ({"tenant_id": "tenant-1", "country_code": "NL", "net_amount": 100.0, "currency": "BTC"}, 422),
    ],
)
def test_negative_boundary_and_compliance_validation(invalid_payload, expected_status):
    headers = {
        "X-Tenant-ID": invalid_payload["tenant_id"],
        "Idempotency-Key": str(uuid.uuid4()),
    }
    res = requests.post(f"{BASE_URL}/v1/invoices/calculate", json=invalid_payload, headers=headers, timeout=5)
    assert res.status_code == expected_status
