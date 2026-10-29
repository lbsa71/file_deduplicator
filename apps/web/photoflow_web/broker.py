"""Narrow root PAM broker, isolated from the HTTP application."""

import ctypes as C, ctypes.util, json, os, pwd, socket, socketserver, struct


class Message(C.Structure):
    _fields_ = [("style", C.c_int), ("text", C.c_char_p)]


class Response(C.Structure):
    _fields_ = [("text", C.c_void_p), ("code", C.c_int)]


Callback = C.CFUNCTYPE(
    C.c_int,
    C.c_int,
    C.POINTER(C.POINTER(Message)),
    C.POINTER(C.POINTER(Response)),
    C.c_void_p,
)


class Conversation(C.Structure):
    _fields_ = [("callback", Callback), ("data", C.c_void_p)]


def pam_check(username, password=None):
    pam = C.CDLL(ctypes.util.find_library("pam"))
    libc = C.CDLL(ctypes.util.find_library("c"))
    libc.calloc.restype = C.c_void_p
    libc.strdup.restype = C.c_void_p
    libc.strdup.argtypes = [C.c_char_p]

    @Callback
    def callback(n, messages, out, data):
        ptr = libc.calloc(n, C.sizeof(Response))
        responses = C.cast(ptr, C.POINTER(Response))
        for i in range(n):
            style = messages[i].contents.style
            if style not in (1, 2, 3, 4) or (style == 1 and password is None):
                return 19
            if style in (1, 2):
                responses[i].text = libc.strdup(
                    (password if style == 1 else username).encode()
                )
        out[0] = responses
        return 0

    conv = Conversation(callback, None)
    handle = C.c_void_p()
    result = pam.pam_start(
        b"photoflow-web", username.encode(), C.byref(conv), C.byref(handle)
    )
    try:
        if result == 0 and password is not None:
            result = pam.pam_authenticate(handle, 1)
        if result == 0:
            result = pam.pam_acct_mgmt(handle, 0)
        return result == 0
    finally:
        if handle:
            pam.pam_end(handle, result)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        _, uid, _ = struct.unpack(
            "3i", self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        )
        if uid != int(os.environ["PHOTOFLOW_WEB_UID"]):
            return
        try:
            d = json.loads(self.rfile.readline(4097))
            name = d["username"]
            password = d.get("password")
            if (
                not isinstance(name, str)
                or len(name) > 256
                or (
                    password is not None
                    and (not isinstance(password, str) or len(password) > 1024)
                )
            ):
                raise ValueError()
            account = pwd.getpwnam(name)
            ok = account.pw_uid != 0 and pam_check(name, password)
            if password is None:
                ok = ok and d.get("uid") == account.pw_uid
            self.wfile.write(
                json.dumps(
                    {
                        "ok": ok,
                        "username": name if ok else None,
                        "uid": account.pw_uid if ok else None,
                    }
                ).encode()
                + b"\n"
            )
        except Exception:
            self.wfile.write(b'{"ok":false}\n')


def main():
    path = os.environ.get("PHOTOFLOW_AUTH_SOCKET", "/run/photoflow-auth/auth.sock")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.unlink(path)
    with socketserver.UnixStreamServer(path, Handler) as server:
        os.chmod(path, 0o660)
        os.chown(path, 0, int(os.environ["PHOTOFLOW_WEB_GID"]))
        server.serve_forever()


if __name__ == "__main__":
    main()
