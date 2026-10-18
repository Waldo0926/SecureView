from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.api.dependencies import get_current_actor, get_key_service, get_request_context
from app.api.responses import AUTH_NO_STORE_HEADERS, ApiSuccessResponse, ok
from app.core.time import to_api_utc
from app.domain.auth import ActorContext, RequestContext
from app.schemas.key_schema import (
    AddClientKeyRequest,
    AddClientKeyResponse,
    ClientKeyAdditionIn,
    EncryptedPrivateKeyBundleOut,
    KeyAdditionSigningPayloadOut,
    KeyProtectionProfileOut,
    MyKeyBundleResponse,
    PublicEncryptionKeyOut,
    ResetKeyProtectionIn,
    ResetKeyProtectionRequest,
    ResetKeyProtectionResponse,
    ResetKeyProtectionSigningPayloadOut,
    RewrapKeyProtectionIn,
    RewrapKeyProtectionRequest,
    RewrapKeyProtectionResponse,
    RewrapKeyProtectionSigningPayloadOut,
    encode_base64,
)
from app.services.key_service import KeyService

router = APIRouter()

ActorDependency = Annotated[ActorContext, Depends(get_current_actor)]
KeyServiceDependency = Annotated[KeyService, Depends(get_key_service)]
RequestContextDependency = Annotated[RequestContext, Depends(get_request_context)]


def _public_key(user, key) -> PublicEncryptionKeyOut:
    return PublicEncryptionKeyOut(
        key_id=UUID(key.key_uuid),
        user_id=UUID(user.user_uuid),
        algorithm=key.algorithm,
        key_size_bits=key.key_size_bits,
        public_key_pem=key.public_key_pem,
        fingerprint=key.fingerprint,
        created_at=to_api_utc(key.created_at),
    )


def _bundle_response(user, key, profile, bundle) -> MyKeyBundleResponse:
    return MyKeyBundleResponse(
        key=_public_key(user, key),
        protection=KeyProtectionProfileOut(
            profile_id=UUID(profile.profile_uuid),
            format_version=profile.format_version,
            kdf_algorithm=profile.kdf_algorithm,
            kdf_version=profile.kdf_version,
            kdf_salt=encode_base64(profile.kdf_salt),
            kdf_memory_kib=profile.kdf_memory_kib,
            kdf_iterations=profile.kdf_iterations,
            kdf_parallelism=profile.kdf_parallelism,
            derived_key_length=profile.derived_key_length,
            amk_wrapping_algorithm=profile.amk_wrapping_algorithm,
            wrapped_amk=encode_base64(profile.wrapped_amk),
            amk_nonce=encode_base64(profile.amk_nonce),
            amk_auth_tag=encode_base64(profile.amk_auth_tag),
            aad_version=profile.aad_version,
            revision=profile.revision,
            updated_at=to_api_utc(profile.updated_at),
        ),
        private_key_bundle=EncryptedPrivateKeyBundleOut(
            bundle_id=UUID(bundle.bundle_uuid),
            format_version=bundle.format_version,
            private_key_format=bundle.private_key_format,
            derivation_algorithm=bundle.derivation_algorithm,
            derivation_salt=encode_base64(bundle.derivation_salt),
            encryption_algorithm=bundle.encryption_algorithm,
            encrypted_private_key=encode_base64(bundle.encrypted_private_key),
            nonce=encode_base64(bundle.nonce),
            auth_tag=encode_base64(bundle.auth_tag),
            aad_version=bundle.aad_version,
            ciphertext_sha256=bundle.ciphertext_sha256,
            revision=bundle.revision,
            updated_at=to_api_utc(bundle.updated_at),
        ),
    )


@router.get("/me", response_model=ApiSuccessResponse[MyKeyBundleResponse])
def my_key_bundle(
    actor: ActorDependency,
    service: KeyServiceDependency,
) -> JSONResponse:
    user, key, profile, bundle = service.get_my_bundle(actor=actor)
    response = _bundle_response(user, key, profile, bundle)
    return ok(
        message="Encrypted key bundle retrieved", data=response, headers=AUTH_NO_STORE_HEADERS
    )


