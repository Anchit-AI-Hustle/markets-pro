# Sign-in

Signing in is optional and additive. Without it the app works exactly as it
always has: capital settings and the paper book live in `localStorage`, on one
browser. Signing in mirrors those two documents to the reader's account so a
second device opens on the same setup. Nothing else is stored, and the account
is not a broker connection — no real money can move through it.

## Where it lives

| | |
|---|---|
| Project | `petmind` (`wvnqyegqxgvjbgqujyom`), ap-south-1 |
| API origin | `https://wvnqyegqxgvjbgqujyom.supabase.co` |
| Tables | `public.mp_state` only |
| Auth users | shared `auth.users` for the project |

**This project is shared with another application.** It was chosen over a
dedicated project because a new Supabase project costs $10/month on the Pro
plan, and this one had zero auth users and an untouched auth configuration, so
there was nothing to collide with. Everything Markets Pro owns is prefixed
`mp_`. The consequence to be aware of: if the other application ever adds
sign-in, the two will share one user table. Moving to a dedicated project later
means creating one, re-running `supabase/migrations/`, and changing two lines
— the `supabase` block in `config/live.json` and the `connect-src` origin in
`vercel.json`.

## How it works

The page's CSP allows inline script and nothing else, so `supabase-js` cannot
be loaded. `src/autotrader/web/auth.py` talks to the Supabase Auth REST API
with `fetch` and the publishable key instead. The only policy change required
is the project origin in `connect-src`.

Those two files have to agree, and nothing else keeps them in step, so
`autotrader.web.build.check_csp_allows` **fails the build** when they drift.
That is deliberate: a mismatch breaks every sign-in in production and nowhere
else. A failed build leaves the previous deployment serving.

Which methods are offered is decided at page load, not at build time. The page
reads `/auth/v1/settings`, a public endpoint that reports the providers the
project actually has enabled, and renders only those. Enabling a provider
therefore takes effect on the next page load with no redeploy, and a provider
nobody has configured never renders a button that could only fail.

## Providers

**Email (on).** Supabase sends a six-digit code from its own mailer, with a
sign-in link below it as a fallback. Free, no third-party account. The shared
mailer is rate limited and is fine for personal use; a real user base needs
custom SMTP configured in the Supabase dashboard.

Two templates carry that code, and both have to. The first sign-in from an
address Supabase has not seen is a **signup**, which sends `confirmation`;
`magic_link` is only used once the account exists. Customising just one leaves
half the readers — and specifically every new one — with the stock link-only
mail and a code screen they cannot satisfy. Both live in
`supabase/templates/`.

**Google (off).** Free, but the credentials must be created first:

1. Google Cloud Console → APIs & Services → Credentials → Create OAuth client
   ID → Web application.
2. Authorised redirect URI:
   `https://wvnqyegqxgvjbgqujyom.supabase.co/auth/v1/callback`
3. Supabase dashboard → Authentication → Providers → Google → paste the client
   ID and secret, enable.

The button appears by itself on the next page load.

**Phone (off).** Supabase has no SMS of its own — every message is sent by a
third party and billed per message, roughly ₹0.20–0.75 in India. It stays off
until a Twilio (or MessageBird / Vonage) account with credit is configured
under Authentication → Providers → Phone. The client code is already written;
enabling the provider is the whole remaining step.

## Data

`public.mp_state` is one row per (user, document), with row-level security
allowing a user to touch only their own rows — verified against a second
account, not assumed. `updated_at` is set by a trigger, never by the client,
because the client is the party with an interest in claiming its copy is the
newer one.

On sign-in the two copies are reconciled once: the account's copy wins if it is
newer than the last copy this browser is known to have sent, otherwise this
browser uploads. A device that has never synced has no claim to be newer, so a
fresh phone inherits rather than overwrites.

Signing out clears the session and leaves both copies alone — the local one and
the account one. Losing a paper portfolio to a sign-out button would be a
surprising way to lose it.

## Configuration

`config/live.json`:

```json
"supabase": {
  "url": "https://<ref>.supabase.co",
  "anon_key": "sb_publishable_..."
}
```

`SUPABASE_URL` and `SUPABASE_ANON_KEY` override it, so a deploy can point
elsewhere without a commit. Both halves must be present or sign-in is omitted
entirely: half a configuration would draw a button that cannot authenticate.

The publishable key is meant to be public — it identifies the project and
grants nothing on its own. Row-level security, not the key, is what protects
the data.

Auth settings themselves are recorded in `supabase/config.toml`. Read the
comment at the top of that file before running `supabase config push`: it
sends the whole file, on a project that is not exclusively ours.
