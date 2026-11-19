"""Controlled management of platform and company provider integrations.

Transaction ownership remains with the caller. These functions flush but
never commit or silently roll back.
"""

import json
import re
from datetime import datetime

from . import db
from .models import Company, CompanyIntegration, IntegrationProvider
from .integration_security import (
    IntegrationCredentialError,
    encrypt_credentials,
)


ALLOWED_ENVIRONMENTS = frozenset({"sandbox", "production"})

FORBIDDEN_CONFIGURATION_KEYS = frozenset({
    "secret",
    "secretkey",
    "clientsecret",
    "password",
    "token",
    "accesstoken",
    "refreshtoken",
    "bearertoken",
    "credential",
    "credentials",
    "privatekey",
    "apikey",
    "authorization",
    "authorizationheader",
    "webhooksecret",
    "signingsecret",
})


class IntegrationServiceError(ValueError):
    """Raised when an integration operation violates a safety rule."""


def _normalise_code(value):
    if not isinstance(value, str):
        raise IntegrationServiceError("Provider code is required.")

    value = value.strip().lower()

    if not value or len(value) > 80:
        raise IntegrationServiceError("Invalid provider code.")

    return value


def _validate_environment(environment):
    if not isinstance(environment, str):
        raise IntegrationServiceError("Invalid integration environment.")

    environment = environment.strip().lower()

    if environment not in ALLOWED_ENVIRONMENTS:
        raise IntegrationServiceError("Unsupported integration environment.")

    return environment


def _validate_configuration(configuration):
    if configuration is None:
        return {}

    if not isinstance(configuration, dict):
        raise IntegrationServiceError(
            "Integration configuration must be an object."
        )

    def inspect_value(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str):
                    raise IntegrationServiceError(
                        "Configuration field names must be strings."
                    )

                normalised = re.sub(r"[^a-z0-9]", "", key.lower())

                if normalised in FORBIDDEN_CONFIGURATION_KEYS:
                    raise IntegrationServiceError(
                        "Sensitive credentials must not be stored in configuration."
                    )

                inspect_value(child)

        elif isinstance(value, list):
            for child in value:
                inspect_value(child)

    inspect_value(configuration)

    try:
        encoded = json.dumps(
            configuration,
            allow_nan=False,
            ensure_ascii=False,
        )
        result = json.loads(encoded)
    except (TypeError, ValueError, UnicodeEncodeError):
        raise IntegrationServiceError(
            "Configuration contains unsupported values."
        ) from None

    return result


def _get_enabled_provider(provider_code):
    code = _normalise_code(provider_code)

    provider = IntegrationProvider.query.filter_by(
        code=code,
        is_enabled=True,
    ).first()

    if provider is None:
        raise IntegrationServiceError(
            "Provider is unavailable or disabled."
        )

    return provider


def _get_existing_connection(
    integration_id,
    ownership_scope,
    company_id=None,
):
    if (
        isinstance(integration_id, bool)
        or not isinstance(integration_id, int)
        or integration_id <= 0
    ):
        raise IntegrationServiceError("A valid integration ID is required.")

    query = CompanyIntegration.query.filter_by(
        id=integration_id,
        ownership_scope=ownership_scope,
    )

    if ownership_scope == "company":
        query = query.filter_by(company_id=company_id)
    else:
        query = query.filter(CompanyIntegration.company_id.is_(None))

    integration = query.first()

    if integration is None:
        raise IntegrationServiceError("Integration not found.")

    return integration


def _prepare_credentials(credentials):
    if credentials is None:
        return None, None

    try:
        return encrypt_credentials(credentials)
    except IntegrationCredentialError:
        raise IntegrationServiceError(
            "Integration credentials could not be protected."
        ) from None


def _create_connection(
    ownership_scope,
    company_id,
    provider_code,
    environment,
    configuration,
    credentials,
):
    provider = _get_enabled_provider(provider_code)
    environment = _validate_environment(environment)
    configuration = _validate_configuration(configuration)

    if ownership_scope == "company":
        company = Company.query.filter_by(id=company_id).first()

        if company is None:
            raise IntegrationServiceError("Company not found.")

    existing_query = CompanyIntegration.query.filter_by(
        provider_id=provider.id,
        environment=environment,
        ownership_scope=ownership_scope,
    )

    if ownership_scope == "company":
        existing_query = existing_query.filter_by(company_id=company_id)
    else:
        existing_query = existing_query.filter(
            CompanyIntegration.company_id.is_(None)
        )

    if existing_query.first() is not None:
        raise IntegrationServiceError(
            "An integration already exists for this provider and environment."
        )

    encrypted, key_version = _prepare_credentials(credentials)

    integration = CompanyIntegration(
        company_id=company_id,
        provider_id=provider.id,
        ownership_scope=ownership_scope,
        environment=environment,
        status="not_connected",
        configuration=configuration,
        credentials_encrypted=encrypted,
        credential_key_version=key_version,
    )

    db.session.add(integration)
    db.session.flush()

    return integration


