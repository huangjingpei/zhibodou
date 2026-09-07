import os
import unittest
from unittest.mock import patch

from pdk import auth_service
from pdk.pdk_client import PdkClientError


class FakeClient:
    def __init__(self, _base_url, app_id, phone="", **_kwargs):
        self.app_id = app_id
        self.phone = phone
        self.logged_in = False
        self.closed = False
        self.logout_count = 0
        self.calls = []
        self.timeout = None
        self.on_http = None

    @property
    def is_logged_in(self):
        return self.logged_in

    def fetch_public_config(self):
        self.calls.append("fetch_public_config")
        return {"encryptionMode": "force", "kid": "v1"}

    def business_info(self):
        self.calls.append("business_info")
        return {
            "bizCode": "ZHIBO_LIVE",
            "authorizationMode": "DEVICE_LICENSE",
            "effectiveStatus": "AVAILABLE",
            "configuredStatus": "ACTIVE",
            "liveMedia": {
                "enabled": True,
                "status": "AVAILABLE",
                "mediaServerAddress": "rtmp://127.0.0.1:1935",
                "preferredPublishProtocol": "RTMP",
            },
        }

    def login(self, password, **kwargs):
        self.calls.append(("login", password, kwargs.get("card_key", "")))
        self.logged_in = True
        return {"tokenName": "satoken", "tokenValue": "secret", "appId": self.app_id}

    def verify_session(self):
        self.calls.append("verify_session")
        return {
            "sessionValid": True,
            "operationAllowedHint": True,
            "authorizationMode": "DEVICE_LICENSE",
            "bizCode": "ZHIBO_LIVE",
            "status": "ACTIVE",
            "expireAt": "2099-12-31T23:59:59",
        }

    def profile(self):
        self.calls.append("profile")
        return {"remainingCalls": 12, "status": "ACTIVE"}

    def device_license_current(self):
        self.calls.append("device_license_current")
        return {"status": "ACTIVE", "expireAt": "2099-12-31T23:59:59"}

    def logout(self):
        self.calls.append("logout")
        self.logout_count += 1
        self.logged_in = False
        return "ok"

    def clear_session(self):
        self.logged_in = False

    def close(self):
        self.closed = True


class SubscriptionClient(FakeClient):
    def business_info(self):
        info = super().business_info()
        info["authorizationMode"] = "USER_SUBSCRIPTION"
        return info

    def verify_session(self):
        result = super().verify_session()
        result["authorizationMode"] = "USER_SUBSCRIPTION"
        return result


class DisabledSessionClient(FakeClient):
    def verify_session(self):
        result = super().verify_session()
        result["operationAllowedHint"] = False
        result["status"] = "EXPIRED"
        return result


class DisabledLicenseClient(FakeClient):
    def device_license_current(self):
        self.calls.append("device_license_current")
        return {"status": "EXPIRED", "expireAt": "2026-01-01T00:00:00"}


class NoMediaNodeClient(FakeClient):
    def business_info(self):
        info = super().business_info()
        info["liveMedia"] = {"enabled": False, "status": "NO_AVAILABLE_NODE"}
        return info


SETTINGS = auth_service.PdkSettings(
    base_url="https://pdk.example.test",
    app_id=3,
    public_key_pin="fingerprint",
    require_https=True,
)


