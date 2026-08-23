"""Standalone pages: what this is, who made it, and what it is not permitted to be.

Two audits of this product landed on the same critical finding: it puts trade
suggestions in front of Indian retail investors while carrying no regulatory
disclosure, no terms, no privacy statement and no jurisdiction. That is not a
documentation gap — it is the difference between a personal research tool and
an unregistered advisory service, and the distinction is made by what the page
says about itself.

They also flagged the opposite problem: ``noindex``, no about page, no contact,
nothing trying to be found. Those two findings interact, and the order matters.
Becoming discoverable *before* the disclosures exist would increase exactly the
exposure the first finding names. So these pages come first, and the switch
that makes the site indexable reads from the same config that fills them in.

Separate documents rather than another tab. Eleven is enough, these are read
once rather than daily, and a legal page that can be linked to on its own is
worth more than one buried behind a click.
"""

from __future__ import annotations

from .render import CSS, _esc

#: A page is only published when the build has what it needs to be honest.
#: An about page with a placeholder contact is worse than no about page.
CONTACT_REQUIRED = ("contact",)


def _shell(title: str, subtitle: str, body: str, *, home: str = "/") -> str:
    """One document, sharing the app's stylesheet so it does not look bolted on."""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)} &middot; Markets Pro</title>
<meta name="description" content="{_esc(subtitle)}">
<style>{CSS}
.doc{{max-width:74ch;margin:0 auto;padding:48px 24px 96px}}
.doc h1{{font-size:clamp(1.6rem,4vw,2.3rem);letter-spacing:-.02em;margin:0 0 10px;
  text-transform:none}}
.doc .lede{{color:var(--muted);font-size:1rem;line-height:1.6;margin:0 0 34px}}
.doc h2{{font-size:1.05rem;margin:34px 0 10px;text-transform:none;letter-spacing:-.005em}}
.doc p,.doc li{{line-height:1.68;color:var(--ink)}}
.doc ul{{padding-left:20px}}
.doc li{{margin-bottom:7px}}
.doc .back{{display:inline-block;margin-bottom:28px;font-size:.85rem;color:var(--accent);
  text-decoration:none}}
.doc .back:hover{{text-decoration:underline}}
.doc .updated{{margin-top:44px;padding-top:18px;border-top:1px solid var(--line);
  color:var(--muted);font-size:.82rem}}
.doc .hard{{border:1px solid var(--neg);border-left-width:4px;border-radius:var(--radius);
  padding:18px 20px;margin:24px 0;background:var(--panel)}}
.doc .hard strong{{color:var(--neg)}}
</style>
</head>
<body>
<div class="doc">
  <a class="back" href="{home}">&larr; Markets Pro</a>
  <h1>{_esc(title)}</h1>
  <p class="lede">{subtitle}</p>
  {body}
</div>
</body>
</html>"""


def disclosures(config: dict | None = None) -> str:
    """The regulatory position, stated plainly rather than implied by absence."""
    contact = (config or {}).get("contact", "")
    contact_line = (
        f'<p>Questions about anything on this page: <a href="mailto:{_esc(contact)}">'
        f"{_esc(contact)}</a>.</p>"
        if contact else
        "<p>No contact address is published for this build.</p>"
    )
    body = f"""
<div class="hard">
  <p><strong>This is not investment advice, and the person who built it is not
  registered to give any.</strong></p>
  <p>Markets Pro is not registered with the Securities and Exchange Board of India
  as a Research Analyst under the SEBI (Research Analysts) Regulations, 2014, nor
  as an Investment Adviser under the SEBI (Investment Advisers) Regulations, 2013,
  nor with any equivalent authority in the United States or elsewhere.</p>
  <p>Nothing here is a recommendation, a solicitation, or advice of any kind,
  personalised or otherwise. No fee, commission or other consideration is charged
  for anything on this site.</p>
</div>

<h2>What this actually is</h2>
<p>A rule-based research tool. It applies four published rules to end-of-day
prices and shows what survives them, together with the entry, the target, the
stop and the exact amount of money at risk. The rules are printed in full, so
there is nothing discretionary being sold &mdash; you can reproduce every figure
from the same public price data.</p>

<h2>The record, stated up front</h2>
<p>The strategies' published track record is <strong>negative</strong>. Over the
period tested they returned less than nothing after costs, with a profit factor
below 1 and long runs of consecutive losses. Separately, an evidence study ran
975 statistical tests across 325 instruments over roughly twenty years and found
fewer rules clearing significance than chance alone would produce &mdash; that is
the absence of an edge, measured, not a near miss.</p>
<p>Those figures are on the site because they are true, not because they help.
Anyone using this should assume the rules do not work until evidence says
otherwise.</p>

<h2>Risk</h2>
<ul>
  <li>Equity investing can lose money, including your entire capital.</li>
  <li>Past performance &mdash; including every backtest and figure on this site
      &mdash; does not predict future results.</li>
  <li>Prices are end-of-day and may be delayed, wrong, or missing. Corporate
      actions and data errors are not always caught.</li>
  <li>Every decision to buy or sell is yours alone. This site places no orders
      and holds no money.</li>
</ul>

<h2>No brokerage relationship</h2>
<p>Markets Pro is not a broker, dealer, custodian or payment service. Where it
offers to hand an order to your broker, the order is reviewed and confirmed by
you inside your broker's own interface, under your own credentials. Broker
integrations are inactive unless you supply your own API keys, and even then
order placement is disabled unless explicitly armed.</p>

<h2>Jurisdiction</h2>
<p>This site is operated from India and these terms are governed by Indian law.
It is not directed at, and should not be relied on by, anyone in a jurisdiction
where its publication or use would be unlawful.</p>

