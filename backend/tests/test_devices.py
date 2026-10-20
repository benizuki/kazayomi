"""デバイスの登録と認証。Kazami と同じ手順（P-256 の鍵・署名）で確かめる。"""
from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from domain import devices
from domain.devices import DeviceAuthError
from tests.conftest import make_room


class FakeKazami:
    """端末側。鍵を作り、登録と認証の署名をする。"""

    def __init__(self, device_id: str = "A1B2C3D4-0000-1111-2222-333344445555"):
        self.device_id = device_id
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.public = self.key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)

    def sign(self, message: bytes) -> str:
        return base64.b64encode(self.key.sign(message, ec.ECDSA(hashes.SHA256()))).decode()

    def enroll_payload(self, token: str) -> dict:
        return {
            "token": token,
            "device_id": self.device_id,
            "device_pub": base64.b64encode(self.public).decode(),
            "signature": self.sign(devices.enroll_message(token, self.device_id, self.public)),
        }

    def login(self) -> dict:
        challenge = devices.issue_challenge({"device_id": self.device_id})["challenge"]
        return devices.issue_token(
            {"device_id": self.device_id, "signature": self.sign(devices.auth_message(challenge, self.device_id))},
            ttl_seconds=60, default_signaling_url="ws://default/signaling",
        )


def _enrolled(name: str = "端末1", room_id: str | None = None) -> tuple[dict, FakeKazami]:
    device = devices.create_device({"name": name, "room_id": room_id})
    kazami = FakeKazami()
    devices.enroll(kazami.enroll_payload(devices.issue_enrollment(device["id"])["token"]))
    return devices.get_device(device["id"]), kazami


def test_enroll_then_login_returns_room_config():
    room = make_room("ライン1", "line-1")
    device, kazami = _enrolled(room_id=room["id"])
    assert device["enrolled"] and device["device_id"] == kazami.device_id

    config = kazami.login()
    assert config["room"] == {"id": room["id"], "name": "ライン1", "ayame_room_id": "line-1"}
    assert config["signaling_url"] == room["signaling_url"]
    assert config["signaling_key"] == config["access_token"]
    assert devices.resolve_access_token(config["access_token"])["id"] == device["id"]


def test_enrollment_token_is_single_use_and_wrong_signature_does_not_consume_it():
    device = devices.create_device({"name": "端末1"})
    token = devices.issue_enrollment(device["id"])["token"]
    kazami = FakeKazami()
    forged = {**kazami.enroll_payload(token), "signature": FakeKazami().sign(b"x")}
    with pytest.raises(DeviceAuthError, match="署名"):
        devices.enroll(forged)
    devices.enroll(kazami.enroll_payload(token))
    with pytest.raises(DeviceAuthError, match="期限が切れているか、使用済み"):
        devices.enroll(FakeKazami("OTHER-1").enroll_payload(token))


def test_device_id_cannot_be_bound_to_two_devices():
    _, kazami = _enrolled("端末1")
    other = devices.create_device({"name": "端末2"})
    token = devices.issue_enrollment(other["id"])["token"]
    with pytest.raises(ValueError, match="別のデバイス「端末1」"):
        devices.enroll(kazami.enroll_payload(token))


def test_login_requires_the_enrolled_key_and_challenge_is_single_use():
    _, kazami = _enrolled()
    challenge = devices.issue_challenge({"device_id": kazami.device_id})["challenge"]
    impostor = FakeKazami(kazami.device_id)  # 同じ ID を名乗る別の鍵
    with pytest.raises(DeviceAuthError, match="署名"):
        devices.issue_token({"device_id": kazami.device_id, "signature": impostor.sign(devices.auth_message(challenge, kazami.device_id))},
                            ttl_seconds=60, default_signaling_url="")
    signature = kazami.sign(devices.auth_message(challenge, kazami.device_id))
    devices.issue_token({"device_id": kazami.device_id, "signature": signature}, ttl_seconds=60, default_signaling_url="")
    with pytest.raises(DeviceAuthError, match="期限"):
        devices.issue_token({"device_id": kazami.device_id, "signature": signature}, ttl_seconds=60, default_signaling_url="")


def test_unknown_device_cannot_get_challenge():
    with pytest.raises(DeviceAuthError, match="登録されていません"):
        devices.issue_challenge({"device_id": "UNKNOWN-1"})
    with pytest.raises(DeviceAuthError, match="形式"):
        devices.issue_challenge({"device_id": "../etc/passwd"})


def test_clearing_enrollment_revokes_tokens():
    device, kazami = _enrolled()
    token = kazami.login()["access_token"]
    devices.clear_enrollment(device["id"])
    assert devices.resolve_access_token(token) is None
    with pytest.raises(DeviceAuthError, match="登録されていません"):
        kazami.login()


def test_device_without_room_gets_default_signaling_url():
    _, kazami = _enrolled()
    config = kazami.login()
    assert config["room"] is None
    assert config["signaling_url"] == "ws://default/signaling"


def test_device_upload_goes_to_assigned_room_and_group():
    from domain import captures
    from domain.captures import CaptureAuthError
    from tests.conftest import make_group, make_jpeg

    make_group("line")
    room = make_room("ライン1", "line-1", "line")
    device, kazami = _enrolled("端末1", room["id"])
    token = kazami.login()["access_token"]
    record = captures.accept_device_upload(token, make_jpeg(), captured_at="2026-10-17T10:00:00+09:00", source_name="a.jpg")
    assert (record["room_id"], record["group_id"], record["captured_by"]) == (room["id"], "line", "device:端末1")

    with pytest.raises(CaptureAuthError):
        captures.accept_device_upload("bogus", make_jpeg(), captured_at=None, source_name="")
    devices.clear_enrollment(device["id"])
    with pytest.raises(CaptureAuthError):
        captures.accept_device_upload(token, make_jpeg(), captured_at=None, source_name="")


def test_device_upload_requires_a_room():
    from domain import captures
    from tests.conftest import make_jpeg

    _, kazami = _enrolled("端末1")
    with pytest.raises(ValueError, match="ルームが割り当てられていません"):
        captures.accept_device_upload(kazami.login()["access_token"], make_jpeg(), captured_at=None, source_name="")
