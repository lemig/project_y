"""Structural validation tests for the FtM minimal-subset validator.

Covers the five v2 schemas (Person, Company, Address, BankAccount, Payment),
the Unknown stub for everything else, and the structural rejection paths
(non-dict input, missing id/schema, malformed properties).
"""

from __future__ import annotations

from typing import Any

import pytest

from verifier.ftm import (
    UNKNOWN_SCHEMA,
    FtMValidationError,
    ValidatedEntity,
    validate_entity,
)


def _person(**props: Any) -> dict[str, Any]:
    return {
        "id": "person-1",
        "schema": "Person",
        "properties": props,
    }


def _company(**props: Any) -> dict[str, Any]:
    return {
        "id": "company-1",
        "schema": "Company",
        "properties": props,
    }


class TestKnownSchemas:
    def test_valid_person(self) -> None:
        result = validate_entity(
            _person(name=["Marco Rossi"], nationality=["IT"], birthDate=["1972-04-11"])
        )
        assert isinstance(result, ValidatedEntity)
        assert result.schema_kind == "Person"
        assert result.raw_schema == "Person"
        assert result.properties == {
            "name": ("Marco Rossi",),
            "nationality": ("IT",),
            "birthDate": ("1972-04-11",),
        }

    def test_valid_company(self) -> None:
        result = validate_entity(
            _company(
                name=["ACME Holdings SA"],
                jurisdiction=["LU"],
                registrationNumber=["B-12345"],
            )
        )
        assert isinstance(result, ValidatedEntity)
        assert result.schema_kind == "Company"

    def test_valid_address(self) -> None:
        result = validate_entity(
            {
                "id": "addr-1",
                "schema": "Address",
                "properties": {
                    "full": ["Rue de la Loi 200, 1040 Bruxelles"],
                    "city": ["Bruxelles"],
                    "country": ["BE"],
                },
            }
        )
        assert isinstance(result, ValidatedEntity)
        assert result.schema_kind == "Address"

    def test_valid_bank_account(self) -> None:
        result = validate_entity(
            {
                "id": "bank-1",
                "schema": "BankAccount",
                "properties": {
                    "iban": ["IT60X0542811101000000123456"],
                    "bankName": ["Banca Intesa"],
                    "holder": ["ACME Holdings SA"],
                },
            }
        )
        assert isinstance(result, ValidatedEntity)
        assert result.schema_kind == "BankAccount"

    def test_valid_payment(self) -> None:
        result = validate_entity(
            {
                "id": "pay-1",
                "schema": "Payment",
                "properties": {
                    "amount": ["120000"],
                    "currency": ["EUR"],
                    "date": ["2024-03-12"],
                    "payer": ["company-1"],
                    "beneficiary": ["company-2"],
                },
            }
        )
        assert isinstance(result, ValidatedEntity)
        assert result.schema_kind == "Payment"

    def test_multi_value_property(self) -> None:
        result = validate_entity(_person(name=["Marco Rossi", "M. Rossi"]))
        assert isinstance(result, ValidatedEntity)
        assert result.properties["name"] == ("Marco Rossi", "M. Rossi")


class TestUnknownSchema:
    def test_unknown_schema_passes_through(self) -> None:
        result = validate_entity(
            {
                "id": "v-1",
                "schema": "Vessel",
                "properties": {"imoNumber": ["IMO 1234567"], "flag": ["MT"]},
            }
        )
        assert isinstance(result, ValidatedEntity)
        assert result.schema_kind == UNKNOWN_SCHEMA
        assert result.raw_schema == "Vessel"
        assert result.properties == {
            "imoNumber": ("IMO 1234567",),
            "flag": ("MT",),
        }

    def test_unknown_schema_does_not_enforce_property_allowlist(self) -> None:
        # Property names that would be rejected on a known schema are fine here.
        result = validate_entity(
            {
                "id": "x-1",
                "schema": "Mystery",
                "properties": {"totallyMadeUpField": ["whatever"]},
            }
        )
        assert isinstance(result, ValidatedEntity)
        assert result.schema_kind == UNKNOWN_SCHEMA


class TestStructuralRejection:
    def test_non_dict_input(self) -> None:
        result = validate_entity("not a dict")
        assert isinstance(result, FtMValidationError)
        assert result.error == "not_a_dict"

    def test_missing_id(self) -> None:
        result = validate_entity({"schema": "Person", "properties": {}})
        assert isinstance(result, FtMValidationError)
        assert result.error == "bad_id"

    def test_empty_id(self) -> None:
        result = validate_entity({"id": "", "schema": "Person", "properties": {}})
        assert isinstance(result, FtMValidationError)
        assert result.error == "bad_id"

    def test_non_string_id(self) -> None:
        result = validate_entity({"id": 42, "schema": "Person", "properties": {}})
        assert isinstance(result, FtMValidationError)
        assert result.error == "bad_id"

    def test_missing_schema(self) -> None:
        result = validate_entity({"id": "x", "properties": {}})
        assert isinstance(result, FtMValidationError)
        assert result.error == "bad_schema"

    def test_empty_schema(self) -> None:
        result = validate_entity({"id": "x", "schema": "", "properties": {}})
        assert isinstance(result, FtMValidationError)
        assert result.error == "bad_schema"

    def test_properties_not_a_dict(self) -> None:
        result = validate_entity({"id": "x", "schema": "Person", "properties": []})
        assert isinstance(result, FtMValidationError)
        assert result.error == "bad_properties"

    def test_property_values_not_a_list(self) -> None:
        result = validate_entity(_person(name="Marco Rossi"))  # bare string, not list
        assert isinstance(result, FtMValidationError)
        assert result.error == "bad_property_values"

    def test_empty_property_values(self) -> None:
        result = validate_entity(_person(name=[]))
        assert isinstance(result, FtMValidationError)
        assert result.error == "empty_property_values"

    def test_non_string_property_value(self) -> None:
        result = validate_entity(_person(name=["Marco", 42]))
        assert isinstance(result, FtMValidationError)
        assert result.error == "bad_property_value"

    def test_empty_string_property_value(self) -> None:
        result = validate_entity(_person(name=[""]))
        assert isinstance(result, FtMValidationError)
        assert result.error == "bad_property_value"

    def test_unknown_property_for_known_schema(self) -> None:
        result = validate_entity(_person(notARealField=["x"]))
        assert isinstance(result, FtMValidationError)
        assert result.error == "unknown_property_for_schema"
        assert "notARealField" in result.detail


class TestImmutability:
    def test_validated_entity_is_frozen(self) -> None:
        result = validate_entity(_person(name=["Marco Rossi"]))
        assert isinstance(result, ValidatedEntity)
        with pytest.raises(Exception):
            result.id = "different"  # type: ignore[misc]

    def test_validated_entity_rejects_extra_fields(self) -> None:
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError):
            ValidatedEntity(
                id="x",
                schema_kind="Person",
                raw_schema="Person",
                properties={},
                extra_field="nope",  # type: ignore[call-arg]
            )