{contact_line}
"""
    return _shell(
        "Disclosures and terms",
        "The regulatory position, the risks, and what this site is not.",
        body,
    )


def privacy(config: dict | None = None) -> str:
    """What is stored, where, and what is deliberately not collected."""
    contact = (config or {}).get("contact", "")
    contact_line = (
        f'<p>Requests about your data: <a href="mailto:{_esc(contact)}">'
        f"{_esc(contact)}</a>.</p>" if contact else ""
    )
    body = f"""
<p>Most of this site stores nothing anywhere but your own browser. The parts that
do are listed below in full.</p>

<h2>Without an account</h2>
<ul>
  <li>Your capital and daily-limit settings, and your paper trades, are kept in
      this browser's local storage. They are never sent anywhere. Clearing site
      data deletes them.</li>
  <li>Nothing identifies you. There is no advertising, no third-party tracker and
      no cookie used for tracking.</li>
</ul>

<h2>With an account</h2>
<ul>
  <li>Signing in stores your email address (or phone number, if you use that
      method) and an authentication token, so the same settings appear on another
      device.</li>
  <li>Two documents are copied to your account: your capital and cap settings, and
      your paper book. Nothing else.</li>
  <li>Authentication and that storage are provided by Supabase. Row-level security
      means your rows are readable only by you.</li>
  <li>Signing out leaves both copies in place. Ask and they will be deleted.</li>
</ul>

<h2>If you connect a broker</h2>
<ul>
  <li>The access token your broker issues is stored server-side only, in a table
      the site's own public key cannot read. It never reaches the browser.</li>
  <li>Your broker password, PIN or one-time code is never seen by this site. You
      enter those on your broker's own domain.</li>
  <li>Indian brokers expire API access daily by regulation, so a connection lasts
      one trading day.</li>
</ul>

<h2>Usage counting</h2>
<p>Feature counts are recorded so it is possible to tell which parts of the site
anyone uses. One row per day per feature, with a number on it. No identifier, no
session, no IP address, no page path and no cookie &mdash; there is nothing in it
that could be traced back to a person. Client-side errors are recorded with the
message and browser family so a broken release is visible.</p>

<h2>What is never collected</h2>
<ul>
  <li>Your broker credentials, holdings or balances, unless you explicitly connect
      a broker &mdash; and then only server-side.</li>
  <li>Any payment information. Nothing is sold here.</li>
  <li>Your location, contacts, or anything from other sites.</li>
</ul>
{contact_line}
"""
    return _shell("Privacy", "What is stored, where, and what is not collected.", body)


def about(config: dict | None = None) -> str:
    """Who built it and why — the audits noted its absence."""
    settings = config or {}
    contact = settings.get("contact", "")
    author = settings.get("author", "")
    repo = settings.get("repo", "")
    lines = []
    if author:
        lines.append(f"<p>Built by {_esc(author)}.</p>")
    if contact:
        lines.append(
            f'<p>Contact: <a href="mailto:{_esc(contact)}">{_esc(contact)}</a></p>')
    if repo:
        lines.append(
            f'<p>Source: <a href="{_esc(repo)}" rel="noopener">{_esc(repo)}</a></p>')
    attribution = "\n".join(lines) or "<p>No author details are published for this build.</p>"

    body = f"""
<p>Markets Pro applies four published rules to end-of-day prices for 325 Indian
and US listings, and shows only what survives them &mdash; with the entry, the
target, the stop, and the exact money at risk written down before you act.</p>

<h2>Why it looks like this</h2>
<p>Retail market tools sell conviction and bury the record. This one inverts that:
the win rate, the worst drawdown, the longest losing streak and the period return
sit on the same screen as the suggestion, and the evidence study that found no
edge is a tab rather than a footnote. That is the whole design.</p>

<h2>How it works</h2>
<ul>
  <li>A scheduled job fetches closing prices after each market close, commits them,
      and that commit rebuilds this site. There is no server kept running between
      times, and no model &mdash; every figure is arithmetic on public prices.</li>
  <li>Indicators are recomputed from raw bars each time rather than carried over.</li>
  <li>Only completed sessions are used, so no rule is ever evaluated against a
      price that had not settled.</li>
  <li>An absent fundamental is shown as absent. Nothing here is estimated,
      smoothed or inferred to fill a gap.</li>
</ul>

<h2>What it is not</h2>
<ul>
  <li>Not advice, and not registered research. See
      <a href="/disclosures.html">disclosures</a>.</li>
  <li>Not a broker. It holds no money and places nothing by itself.</li>
  <li>Not a tips service &mdash; the rules are printed in full.</li>
  <li>Not a profit promise. The published record is negative.</li>
</ul>

<h2>Who</h2>
{attribution}
"""
    return _shell("About", "What this is, how it works, and who built it.", body)


def robots(*, indexable: bool, site: str) -> str:
    """Robots policy, matching whatever the build actually decided.

    Written from the same flag the page's meta tag reads, so the two cannot
    disagree — a site that says one thing in a meta tag and another in
    robots.txt is a site that gets indexed by accident.
    """
    if not indexable:
        return (
            "# This build is deliberately not indexed. Disclosures and terms are\n"
            "# published, but the decision to be discoverable has not been taken.\n"
            "User-agent: *\nDisallow: /\n"
        )
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "# Sidecars are data, not pages.\n"
        "Disallow: /d/\n"
        "Disallow: /api/\n"
        f"\nSitemap: {site}/sitemap.xml\n"
    )


def sitemap(*, site: str, pages: tuple[str, ...]) -> str:
    site = site.rstrip("/")
    urls = "".join(
        f"\n  <url><loc>{site}{path}</loc></url>" for path in pages
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}\n</urlset>\n"
    )
