from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

client = TestClient(app)


def get_access_token() -> str:
    email = f"document-user-{uuid4().hex}@example.com"
    password = "correct-horse-battery-staple"
    client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
        },
    )
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )
    return response.json()["access_token"]


def upload_txt_document(token: str) -> dict:
    response = client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={
            "file": (
                "policy.txt",
                b"Backups run every night.",
                "text/plain",
            )
        },
    )
    assert response.status_code == 201
    return response.json()


def test_list_documents_requires_authentication() -> None:
    response = client.get("/api/v1/documents")

    assert response.status_code == 401


def test_list_documents_for_authenticated_user() -> None:
    token = get_access_token()

    response = client.get(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == []


def test_upload_txt_document(tmp_path: Path, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path))

    token = get_access_token()
    response = client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={
            "file": (
                "policy.txt",
                b"Backups run every night.",
                "text/plain",
            )
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["original_filename"] == "policy.txt"
    assert body["content_type"] == "text/plain"
    assert body["size_bytes"] == len(b"Backups run every night.")
    assert body["checksum_sha256"]
    assert body["status"] == "ready"
    assert body["chunk_count"] == 1
    assert body["ingestion_error"] is None
    assert len(list(tmp_path.iterdir())) == 1

    list_response = client.get(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    chunks_response = client.get(
        f"/api/v1/documents/{body['id']}/chunks",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert chunks_response.status_code == 200
    chunks = chunks_response.json()
    assert len(chunks) == 1
    assert chunks[0]["chunk_index"] == 0
    assert chunks[0]["content"] == "Backups run every night."
    assert chunks[0]["char_start"] == 0
    assert chunks[0]["char_end"] == len("Backups run every night.")
    assert chunks[0]["token_start"] == 0
    assert chunks[0]["token_end"] > 0


def test_upload_txt_document_creates_multiple_chunks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path))
    monkeypatch.setattr(settings, "document_chunk_size_chars", 12)
    monkeypatch.setattr(settings, "document_chunk_overlap_chars", 2)
    token = get_access_token()

    response = client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={
            "file": (
                "policy.txt",
                b"alpha beta gamma delta epsilon",
                "text/plain",
            )
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ready"
    assert body["chunk_count"] > 1

    chunks_response = client.get(
        f"/api/v1/documents/{body['id']}/chunks",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert chunks_response.status_code == 200
    chunks = chunks_response.json()
    assert len(chunks) == body["chunk_count"]
    assert [chunk["chunk_index"] for chunk in chunks] == list(range(body["chunk_count"]))


def test_upload_document_requires_authentication(tmp_path: Path, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path))

    response = client.post(
        "/api/v1/documents",
        files={
            "file": (
                "policy.txt",
                b"Backups run every night.",
                "text/plain",
            )
        },
    )

    assert response.status_code == 401
    assert not list(tmp_path.iterdir())


def test_upload_rejects_unsupported_content_type(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path))
    token = get_access_token()

    response = client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={
            "file": (
                "notes.md",
                b"# Notes",
                "text/markdown",
            )
        },
    )

    assert response.status_code == 415
    assert not list(tmp_path.iterdir())


def test_upload_rejects_files_over_size_limit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path))
    monkeypatch.setattr(settings, "max_upload_size_bytes", 4)
    token = get_access_token()

    response = client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={
            "file": (
                "policy.txt",
                b"too large",
                "text/plain",
            )
        },
    )

    assert response.status_code == 413
    assert not list(tmp_path.iterdir())


def test_upload_marks_unextractable_pdf_failed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path))
    token = get_access_token()

    response = client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={
            "file": (
                "scan.pdf",
                b"not a real pdf",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert body["chunk_count"] == 0
    assert body["ingestion_error"]

    chunks_response = client.get(
        f"/api/v1/documents/{body['id']}/chunks",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert chunks_response.status_code == 200
    assert chunks_response.json() == []


def test_delete_document_removes_metadata_and_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path))
    token = get_access_token()
    document = upload_txt_document(token)

    stored_files = list(tmp_path.iterdir())
    assert len(stored_files) == 1
    assert stored_files[0].exists()

    response = client.delete(
        f"/api/v1/documents/{document['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 204
    assert response.content == b""
    assert not stored_files[0].exists()

    list_response = client.get(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert list_response.status_code == 200
    assert list_response.json() == []

    chunks_response = client.get(
        f"/api/v1/documents/{document['id']}/chunks",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert chunks_response.status_code == 404


def test_delete_document_requires_authentication() -> None:
    response = client.delete("/api/v1/documents/1")

    assert response.status_code == 401


def test_delete_document_hides_other_users_document(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path))
    owner_token = get_access_token()
    other_token = get_access_token()
    document = upload_txt_document(owner_token)

    response = client.delete(
        f"/api/v1/documents/{document['id']}",
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert response.status_code == 404
    assert len(list(tmp_path.iterdir())) == 1


def test_list_document_chunks_hides_other_users_document(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path))
    owner_token = get_access_token()
    other_token = get_access_token()
    document = upload_txt_document(owner_token)

    response = client.get(
        f"/api/v1/documents/{document['id']}/chunks",
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert response.status_code == 404