@router.get(
    "/me/{key_id}",
    response_model=ApiSuccessResponse[MyKeyBundleResponse],
)
def owned_key_bundle(
    key_id: UUID,
    actor: ActorDependency,
    service: KeyServiceDependency,
) -> JSONResponse:
    user, key, profile, bundle = service.get_owned_bundle(actor=actor, key_id=key_id)
    return ok(
        message="Encrypted key bundle retrieved",
        data=_bundle_response(user, key, profile, bundle),
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post(
    "/me/rewrap/signing-payload",
    response_model=ApiSuccessResponse[RewrapKeyProtectionSigningPayloadOut],
)
def rewrap_signing_payload(
    payload: RewrapKeyProtectionIn,
    actor: ActorDependency,
    service: KeyServiceDependency,
) -> JSONResponse:
    authorization_payload = service.get_rewrap_signing_payload(
        actor=actor,
        authorizing_key_id=payload.authorizing_key_id,
        expected_revision=payload.expected_revision,
        protection=payload.to_domain(),
    )
    response = RewrapKeyProtectionSigningPayloadOut(
        authorization_payload=encode_base64(authorization_payload)
    )
    return ok(
        message="Current-key rewrap authorization payload created",
        data=response,
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post(
    "/me/rewrap",
    response_model=ApiSuccessResponse[RewrapKeyProtectionResponse],
)
def rewrap_my_key(
    payload: RewrapKeyProtectionRequest,
    actor: ActorDependency,
    context: RequestContextDependency,
    service: KeyServiceDependency,
) -> JSONResponse:
    profile = service.rewrap_protection_profile(
        actor=actor,
        authorizing_key_id=payload.authorizing_key_id,
        expected_revision=payload.expected_revision,
        protection=payload.to_domain(),
        authorization_signature=payload.signature_bytes(),
        context=context,
    )
    response = RewrapKeyProtectionResponse(
        profile_id=UUID(profile.profile_uuid),
        revision=profile.revision,
        updated_at=to_api_utc(profile.updated_at),
    )
    return ok(message="Key protection rewrapped", data=response, headers=AUTH_NO_STORE_HEADERS)


@router.post(
    "/me/reset-protection/signing-payload",
    response_model=ApiSuccessResponse[ResetKeyProtectionSigningPayloadOut],
)
def reset_protection_signing_payload(
    payload: ResetKeyProtectionIn,
    actor: ActorDependency,
    service: KeyServiceDependency,
) -> JSONResponse:
    authorization_payload = service.get_reset_signing_payload(
        actor=actor,
        reset=payload.to_domain(),
    )
    response = ResetKeyProtectionSigningPayloadOut(
        authorization_payload=encode_base64(authorization_payload)
    )
    return ok(
        message="Private-key reset authorization payload created",
        data=response,
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post(
    "/me/reset-protection",
    response_model=ApiSuccessResponse[ResetKeyProtectionResponse],
)
def reset_my_key_protection(
    payload: ResetKeyProtectionRequest,
    actor: ActorDependency,
    context: RequestContextDependency,
    service: KeyServiceDependency,
) -> JSONResponse:
    """Set a new encryption passphrase, proven by the private key file from registration."""
    profile, bundle = service.reset_protection_with_private_key(
        actor=actor,
        reset=payload.to_domain(),
        authorization_signature=payload.signature_bytes(),
        context=context,
    )
    response = ResetKeyProtectionResponse(
        profile_id=UUID(profile.profile_uuid),
        profile_revision=profile.revision,
        bundle_id=UUID(bundle.bundle_uuid),
        bundle_revision=bundle.revision,
        updated_at=to_api_utc(profile.updated_at),
    )
    return ok(
        message="Encryption passphrase reset; the account key and every file wrapping are unchanged",
        data=response,
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post(
    "/add/signing-payload",
    response_model=ApiSuccessResponse[KeyAdditionSigningPayloadOut],
)
def key_addition_signing_payload(
    payload: ClientKeyAdditionIn,
    actor: ActorDependency,
    service: KeyServiceDependency,
) -> JSONResponse:
    authorization_payload = service.get_addition_signing_payload(
        actor=actor,
        addition=payload.to_domain(),
    )
    response = KeyAdditionSigningPayloadOut(
        authorization_payload=encode_base64(authorization_payload)
    )
    return ok(
        message="Current-key authorization payload created",
        data=response,
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post(
    "/add",
    response_model=ApiSuccessResponse[AddClientKeyResponse],
    status_code=status.HTTP_201_CREATED,
)
def add_client_key(
    payload: AddClientKeyRequest,
    actor: ActorDependency,
    context: RequestContextDependency,
    service: KeyServiceDependency,
) -> JSONResponse:
    key, bundle, profile = service.add_client_key(
        actor=actor,
        addition=payload.to_domain(),
        authorization_signature=payload.signature_bytes(),
        context=context,
    )
    response = AddClientKeyResponse(
        key_id=UUID(key.key_uuid),
        bundle_id=UUID(bundle.bundle_uuid),
        protection_profile_id=UUID(profile.profile_uuid),
        protection_revision=profile.revision,
        public_key_fingerprint=key.fingerprint,
        created_at=to_api_utc(key.created_at),
    )
    return ok(
        message="Client key added; previous file wrappings were retained",
        data=response,
        code=status.HTTP_201_CREATED,
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.get(
    "/users/{user_id}/active",
    response_model=ApiSuccessResponse[PublicEncryptionKeyOut],
)
def active_user_key(
    user_id: UUID,
    _actor: ActorDependency,
    service: KeyServiceDependency,
) -> JSONResponse:
    user, key = service.get_active_public_key(user_public_id=user_id)
    return ok(
        message="Active public key retrieved",
        data=_public_key(user, key),
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.get(
    "/users/by-identifier/{identifier}/active",
    response_model=ApiSuccessResponse[PublicEncryptionKeyOut],
)
def active_user_key_by_identifier(
    identifier: str,
    _actor: ActorDependency,
    service: KeyServiceDependency,
) -> JSONResponse:
    """Resolve a share recipient by an exact username or email address.

    The share contract is expressed in `target_user_id` and `target_key_id`, but a sender
    knows a colleague's username or email, not their UUID. Registered under
    `by-identifier` rather than as a second shape of `/users/{user_id}/active`, so a
    username that happens to parse as a UUID cannot be routed as one.

    Exact match only, and authenticated: this resolves someone the sender already knows,
    and is deliberately not a directory that can be searched or listed.
    """
    user, key = service.get_active_public_key_by_identifier(identifier=identifier)
    return ok(
        message="Active public key retrieved",
        data=_public_key(user, key),
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.get(
    "/users/by-username/{username}/active",
    response_model=ApiSuccessResponse[PublicEncryptionKeyOut],
    deprecated=True,
)
def active_user_key_by_username(
    username: str,
    _actor: ActorDependency,
    service: KeyServiceDependency,
) -> JSONResponse:
    """Compatibility alias for clients deployed before email recipient lookup existed."""
    user, key = service.get_active_public_key_by_identifier(identifier=username)
    return ok(
        message="Active public key retrieved",
        data=_public_key(user, key),
        headers=AUTH_NO_STORE_HEADERS,
    )
