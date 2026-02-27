"""Tests for PII detection accuracy."""

from __future__ import annotations

from toolwright.core.normalize import EndpointAggregator


class TestPIIDetection:
    """PII detection should avoid false positives on common non-PII fields."""

    def setup_method(self) -> None:
        self.aggregator = EndpointAggregator(first_party_hosts=["api.example.com"])

    def test_product_name_is_not_pii(self) -> None:
        """A product with a 'name' field should not be flagged as PII."""
        samples = [{"id": "prod_1", "name": "Widget", "price": 9.99}]
        assert not self.aggregator._detect_pii([], samples)

    def test_project_name_is_not_pii(self) -> None:
        """A project/org with only a 'name' field should not be PII."""
        samples = [{"id": "proj_1", "name": "My Project", "status": "active"}]
        assert not self.aggregator._detect_pii([], samples)

    def test_name_alone_is_not_pii(self) -> None:
        """'name' by itself is too generic to be considered PII."""
        samples = [{"name": "some thing"}]
        assert not self.aggregator._detect_pii([], samples)

    def test_person_with_name_and_email_is_pii(self) -> None:
        """name + email together indicate a person record -> PII."""
        samples = [{"name": "Jane Doe", "email": "jane@example.com"}]
        assert self.aggregator._detect_pii([], samples)

    def test_email_alone_is_pii(self) -> None:
        """email is always PII regardless of other fields."""
        samples = [{"email": "test@example.com"}]
        assert self.aggregator._detect_pii([], samples)

    def test_phone_alone_is_pii(self) -> None:
        """phone is always PII."""
        samples = [{"phone": "+1234567890"}]
        assert self.aggregator._detect_pii([], samples)

    def test_ssn_is_pii(self) -> None:
        """SSN is always PII."""
        samples = [{"ssn": "123-45-6789"}]
        assert self.aggregator._detect_pii([], samples)

    def test_nested_email_is_pii(self) -> None:
        """PII in nested objects should be detected."""
        samples = [{"data": {"user": {"email": "x@y.com"}}}]
        assert self.aggregator._detect_pii([], samples)

    def test_first_name_last_name_is_pii(self) -> None:
        """first_name/last_name are person-specific -> PII."""
        samples = [{"first_name": "Jane", "last_name": "Doe"}]
        assert self.aggregator._detect_pii([], samples)

    def test_address_is_pii(self) -> None:
        """address is PII."""
        samples = [{"address": "123 Main St"}]
        assert self.aggregator._detect_pii([], samples)

    def test_credit_card_is_pii(self) -> None:
        """credit_card is PII."""
        samples = [{"credit_card": "4111111111111111"}]
        assert self.aggregator._detect_pii([], samples)

    def test_request_body_pii(self) -> None:
        """PII in request body should be detected."""
        request_samples = [{"email": "a@b.com", "password": "secret"}]
        assert self.aggregator._detect_pii(request_samples, [])
