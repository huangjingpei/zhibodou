import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QLineEdit

from ui.login_window import LoginWindow


class LoginWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def setUp(self):
        self.window = LoginWindow()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    @patch.dict(os.environ, {"PDK_CARD_KEY": "SHOULD-NOT-BE-SENT"}, clear=False)
    def test_regular_login_never_implicitly_sends_environment_card_key(self):
        calls = []
        self.window.login_phone.setText("13800138000")
        self.window.login_password.setText("password")
        self.window._start_auth = lambda phone, password, card_key="": calls.append(
            (phone, password, card_key))

        self.window._do_login()

        self.assertEqual([("13800138000", "password", "")], calls)

    def test_activation_card_key_is_masked(self):
        self.assertEqual(QLineEdit.Password, self.window.act_card.edit.echoMode())


if __name__ == "__main__":
    unittest.main()
