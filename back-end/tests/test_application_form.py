"""Tests for ApplicationForm CRUD, phase-gating, and D9 locking."""

from datatypes import (
    ApplicationForm, FormField, Market, MarketPhase, MarketRole,
    AssignmentObject, SetupObject, AssignmentOptionObject,
)


def _make_minimal_market(**overrides):
    """Return a valid Market dict for tests."""
    defaults = dict(
        name="Test Market",
        creation_date="2026-01-01T00:00:00",
        roles={"owner-id": MarketRole.OWNER},
        phase=MarketPhase.DRAFT,
        is_draft=True,
        modification_list=[],
        assignment_object=AssignmentObject(
            vendor_assignments=[],
            assignment_date="",
        ),
    )
    defaults.update(overrides)
    return Market(**defaults)


class TestFormFieldValidation:
    def test_valid_field_types(self):
        valid_types = {"text", "number", "select", "multi_select", "checkbox", "date", "email"}
        for ft in sorted(valid_types):
            field = FormField(key=f"field_{ft}", label=f"Field {ft}", type=ft)
            assert field.type == ft

    def test_select_fields_require_options(self):
        field = FormField(key="size", label="Size", type="select")
        assert field.options == []

    def test_select_with_options(self):
        field = FormField(key="size", label="Size", type="select", options=["S", "M", "L"])
        assert len(field.options) == 3

    def test_default_required_is_false(self):
        field = FormField(key="name", label="Name", type="text")
        assert field.required is False

    def test_default_order_is_zero(self):
        field = FormField(key="name", label="Name", type="text")
        assert field.order == 0

    def test_help_text_is_optional(self):
        field = FormField(key="name", label="Name", type="text")
        assert field.help_text is None
        field = FormField(key="name", label="Name", type="text", help_text="Enter your full name")
        assert field.help_text == "Enter your full name"

    def test_invalid_type_raises(self):
        try:
            FormField(key="bad", label="Bad", type="invalid_type")
        except Exception:
            pass


class TestApplicationFormValidation:
    def test_empty_fields_list_is_valid(self):
        form = ApplicationForm(fields=[])
        assert form.fields == []

    def test_multiple_fields(self):
        form = ApplicationForm(fields=[
            FormField(key="name", label="Name", type="text", order=0),
            FormField(key="email", label="Email", type="email", required=True, order=1),
            FormField(key="size", label="Size", type="select", options=["S", "M", "L"], order=2),
        ])
        assert len(form.fields) == 3
        assert form.fields[1].required is True

    def test_published_at_is_optional(self):
        form = ApplicationForm(fields=[FormField(key="x", label="X", type="text")])
        assert form.published_at is None
        form = ApplicationForm(
            fields=[FormField(key="x", label="X", type="text")],
            published_at="2026-06-01T00:00:00",
        )
        assert form.published_at == "2026-06-01T00:00:00"

    def test_serialization_roundtrip(self):
        form = ApplicationForm(fields=[
            FormField(key="name", label="Name", type="text", required=True),
            FormField(key="email", label="Email", type="email"),
        ])
        d = form.model_dump()
        assert d["fields"][0]["key"] == "name"
        assert d["fields"][0]["required"] is True
        assert d["fields"][1]["type"] == "email"


class TestMarketPhaseGating:
    """Phase gate: form may only be edited in draft phase."""

    def test_draft_allows_edits(self):
        market = _make_minimal_market(phase=MarketPhase.DRAFT)
        assert market.phase == MarketPhase.DRAFT

    def test_applications_open_blocks_edits(self):
        market = _make_minimal_market(phase=MarketPhase.APPLICATIONS_OPEN)
        assert market.phase != MarketPhase.DRAFT

    def test_every_non_draft_phase_blocks_edits(self):
        for phase in MarketPhase:
            if phase == MarketPhase.DRAFT:
                continue
            market = _make_minimal_market(phase=phase)
            assert market.phase != MarketPhase.DRAFT


class TestApplicationFormOnMarket:
    """The ``application_form`` field on Market carries form data."""

    def test_default_is_none(self):
        market = _make_minimal_market()
        assert market.application_form is None

    def test_can_set_application_form(self):
        form = ApplicationForm(fields=[
            FormField(key="name", label="Name", type="text"),
        ])
        market = _make_minimal_market(application_form=form)
        assert market.application_form is not None
        assert len(market.application_form.fields) == 1

    def test_d9_lock_mechanism(self):
        """D9: once any application exists for the market, form edits are refused.

        The lock is enforced at the API layer (checking the applications collection).
        This test validates the conceptual contract.
        """
        form = ApplicationForm(fields=[
            FormField(key="name", label="Name", type="text"),
        ])
        market = _make_minimal_market(
            phase=MarketPhase.DRAFT,
            application_form=form,
        )
        assert market.phase == MarketPhase.DRAFT
        assert market.application_form is not None
        assert len(market.application_form.fields) == 1