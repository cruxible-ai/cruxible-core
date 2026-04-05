"""Tests for deploy/bootstrap routes and runtime-key auth."""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from cruxible_core.deploy import build_deploy_bundle
from cruxible_core.mcp.handlers import reset_client_cache
from cruxible_core.mcp.permissions import reset_permissions
from cruxible_core.runtime.instance import CruxibleInstance
from cruxible_core.runtime.instance_manager import get_manager
from cruxible_core.server.app import create_app
from cruxible_core.server.auth_store import reset_auth_store
from cruxible_core.server.registry import get_registry, reset_registry
from cruxible_core.service import service_fork_world, service_publish_world
from tests.test_cli.conftest import CAR_PARTS_YAML

WORLD_MODEL_YAML = """\
version: "1.0"
name: case_reference
kind: world_model

entity_types:
  Case:
    properties:
      case_id:
        type: string
        primary_key: true
      title:
        type: string

relationships:
  - name: cites
    from: Case
    to: Case
"""


def _mint_bootstrap_token(
    private_key: rsa.RSAPrivateKey,
    *,
    system_id: str,
    expires_delta: timedelta = timedelta(minutes=10),
    jti: str | None = None,
    actions: list[str] | None = None,
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": "https://cloud.cruxible.test",
            "aud": "cruxible-core",
            "kind": "bootstrap",
            "org_id": "org-test",
            "system_id": system_id,
            "actions": actions if actions is not None else ["bootstrap", "admin"],
            "iat": int(now.timestamp()),
            "exp": int((now + expires_delta).timestamp()),
            "jti": jti or f"jti-{system_id}-{int(now.timestamp())}",
        },
        private_key,
        algorithm="RS256",
    )


@pytest.fixture
def bootstrap_private_key(monkeypatch: pytest.MonkeyPatch) -> rsa.RSAPrivateKey:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    monkeypatch.setenv("CRUXIBLE_BOOTSTRAP_PUBLIC_KEY", public_pem)
    monkeypatch.setenv("CRUXIBLE_BOOTSTRAP_ISSUER", "https://cloud.cruxible.test")
    monkeypatch.setenv("CRUXIBLE_BOOTSTRAP_AUDIENCE", "cruxible-core")
    return private_key


@pytest.fixture
def app_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bootstrap_private_key: rsa.RSAPrivateKey,
) -> TestClient:
    del bootstrap_private_key
    monkeypatch.setenv("CRUXIBLE_SERVER_STATE_DIR", str(tmp_path / "server-state"))
    reset_permissions()
    reset_registry()
    reset_auth_store()
    reset_client_cache()
    get_manager().clear()
    return TestClient(create_app())


@pytest.fixture
def server_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "config.yaml").write_text(CAR_PARTS_YAML)
    return root


def _upload_bundle(client: TestClient, bundle_path: Path, token: str) -> str:
    with bundle_path.open("rb") as handle:
        upload = client.post(
            "/api/v1/deploy/uploads",
            headers={"Authorization": f"Bearer {token}"},
            files={"bundle": ("bundle.zip", handle, "application/zip")},
        )
    assert upload.status_code == 200, upload.text
    return upload.json()["upload_id"]


def _bootstrap_request(
    client: TestClient,
    token: str,
    *,
    system_id: str,
    upload_id: str,
) -> object:
    return client.post(
        "/api/v1/deploy/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
        json={"system_id": system_id, "upload_id": upload_id},
    )


