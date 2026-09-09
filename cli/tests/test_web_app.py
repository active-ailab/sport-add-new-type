import os
import unittest
from unittest import mock

from sport_config import web_app


class SportConfigWebBrowserTest(unittest.TestCase):
    def test_open_browser_prefers_wslview(self):
        def which(name):
            return "/usr/bin/wslview" if name == "wslview" else None

        with mock.patch.object(web_app.shutil, "which", side_effect=which), \
                mock.patch.object(web_app.subprocess, "Popen") as popen:
            self.assertTrue(web_app._open_browser("http://127.0.0.1:8500"))

        popen.assert_called_once_with(["wslview", "http://127.0.0.1:8500"])

    def test_open_browser_does_not_use_text_browser_over_ssh(self):
        with mock.patch.object(web_app.shutil, "which", return_value=None), \
                mock.patch.object(web_app.webbrowser, "open_new") as open_new, \
                mock.patch.dict(os.environ, {"SSH_CONNECTION": "1"}, clear=False):
            self.assertFalse(web_app._open_browser("http://127.0.0.1:8500"))

        open_new.assert_not_called()

    def test_open_browser_uses_python_fallback_without_ssh(self):
        with mock.patch.object(web_app.shutil, "which", return_value=None), \
                mock.patch.object(web_app.webbrowser, "open_new", return_value=True) as open_new, \
                mock.patch.dict(os.environ, {"DISPLAY": ":0"}, clear=True):
            self.assertTrue(web_app._open_browser("http://127.0.0.1:8500"))

        open_new.assert_called_once_with("http://127.0.0.1:8500")


if __name__ == "__main__":
    unittest.main()
