"""Schema-level guards for the first commercial-domain slice."""

from app.models.contact import ConsentRecord, Contact, ContactPoint


def test_contact_metadata_preserves_identity_and_append_only_boundaries() -> None:
    contact_columns = Contact.__table__.columns
    point_columns = ContactPoint.__table__.columns
    consent_columns = ConsentRecord.__table__.columns
    point_constraints = {
        constraint.name for constraint in ContactPoint.__table__.constraints
    }
    consent_constraints = {
        constraint.name for constraint in ConsentRecord.__table__.constraints
    }

    assert "display_name" not in contact_columns
    assert "external_subject" not in point_columns
    assert "plaintext" not in point_columns
    assert "updated_at" not in consent_columns
    assert contact_columns.status.default.arg == "provisional"
    assert contact_columns.status.server_default.arg == "provisional"
    assert consent_columns.principal_id.nullable is False
    assert consent_columns.contact_id.nullable is True
    assert "uq_contact_principal" in {
        constraint.name for constraint in Contact.__table__.constraints
    }
    assert "ck_contact_status" in {
        constraint.name for constraint in Contact.__table__.constraints
    }
    assert "uq_contact_point_value" in point_constraints
    assert "ck_contact_point_ciphertext" in point_constraints
    assert "uq_consent_record_agent_idempotency" in consent_constraints
    assert "ck_consent_record_expiration" in consent_constraints
    assert "ck_consent_record_point_requires_contact" in consent_constraints
