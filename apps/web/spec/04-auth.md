# Linux login and access

## Identity

AUTH-01 uses a dedicated PAM service named `photoflow-web` with the host's
configured password/account policy. Call `pam_authenticate` with empty passwords
disallowed, then `pam_acct_mgmt`. Deny expired accounts and passwords requiring a
change; direct users to the normal Linux password-management channel. Successful
password verification alone is insufficient. See the upstream manuals for
[authentication](https://www.man7.org/linux/man-pages/man3/pam_authenticate.3.html)
and [account validation](https://www.man7.org/linux/man-pages/man3/pam_acct_mgmt.3.html).

Implement a small privileged authentication broker on a Unix socket. Only the
web-service UID may connect, verified using socket peer credentials. Its bounded
request schema supports `authenticate(username,password)` and
`check_account(canonical_username,uid)` for the fixed PAM service. Account checks
perform fresh NSS identity resolution and password-free PAM account validation;
deleted accounts or a changed username/UID binding deny the session. It exposes
no command execution, user-supplied service name, filesystem path, or shell.
Return authenticated canonical username and UID, or a generic denial. The HTTP
server, coordinator, and media decoders run without root/shadow access.

Do not invoke `unix_chkpwd` directly; it is an internal PAM helper with current-user
restrictions. See [unix_chkpwd](https://www.man7.org/linux/man-pages/man8/unix_chkpwd.8.html).
Deployment tests must prove actual non-service Linux-user login through the broker.
Unexpected interactive PAM prompts/MFA are unsupported in this username/password
release and fail closed rather than being silently bypassed.

## Authorization

Default configurable group names:

| Group | Role and capability |
| --- | --- |
| `photoflow-readers` | Browse, search, previews, original/batch download, read metadata |
| `photoflow-editors` | Reader plus upload, edits, folder CRUD, trash/restore, scoped reconcile |
| `photoflow-admins` | Editor plus full scans/verification, derived rebuilds, purge, operations settings |

Highest role wins; membership in none denies login. Resolve primary and
supplementary groups through NSS. Root login is denied. There is no self-signup
and the GUI does not create accounts, change Linux passwords, or modify groups.
Group names are installer configuration, never automatically granted to `sudo`.

This is a shared library: all admitted readers can see/download all its photos,
including Trash. Per-file Unix ownership does not establish private web access.
The mounted exFAT filesystem uses mount-level ownership/mask settings; see the
[kernel exFAT documentation](https://docs.kernel.org/next/filesystems/exfat.html).
Use an explicitly configured service UID/GID with library write access and enforce
the role model in the API. The deployment must ensure external SMB access has the
intended permissions independently.

## Sessions and browser security

Require HTTPS beyond loopback development. Passwords are passed only in a POST
body to the same-origin server and over the local broker socket; never persist
them or include them in URLs, analytics, logs, exception reports, or command
arguments. Bound credential/request lengths and authentication concurrency.

Use random opaque server-side sessions, storing only a token hash, UID, username,
timestamps and authorization state. Cookie: `__Host-photoflow`, Secure, HttpOnly,
SameSite=Lax, Path=/, no Domain. Rotate on login; revoke on logout. Default idle
expiry 30 minutes, absolute expiry 12 hours; no remember-me initially. Long-lived
streams must revalidate session expiry and stop delivery when revoked.

Check current role/group membership for every mutation, including job execution;
read authorization caches expire within 60 seconds. Revalidate PAM account status
at most 60 seconds apart for active sessions. Group removal or account-policy denial
revokes access within that bound. Merely locking a Unix password is not universally
an account-policy denial: administrators must remove the allowed group, expire the
account, or revoke sessions when immediate web removal is intended. A password
change alone need not revoke an existing
session. Provide administrator session revocation. Restart may invalidate sessions
without data loss. Thumbnail cache hits still require authorization.

Require CSRF tokens plus same-origin Origin/Referer validation for mutations;
protect login against cross-site submission too. No wildcard credentialed CORS.
Use a restrictive content security policy and escape imported metadata. Login
returns the same outward message for unknown user, wrong password, expired account,
or missing role. Throttle by source and normalized username: default 5 failed
attempts/minute per pair, 30/minute per source, bounded backoff, no permanent
automatic account lock. Broker failures deny authentication and are observable.

If account revalidation is due and the broker is unavailable, suspend requests
with 503 until validation succeeds; retain the session until its normal expiry.
An explicit account-policy denial revokes it. Never extend the authorization
cache indefinitely because the broker is down.

Every API route, media range request, event stream, export, and thumbnail lookup
enforces authorization. Signed public media URLs are out of scope. Clear UI state
and image references on logout; do not promise to revoke bytes a user downloaded.
Administrative access/audit logs are bounded and redact secrets.