def create_company_integration(
    company_id,
    provider_code,
    environment="sandbox",
    configuration=None,
    credentials=None,
):
    """Create an integration owned by one company."""
    if (
        isinstance(company_id, bool)
        or not isinstance(company_id, int)
        or company_id <= 0
    ):
        raise IntegrationServiceError("A valid company ID is required.")

    return _create_connection(
        ownership_scope="company",
        company_id=company_id,
        provider_code=provider_code,
        environment=environment,
        configuration=configuration,
        credentials=credentials,
    )


def create_platform_integration(
    provider_code,
    environment="sandbox",
    configuration=None,
    credentials=None,
):
    """Create an integration owned by the Appex platform."""
    return _create_connection(
        ownership_scope="platform",
        company_id=None,
        provider_code=provider_code,
        environment=environment,
        configuration=configuration,
        credentials=credentials,
    )


def _update_connection(
    integration,
    configuration=None,
    credentials=None,
):
    changed = False

    if configuration is not None:
        integration.configuration = _validate_configuration(configuration)
        changed = True

    if credentials is not None:
        encrypted, key_version = _prepare_credentials(credentials)
        integration.credentials_encrypted = encrypted
        integration.credential_key_version = key_version
        changed = True

    if changed:
        integration.updated_at = datetime.utcnow()
        db.session.flush()

    return integration


def update_company_integration(
    company_id,
    integration_id,
    configuration=None,
    credentials=None,
):
    """Update a connection only when it belongs to the supplied company."""
    if (
        isinstance(company_id, bool)
        or not isinstance(company_id, int)
        or company_id <= 0
    ):
        raise IntegrationServiceError("A valid company ID is required.")

    integration = _get_existing_connection(
        integration_id,
        ownership_scope="company",
        company_id=company_id,
    )

    return _update_connection(
        integration,
        configuration=configuration,
        credentials=credentials,
    )


def update_platform_integration(
    integration_id,
    configuration=None,
    credentials=None,
):
    """Update a platform-owned connection only."""
    integration = _get_existing_connection(
        integration_id,
        ownership_scope="platform",
    )

    return _update_connection(
        integration,
        configuration=configuration,
        credentials=credentials,
    )


def _status_snapshot(integration):
    """Return safe connection metadata without credential material."""
    provider = integration.provider

    return {
        "id": integration.id,
        "provider_code": provider.code if provider else None,
        "provider_name": provider.display_name if provider else None,
        "ownership_scope": integration.ownership_scope,
        "company_id": integration.company_id,
        "environment": integration.environment,
        "status": integration.status,
        "configuration": dict(integration.configuration or {}),
        "has_credentials": bool(integration.credentials_encrypted),
        "last_connected_at": integration.last_connected_at,
        "last_error_at": integration.last_error_at,
        "last_error_code": integration.last_error_code,
        "created_at": integration.created_at,
        "updated_at": integration.updated_at,
    }


def get_company_integration_status(company_id, integration_id):
    """Return safe status only for the specified company's connection."""
    if (
        isinstance(company_id, bool)
        or not isinstance(company_id, int)
        or company_id <= 0
    ):
        raise IntegrationServiceError("A valid company ID is required.")

    integration = _get_existing_connection(
        integration_id,
        ownership_scope="company",
        company_id=company_id,
    )

    return _status_snapshot(integration)


def get_platform_integration_status(integration_id):
    """Return safe status only for a platform-owned connection."""
    integration = _get_existing_connection(
        integration_id,
        ownership_scope="platform",
    )

    return _status_snapshot(integration)


def list_company_integrations(company_id):
    """List safe status snapshots for one company."""
    if (
        isinstance(company_id, bool)
        or not isinstance(company_id, int)
        or company_id <= 0
    ):
        raise IntegrationServiceError("A valid company ID is required.")

    integrations = (
        CompanyIntegration.query
        .filter_by(
            ownership_scope="company",
            company_id=company_id,
        )
        .order_by(CompanyIntegration.id.asc())
        .all()
    )

    return [_status_snapshot(item) for item in integrations]


def list_platform_integrations():
    """List safe status snapshots for platform-owned connections."""
    integrations = (
        CompanyIntegration.query
        .filter_by(ownership_scope="platform")
        .filter(CompanyIntegration.company_id.is_(None))
        .order_by(CompanyIntegration.id.asc())
        .all()
    )

    return [_status_snapshot(item) for item in integrations]
