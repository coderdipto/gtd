# Security Policy

## Reporting a vulnerability

Please report security issues privately via GitHub's **"Report a vulnerability"**
button on the repository's **Security** tab (Private Vulnerability Reporting),
rather than opening a public issue. I'll acknowledge as soon as I can.

## Security model — read this before deploying

GTD is a **single-user, self-hosted** application. Its threat model assumes the
person deploying it is the only user, and it takes some deliberate shortcuts on
that basis. If you expose it to the internet or to more than one person, you
need to understand these:

- **No per-user data isolation.** There is no `user` foreign key on tasks,
  notes, projects, etc. Every authenticated session sees *all* data. This is
  not a multi-tenant app — one deployment == one person's data. Do not put two
  people's data in the same instance.
- **Notes render Markdown without HTML sanitization.** `Note.body` is rendered
  to HTML with no sanitizer, which is safe *only* because the sole author and
  sole viewer are the same trusted person. Never point this at untrusted or
  externally-sourced note content — it would be a stored-XSS vector.
- **Set your own `SECRET_KEY`.** The app refuses to boot with `DEBUG=False` if
  `SECRET_KEY` is still the insecure dev default — but set a real one anyway.
- **The ntfy topic is a shared secret.** If you enable notifications, anyone who
  knows your `NTFY_TOPIC` string can read and publish to it. Use a long,
  random topic name and treat it like a password.
- **Attachments are served through an auth-checked view** (never a public
  `/media/` path); keep it that way if you customize the nginx config.

For normal single-user self-hosting, run behind HTTPS with `DEBUG=False`, a real
`SECRET_KEY`, and a correct `ALLOWED_HOSTS`, and you're in good shape.
