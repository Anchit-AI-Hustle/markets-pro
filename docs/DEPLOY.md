# Deploying the dashboard

The dashboard is a **single self-contained HTML file** with no external scripts,
styles, fonts or images. That makes deployment deliberately boring: serve one
file at one path.

## Build

```bash
PYTHONPATH=src python3 -m autotrader.web.build --out public
```

This writes `public/markets-pro/index.html`.

## Serving it at `yourdomain.com/markets-pro`

The route is a *path* on an existing site, so it has to be published by whatever
already serves that domain. Three options:

**1. Vercel (matches the included `vercel.json`)**

```bash
vercel --prod
```

The build command produces `public/markets-pro/index.html`, which Vercel serves
at `/markets-pro`. If the domain is already attached to a different Vercel
project, do not create a second project for it — a domain can only point at one.
Instead, copy the built file into that project's `public/markets-pro/` directory
and redeploy it, or add a rewrite from `/markets-pro` to this deployment.

**2. Any static host / existing server**

Copy `public/markets-pro/index.html` to the `/markets-pro` path of the document
root. Nothing else is required.

**3. Local check**

```bash
make serve      # http://localhost:8000/markets-pro
```

The bundled server is for development only — no TLS, no auth, no rate limiting.
Do not expose it directly.

## Sign-in

Optional, and off unless `config/live.json` carries a `supabase` block. The
build prints which it chose:

```
sign-in enabled against https://<ref>.supabase.co
no supabase project configured; the page ships without sign-in
```

The project origin must also appear in the `connect-src` directive in
`vercel.json`, or every sign-in fails once deployed. The build checks this and
stops rather than shipping a page whose own CSP blocks it. See
[AUTH.md](AUTH.md).

## What is not automated

Pointing a domain at a deployment requires DNS and hosting-account access. That
part has to be done by whoever controls the domain; this repo only produces the
file and the route.
