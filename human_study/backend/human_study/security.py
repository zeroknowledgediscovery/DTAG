"""Anonymous signed browser cookies plus same-origin writes and bounded requests."""
import hashlib
import re
import time
from collections import OrderedDict
from threading import Lock
from urllib.parse import urlsplit

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired


class Sessions:
    def __init__(self, secret, secure):
        self.signer = URLSafeTimedSerializer(secret, salt="dtag-human-v1", signer_kwargs={"digest_method": hashlib.sha256})
        self.secure = secure
        self.cookie = "__Host-dtag-human" if secure else "dtag-human-local"

    def token(self, sid):
        return self.signer.dumps(sid)

    def sid(self, request):
        value = request.cookies.get(self.cookie)
        if not value:
            return None
        try:
            sid = self.signer.loads(value, max_age=7 * 86400)
            return sid if isinstance(sid, str) and re.fullmatch(r"[a-f0-9]{32}", sid) else None
        except (BadSignature, SignatureExpired):
            return None

    def set_cookie(self, response, sid):
        response.set_cookie(self.cookie, self.token(sid), httponly=True, secure=self.secure,
                            samesite="strict", max_age=7 * 86400, path="/")


class Throttle:
    """Basic per-instance abuse cap, not a distributed quota or payment decision."""
    def __init__(self, limit=120, maximum=5000):
        self.limit, self.maximum = limit, maximum
        self.lock = Lock()
        self.counts = OrderedDict()

    def allow(self, key):
        window = int(time.monotonic() // 60)
        with self.lock:
            old_window, count = self.counts.pop(key, (window, 0))
            count = count + 1 if old_window == window else 1
            self.counts[key] = (window, count)
            while len(self.counts) > self.maximum:
                self.counts.popitem(last=False)
            return count <= self.limit
