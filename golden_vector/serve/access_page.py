"""Small self-contained sign-in page; no research data before authentication."""

from html import escape


def login_page(*, csrf: str, email: str = "", error: str = "") -> str:
    feedback = f'<p class="access-error" role="alert">{escape(error)}</p>' if error else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in · Golden Vector</title>
<link rel="stylesheet" href="/static/workspace.css"></head>
<body class="access-body"><main class="access-card">
<p class="access-brand">GOLDEN VECTOR</p><p class="access-kicker">Gold-equities research</p>
<h1>Welcome back.</h1><p>Enter your email and the access code you were given.</p>
{feedback}
<form method="post" action="/login">
<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">
<label for="email">Email address</label>
<input id="email" name="email" type="email" autocomplete="username" required maxlength="254"
 value="{escape(email, quote=True)}" spellcheck="false">
<label for="code">Access code</label>
<input id="code" name="code" type="password" autocomplete="current-password" required maxlength="128">
<button type="submit">Open Golden Vector <span aria-hidden="true">→</span></button>
</form><p class="access-footnote">Access is by invitation. Need a code? Contact the person who invited you.</p>
</main></body></html>"""


def access_message(title: str, message: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · Golden Vector</title><link rel="stylesheet" href="/static/workspace.css">
</head><body class="access-body"><main class="access-card"><p class="access-brand">GOLDEN VECTOR</p>
<h1>{escape(title)}</h1><p>{escape(message)}</p><a href="/">Return to Golden Vector</a>
</main></body></html>"""