class PdkAuthServiceTests(unittest.TestCase):
    def tearDown(self):
        try:
            auth_service.logout()
        except Exception:
            pass

    @staticmethod
    def _factory(client_type, created):
        def factory(*args, **kwargs):
            client = client_type(*args, **kwargs)
            created.append(client)
            return client
        return factory

    def test_device_license_login_calls_complete_contract(self):
        created = []
        result = auth_service.authenticate(
            "13800138000", "password", "CARD-KEY", settings=SETTINGS,
            client_factory=self._factory(FakeClient, created),
        )
        self.assertTrue(auth_service.is_authenticated())
        self.assertEqual("DEVICE_LICENSE", result.authorization_mode)
        self.assertEqual("rtmp://127.0.0.1:1935", result.live_media.get("mediaServerAddress"))
        self.assertEqual("138****8000", result.masked_phone)
        self.assertIn(("login", "password", "CARD-KEY"), created[0].calls)
        self.assertIn("device_license_current", created[0].calls)
        self.assertIsNone(created[0].on_http)

    def test_subscription_skips_device_license_endpoint(self):
        created = []
        result = auth_service.authenticate(
            "13800138000", "password", settings=SETTINGS,
            client_factory=self._factory(SubscriptionClient, created),
        )
        self.assertEqual("USER_SUBSCRIPTION", result.authorization_mode)
        self.assertNotIn("device_license_current", created[0].calls)

    def test_invalid_session_is_logged_out_closed_and_not_published(self):
        created = []
        with self.assertRaises(PdkClientError):
            auth_service.authenticate(
                "13800138000", "password", settings=SETTINGS,
                client_factory=self._factory(DisabledSessionClient, created),
            )
        self.assertFalse(auth_service.is_authenticated())
        self.assertEqual(1, created[0].logout_count)
        self.assertTrue(created[0].closed)

    def test_invalid_device_license_cannot_enter_application(self):
        created = []
        with self.assertRaises(PdkClientError):
            auth_service.authenticate(
                "13800138000", "password", settings=SETTINGS,
                client_factory=self._factory(DisabledLicenseClient, created),
            )
        self.assertFalse(auth_service.is_authenticated())
        self.assertTrue(created[0].closed)

    def test_live_business_requires_public_media_node(self):
        created = []
        with self.assertRaises(PdkClientError) as ctx:
            auth_service.authenticate(
                "13800138000", "password", "CARD", settings=SETTINGS,
                client_factory=self._factory(NoMediaNodeClient, created),
            )
        self.assertEqual(50372, ctx.exception.code)
        self.assertFalse(auth_service.is_authenticated())
        self.assertTrue(created[0].closed)

    def test_verify_current_session_refreshes_snapshot(self):
        created = []
        auth_service.authenticate(
            "13800138000", "password", "CARD", settings=SETTINGS,
            client_factory=self._factory(FakeClient, created),
        )
        refreshed = auth_service.verify_current_session()
        self.assertEqual("ACTIVE", refreshed.status)
        self.assertEqual(2, created[0].calls.count("verify_session"))

    def test_logout_clears_runtime_when_remote_logout_fails(self):
        class LogoutFailureClient(FakeClient):
            def logout(self):
                raise PdkClientError(0, "network down")

        created = []
        auth_service.authenticate(
            "13800138000", "password", "CARD", settings=SETTINGS,
            client_factory=self._factory(LogoutFailureClient, created),
        )
        auth_service.logout()
        self.assertFalse(auth_service.is_authenticated())
        self.assertTrue(created[0].closed)

    @patch.dict(os.environ, {
        "PDK_BASE_URL": "https://license.example.com",
        "PDK_APP_ID": "9",
        "PDK_REQUIRE_HTTPS": "true",
        "PDK_VERIFY_TLS": "false",
        "PDK_HTTP_DEBUG": "true",
    }, clear=True)
    def test_settings_are_loaded_from_environment(self):
        settings = auth_service.PdkSettings.from_env()
        self.assertEqual(9, settings.app_id)
        self.assertTrue(settings.require_https)
        self.assertFalse(settings.verify_tls)
        self.assertTrue(settings.http_debug)

    @patch.dict(os.environ, {}, clear=True)
    def test_defaults_match_client_demo(self):
        settings = auth_service.PdkSettings.from_env()
        self.assertEqual("http://127.0.0.1:8080", settings.base_url)
        self.assertEqual(3, settings.app_id)
        self.assertFalse(settings.http_debug)


if __name__ == "__main__":
    unittest.main()