def _rewrite_bundle(
    bundle_path: Path,
    mutator: Callable[[Path], None],
) -> Path:
    temp_root = Path(tempfile.mkdtemp(prefix="cruxible_bundle_mutate_"))
    try:
        with zipfile.ZipFile(bundle_path) as zf:
            zf.extractall(temp_root)
        mutator(temp_root)
        rewritten = Path(tempfile.mkstemp(prefix="cruxible_bundle_", suffix=".zip")[1])
        with zipfile.ZipFile(rewritten, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(temp_root.rglob("*")):
                if path.is_dir():
                    continue
                zf.write(path, path.relative_to(temp_root).as_posix())
        return rewritten
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _copy_bundle_with_extra_entry(bundle_path: Path, *, arcname: str, data: str) -> Path:
    rewritten = Path(tempfile.mkstemp(prefix="cruxible_bundle_", suffix=".zip")[1])
    with zipfile.ZipFile(bundle_path) as source, zipfile.ZipFile(
        rewritten,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as target:
        for info in source.infolist():
            target.writestr(info, source.read(info.filename))
        target.writestr(arcname, data)
    return rewritten


def _create_release_fork_root(tmp_path: Path) -> Path:
    world_root = tmp_path / "world-model"
    world_root.mkdir()
    (world_root / "config.yaml").write_text(WORLD_MODEL_YAML)
    instance = CruxibleInstance.init(world_root, "config.yaml")
    release_dir = tmp_path / "releases" / "current"
    service_publish_world(
        instance,
        transport_ref=f"file://{release_dir}",
        world_id="case-law",
        release_id="v1.0.0",
        compatibility="data_only",
    )
    fork_root = tmp_path / "forked-model"
    service_fork_world(
        transport_ref=f"file://{release_dir}",
        root_dir=fork_root,
    )
    return fork_root


def _bootstrap_system(
    client: TestClient,
    private_key: rsa.RSAPrivateKey,
    *,
    system_id: str,
    server_project: Path,
) -> tuple[str, str]:
    bundle = build_deploy_bundle(
        root_dir=server_project,
        config_path=str(server_project / "config.yaml"),
    )
    token = _mint_bootstrap_token(private_key, system_id=system_id)
    try:
        upload_id = _upload_bundle(client, bundle.bundle_path, token)
        bootstrap = _bootstrap_request(
            client,
            token,
            system_id=system_id,
            upload_id=upload_id,
        )
        assert bootstrap.status_code == 200, bootstrap.text
        payload = bootstrap.json()
        assert payload["status"] == "bootstrapped"
        assert payload["instance_id"]
        assert payload["admin_bearer_token"]
        return payload["instance_id"], payload["admin_bearer_token"]
    finally:
        bundle.bundle_path.unlink(missing_ok=True)


def test_deploy_bootstrap_and_runtime_key_management(
    app_client: TestClient,
    server_project: Path,
    bootstrap_private_key: rsa.RSAPrivateKey,
) -> None:
    instance_id, admin_token = _bootstrap_system(
        app_client,
        bootstrap_private_key,
        system_id="system-alpha",
        server_project=server_project,
    )

    status = app_client.get(
        "/api/v1/deploy/status",
        headers={"Authorization": f"Bearer {admin_token}"},
        params={"system_id": "system-alpha"},
    )
    assert status.status_code == 200
    assert status.json()["status"] == "initialized"
    assert status.json()["instance_id"] == instance_id

    stats = app_client.get(
        f"/api/v1/{instance_id}/stats",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert stats.status_code == 200
    assert stats.json()["entity_count"] == 0

    created = app_client.post(
        "/api/v1/deploy/keys",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"role": "viewer", "subject_label": "viewer-key"},
    )
    assert created.status_code == 200
    created_payload = created.json()
    assert created_payload["credential"]["role"] == "viewer"
    assert created_payload["bearer_token"].startswith("crx_key_")
    key_id = created_payload["credential"]["key_id"]

    listed = app_client.get(
        "/api/v1/deploy/keys",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert listed.status_code == 200
    assert {item["key_id"] for item in listed.json()["credentials"]} >= {key_id}

    revoked = app_client.post(
        f"/api/v1/deploy/keys/{key_id}/revoke",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["revoked"] is True


def test_runtime_api_key_scope_rejects_other_instance(
    app_client: TestClient,
    server_project: Path,
    bootstrap_private_key: rsa.RSAPrivateKey,
) -> None:
    instance_a, token_a = _bootstrap_system(
        app_client,
        bootstrap_private_key,
        system_id="system-a",
        server_project=server_project,
    )
    instance_b, _token_b = _bootstrap_system(
        app_client,
        bootstrap_private_key,
        system_id="system-b",
        server_project=server_project,
    )

    assert instance_a != instance_b
    response = app_client.get(
        f"/api/v1/{instance_b}/stats",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert response.status_code == 403
    assert response.json()["error_type"] == "InstanceScopeError"


def test_deploy_bootstrap_is_idempotent_for_initialized_system(
    app_client: TestClient,
    server_project: Path,
    bootstrap_private_key: rsa.RSAPrivateKey,
) -> None:
    instance_id, _admin_token = _bootstrap_system(
        app_client,
        bootstrap_private_key,
        system_id="system-idempotent",
        server_project=server_project,
    )

    bundle = build_deploy_bundle(
        root_dir=server_project,
        config_path=str(server_project / "config.yaml"),
    )
    token = _mint_bootstrap_token(bootstrap_private_key, system_id="system-idempotent")
    try:
        upload_id = _upload_bundle(app_client, bundle.bundle_path, token)
        response = _bootstrap_request(
            app_client,
            token,
            system_id="system-idempotent",
            upload_id=upload_id,
        )
    finally:
        bundle.bundle_path.unlink(missing_ok=True)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "already_initialized"
    assert payload["instance_id"] == instance_id
    assert payload["admin_bearer_token"] is None


def test_expired_bootstrap_jwt_is_rejected_for_upload(
    app_client: TestClient,
    server_project: Path,
    bootstrap_private_key: rsa.RSAPrivateKey,
) -> None:
    bundle = build_deploy_bundle(
        root_dir=server_project,
        config_path=str(server_project / "config.yaml"),
    )
    token = _mint_bootstrap_token(
        bootstrap_private_key,
        system_id="system-expired",
        expires_delta=timedelta(minutes=-1),
    )
    try:
        with bundle.bundle_path.open("rb") as handle:
            response = app_client.post(
                "/api/v1/deploy/uploads",
                headers={"Authorization": f"Bearer {token}"},
                files={"bundle": ("bundle.zip", handle, "application/zip")},
            )
    finally:
        bundle.bundle_path.unlink(missing_ok=True)

    assert response.status_code == 401
    assert response.json()["error_type"] == "AuthenticationError"


def test_bootstrap_token_requires_bootstrap_or_admin_action(
    app_client: TestClient,
    server_project: Path,
    bootstrap_private_key: rsa.RSAPrivateKey,
) -> None:
    bundle = build_deploy_bundle(
        root_dir=server_project,
        config_path=str(server_project / "config.yaml"),
    )
    token = _mint_bootstrap_token(
        bootstrap_private_key,
        system_id="system-no-actions",
        actions=[],
    )
    try:
        with bundle.bundle_path.open("rb") as handle:
            response = app_client.post(
                "/api/v1/deploy/uploads",
                headers={"Authorization": f"Bearer {token}"},
                files={"bundle": ("bundle.zip", handle, "application/zip")},
            )
    finally:
        bundle.bundle_path.unlink(missing_ok=True)

    assert response.status_code == 401
    assert response.json()["error_type"] == "AuthenticationError"


def test_replayed_bootstrap_jti_is_rejected_after_failed_bootstrap(
    app_client: TestClient,
    server_project: Path,
    bootstrap_private_key: rsa.RSAPrivateKey,
) -> None:
    bundle = build_deploy_bundle(
        root_dir=server_project,
        config_path=str(server_project / "config.yaml"),
    )
    broken_bundle = _rewrite_bundle(
        bundle.bundle_path,
        lambda root: (root / "manifest.json").write_text(
            json.dumps(
                {
                    **json.loads((root / "manifest.json").read_text(encoding="utf-8")),
                    "lock_digest": "sha256:broken",
                },
                indent=2,
            ),
            encoding="utf-8",
        ),
    )
    token = _mint_bootstrap_token(
        bootstrap_private_key,
        system_id="system-replay",
        jti="replay-jti",
    )
    try:
        upload_id = _upload_bundle(app_client, broken_bundle, token)
        failed = _bootstrap_request(
            app_client,
            token,
            system_id="system-replay",
            upload_id=upload_id,
        )
        replayed = _bootstrap_request(
            app_client,
            token,
            system_id="system-replay",
            upload_id=upload_id,
        )
    finally:
        bundle.bundle_path.unlink(missing_ok=True)
        broken_bundle.unlink(missing_ok=True)

    assert failed.status_code == 400
    assert failed.json()["error_type"] == "ConfigError"
    status = app_client.get(
        "/api/v1/deploy/status",
        headers={"Authorization": f"Bearer {token}"},
        params={"system_id": "system-replay"},
    )
    assert status.status_code == 200
    assert status.json()["status"] == "failed"

    assert replayed.status_code == 401
    assert replayed.json()["error_type"] == "AuthenticationError"


def test_bootstrap_rejects_in_progress_system(
    app_client: TestClient,
    server_project: Path,
    bootstrap_private_key: rsa.RSAPrivateKey,
) -> None:
    get_registry().create_deployed_instance(
        system_id="system-busy",
        instance_slug=None,
        bootstrap_status="bootstrapping",
    )
    bundle = build_deploy_bundle(
        root_dir=server_project,
        config_path=str(server_project / "config.yaml"),
    )
    token = _mint_bootstrap_token(bootstrap_private_key, system_id="system-busy")
    try:
        upload_id = _upload_bundle(app_client, bundle.bundle_path, token)
        response = _bootstrap_request(
            app_client,
            token,
            system_id="system-busy",
            upload_id=upload_id,
        )
    finally:
        bundle.bundle_path.unlink(missing_ok=True)

    assert response.status_code == 400
    assert response.json()["error_type"] == "ConfigError"
    assert "already in progress" in response.json()["message"]


def test_upload_rejects_invalid_manifest_json(
    app_client: TestClient,
    server_project: Path,
    bootstrap_private_key: rsa.RSAPrivateKey,
) -> None:
    bundle = build_deploy_bundle(
        root_dir=server_project,
        config_path=str(server_project / "config.yaml"),
    )
    invalid_bundle = _rewrite_bundle(
        bundle.bundle_path,
        lambda root: (root / "manifest.json").write_text("{", encoding="utf-8"),
    )
    token = _mint_bootstrap_token(bootstrap_private_key, system_id="system-invalid-manifest")
    try:
        with invalid_bundle.open("rb") as handle:
            response = app_client.post(
                "/api/v1/deploy/uploads",
                headers={"Authorization": f"Bearer {token}"},
                files={"bundle": ("bundle.zip", handle, "application/zip")},
            )
    finally:
        bundle.bundle_path.unlink(missing_ok=True)
        invalid_bundle.unlink(missing_ok=True)

    assert response.status_code == 400
    assert response.json()["error_type"] == "ConfigError"
    assert "manifest is invalid" in response.json()["message"]


def test_bootstrap_rejects_zip_slip_bundle_paths(
    app_client: TestClient,
    server_project: Path,
    bootstrap_private_key: rsa.RSAPrivateKey,
) -> None:
    bundle = build_deploy_bundle(
        root_dir=server_project,
        config_path=str(server_project / "config.yaml"),
    )
    malicious_bundle = _copy_bundle_with_extra_entry(
        bundle.bundle_path,
        arcname="../escape.txt",
        data="owned",
    )
    token = _mint_bootstrap_token(bootstrap_private_key, system_id="system-zip-slip")
    try:
        upload_id = _upload_bundle(app_client, malicious_bundle, token)
        response = _bootstrap_request(
            app_client,
            token,
            system_id="system-zip-slip",
            upload_id=upload_id,
        )
    finally:
        bundle.bundle_path.unlink(missing_ok=True)
        malicious_bundle.unlink(missing_ok=True)

    assert response.status_code == 400
    assert response.json()["error_type"] == "ConfigError"
    assert "invalid archive path" in response.json()["message"]


def test_legacy_server_token_cannot_manage_runtime_keys(
    app_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CRUXIBLE_SERVER_TOKEN", "legacy-secret")
    response = app_client.post(
        "/api/v1/deploy/keys",
        headers={"Authorization": "Bearer legacy-secret"},
        json={"role": "viewer", "subject_label": "viewer-key"},
    )

    assert response.status_code == 401
    assert response.json()["error_type"] == "AuthenticationError"


def test_release_fork_bundle_bootstraps_and_supports_world_preview(
    app_client: TestClient,
    tmp_path: Path,
    bootstrap_private_key: rsa.RSAPrivateKey,
) -> None:
    fork_root = _create_release_fork_root(tmp_path)
    bundle = build_deploy_bundle(root_dir=fork_root)
    token = _mint_bootstrap_token(bootstrap_private_key, system_id="system-fork")
    try:
        upload_id = _upload_bundle(app_client, bundle.bundle_path, token)
        bootstrap = _bootstrap_request(
            app_client,
            token,
            system_id="system-fork",
            upload_id=upload_id,
        )
    finally:
        bundle.bundle_path.unlink(missing_ok=True)

    assert bootstrap.status_code == 200, bootstrap.text
    payload = bootstrap.json()
    assert payload["status"] == "bootstrapped"
    instance_id = payload["instance_id"]
    admin_token = payload["admin_bearer_token"]

    status = app_client.get(
        f"/api/v1/{instance_id}/world/status",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert status.status_code == 200
    assert status.json()["upstream"]["world_id"] == "case-law"
    assert status.json()["upstream"]["release_id"] == "v1.0.0"

    preview = app_client.post(
        f"/api/v1/{instance_id}/world/pull/preview",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert preview.status_code == 200
    assert preview.json()["current_release_id"] == "v1.0.0"
    assert preview.json()["target_release_id"] == "v1.0.0"
    assert "Already at latest pulled release" in preview.json()["warnings"]


def test_release_fork_bootstrap_validates_active_config(
    app_client: TestClient,
    tmp_path: Path,
    bootstrap_private_key: rsa.RSAPrivateKey,
) -> None:
    fork_root = _create_release_fork_root(tmp_path)
    active_config = fork_root / ".cruxible" / "composed" / "config.yaml"
    active_config.write_text(
        active_config.read_text(encoding="utf-8")
        + (
            "\nnamed_queries:\n"
            "  broken_cases:\n"
            "    entry_point: Case\n"
            "    traversal:\n"
            "      - relationship: missing_rel\n"
            "        direction: outgoing\n"
            "    returns: \"list[Case]\"\n"
        ),
        encoding="utf-8",
    )

    bundle = build_deploy_bundle(root_dir=fork_root)
    token = _mint_bootstrap_token(bootstrap_private_key, system_id="system-fork-invalid")
    try:
        upload_id = _upload_bundle(app_client, bundle.bundle_path, token)
        response = _bootstrap_request(
            app_client,
            token,
            system_id="system-fork-invalid",
            upload_id=upload_id,
        )
    finally:
        bundle.bundle_path.unlink(missing_ok=True)

    assert response.status_code == 400
    assert response.json()["error_type"] == "ConfigError"
    assert "cross-reference error" in response.json()["message"]
