"""Minimal FollowTheMoney entity validators.

Workspace A is reviewing whether the upstream ``followthemoney`` package can be
imported (license must be compatible with both EUPL v1.2 and Apache 2.0). Until
that verdict ships at ``docs/dependency-decisions/followthemoney.md``, the
trust path uses this hand-rolled subset so we don't block on a license review
to validate entities flowing through the audit log.

Scope is deliberately narrow: structural shape checks for the five schemas the
v2 starter skills emit (Person, Company, Address, BankAccount, Payment). Any
other schema string is admitted but classified as ``Unknown`` — workspace A's
adapter can replace this module wholesale without changing the trust-path API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

KnownSchema = Literal[
    "Person",
    "Company",
    "Address",
    "BankAccount",
    "Payment",
]

UNKNOWN_SCHEMA = "Unknown"

# Conservative property allowlists per known schema. Drawn from the FtM
# upstream model; intentionally a subset, not the full inheritance closure.
# Workspace A's full adapter will replace this. Adding a property here is
# cheap; removing one breaks validators for already-emitted entities, so
# treat this as append-mostly until workspace A lands.
_KNOWN_PROPERTIES: dict[str, frozenset[str]] = {
    "Person": frozenset(
        {
            "name",
            "alias",
            "firstName",
            "lastName",
            "fatherName",
            "motherName",
            "birthDate",
            "birthPlace",
            "deathDate",
            "nationality",
            "gender",
            "idNumber",
            "passportNumber",
            "taxNumber",
            "country",
            "address",
            "phone",
            "email",
            "title",
            "position",
            "summary",
        }
    ),
    "Company": frozenset(
        {
            "name",
            "alias",
            "jurisdiction",
            "registrationNumber",
            "incorporationDate",
            "dissolutionDate",
            "address",
            "country",
            "sector",
            "classification",
            "phone",
            "email",
            "summary",
            "legalForm",
            "status",
            "vatCode",
        }
    ),
    "Address": frozenset(
        {
            "full",
            "street",
            "street2",
            "city",
            "region",
            "postalCode",
            "country",
            "latitude",
            "longitude",
            "summary",
        }
    ),
    "BankAccount": frozenset(
        {
            "accountNumber",
            "bankName",
            "bic",
            "iban",
            "accountType",
            "currency",
            "holder",
            "summary",
        }
    ),
    "Payment": frozenset(
        {
            "amount",
            "amountUsd",
            "amountEur",
            "currency",
            "date",
            "payer",
            "beneficiary",
            "payerAccount",
            "beneficiaryAccount",
            "purpose",
            "transactionNumber",
            "summary",
        }
    ),
}


class ValidatedEntity(BaseModel):
    """An FtM entity that has cleared structural validation.

    ``schema_kind`` is the recognised schema name or ``"Unknown"``;
    ``raw_schema`` preserves the string the caller passed so audits can record
    what was claimed even when we don't recognise it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    schema_kind: str = Field(min_length=1)
    raw_schema: str = Field(min_length=1)
    properties: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class FtMValidationError:
    error: str
    detail: str


def validate_entity(entity: Any) -> ValidatedEntity | FtMValidationError:
    if not isinstance(entity, dict):
        return FtMValidationError(error="not_a_dict", detail=f"got {type(entity).__name__}")

    raw_id = entity.get("id")
    if not isinstance(raw_id, str) or not raw_id:
        return FtMValidationError(error="bad_id", detail="id must be a non-empty string")

    raw_schema = entity.get("schema")
    if not isinstance(raw_schema, str) or not raw_schema:
        return FtMValidationError(
            error="bad_schema", detail="schema must be a non-empty string"
        )

    raw_props = entity.get("properties", {})
    if not isinstance(raw_props, dict):
        return FtMValidationError(
            error="bad_properties", detail="properties must be a dict"
        )

    validated_props: dict[str, tuple[str, ...]] = {}
    for prop_name, prop_values in raw_props.items():
        if not isinstance(prop_name, str) or not prop_name:
            return FtMValidationError(
                error="bad_property_name",
                detail=f"property names must be non-empty strings; got {prop_name!r}",
            )
        if not isinstance(prop_values, list):
            return FtMValidationError(
                error="bad_property_values",
                detail=f"property '{prop_name}' must be a list; got {type(prop_values).__name__}",
            )
        if not prop_values:
            return FtMValidationError(
                error="empty_property_values",
                detail=f"property '{prop_name}' has no values",
            )
        coerced: list[str] = []
        for value in prop_values:
            if not isinstance(value, str) or not value:
                return FtMValidationError(
                    error="bad_property_value",
                    detail=(
                        f"property '{prop_name}' values must be non-empty strings; "
                        f"got {value!r}"
                    ),
                )
            coerced.append(value)
        validated_props[prop_name] = tuple(coerced)

    if raw_schema in _KNOWN_PROPERTIES:
        allowed = _KNOWN_PROPERTIES[raw_schema]
        unknown_props = sorted(p for p in validated_props if p not in allowed)
        if unknown_props:
            return FtMValidationError(
                error="unknown_property_for_schema",
                detail=f"schema '{raw_schema}' rejects properties: {unknown_props}",
            )
        schema_kind: str = raw_schema
    else:
        schema_kind = UNKNOWN_SCHEMA

    return ValidatedEntity(
        id=raw_id,
        schema_kind=schema_kind,
        raw_schema=raw_schema,
        properties=validated_props,
    )
