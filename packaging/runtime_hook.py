"""PyInstaller runtime hook: point SSL to bundled cacert.pem.

certifi.where() uses importlib.resources.path() on Python 3.10 which can fail
in PyInstaller's frozen importer when certifi's code is in PYZ but cacert.pem
is on the filesystem. Setting these env vars bypasses certifi entirely.
"""

import os
import sys

_cacert = os.path.join(sys._MEIPASS, "certifi", "cacert.pem")
if os.path.isfile(_cacert):
    os.environ.setdefault("SSL_CERT_FILE", _cacert)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", _cacert)
