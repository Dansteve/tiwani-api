# Auth email templates

The canonical, version-controlled source for the emails Supabase Auth sends on TIWANI's behalf. Edit
the HTML here, then apply it to the project (see below). Keeping the source in the repo means the
branded email is reviewed like any other change and never drifts silently in a dashboard. All six share
one layout (wordmark, white card, calm teal action, footer); only the copy, the action, and the
variables differ.

| File | Supabase template | Sent when | Key variables |
| --- | --- | --- | --- |
| `confirmation.html` | Confirm signup | A new email + password sign-up confirms their address | `{{ .ConfirmationURL }}` |
| `invite.html` | Invite user | Someone is invited to create an account | `{{ .ConfirmationURL }}` |
| `magic_link.html` | Magic Link / OTP | A passwordless sign-in link or one-time code is requested | `{{ .ConfirmationURL }}`, `{{ .Token }}` |
| `email_change.html` | Change email address | A user verifies a new email after changing it | `{{ .ConfirmationURL }}`, `{{ .NewEmail }}` |
| `recovery.html` | Reset password | A password reset link is requested | `{{ .ConfirmationURL }}` |
| `reauthentication.html` | Reauthentication | A one-time code to confirm a sensitive action | `{{ .Token }}` (code only, no link) |

The app triggers **Confirm signup** (`supabase.auth.signUp`) and **Reset password**
(`resetPasswordForEmail`) today; Google sign-in is already verified by Google, so it sends no
confirmation. Invite, magic link, change email, and reauthentication are not wired by the app yet, but
are branded so that if any is ever enabled it is already on-brand rather than the default Supabase HTML.

## Subjects

| Template | Subject |
| --- | --- |
| confirmation | `Confirm your email to get started with TIWANI` |
| invite | `You are invited to join TIWANI` |
| magic_link | `Your TIWANI sign-in link` |
| email_change | `Confirm your new email address for TIWANI` |
| recovery | `Reset your TIWANI password` |
| reauthentication | `Your TIWANI verification code` |

## Brand + voice

Deep Teal (`#04342c` anchor, `#0f6e56` primary action), one sparing Coral dot (`#d85a30`) on the
wordmark, Warm Grey text (`#2c2c2a` / `#5f5e5a`), Inter with a system-sans fallback. One-time codes sit
in a calm teal-tint chip (`#e1f5ee` / `#9fe1cb`), never a coral or alarm colour. The copy is calm, warm,
and strictly **non-clinical**: transactional account emails with zero care, child, or health content.
Colour is never the only signal, and contrast meets WCAG 2.1 AA. Keep it that way
(`governance/Docs/Brand.md`).

## Template variables (GoTrue, Go `html/template`, auto-escaped)

- `{{ .ConfirmationURL }}` the full verify/action URL (its `redirect_to` is the app origin the user came
  from, validated against the Auth **Redirect URLs** allowlist, falling back to the **Site URL**).
- `{{ .Token }}` the 6-digit one-time code (magic link as an alternative to the link; reauthentication
  has no link at all, only the code).
- `{{ .NewEmail }}` the address being moved to (email change only).
- `{{ .Data.first_name }}` the name captured at sign-up (on `auth.users.user_metadata`). Every template
  guards it with `{{ if .Data.first_name }}...{{ else }}Hi there,{{ end }}`, so a flow without it (an
  OAuth or invited user) still reads cleanly.

Other available variables: `{{ .TokenHash }}`, `{{ .SiteURL }}`, `{{ .Email }}`, `{{ .RedirectTo }}`.

## How to apply

### Hosted project (the operative path)

This repo applies schema directly to the hosted Supabase project (no local CLI stack), so the templates
are set in the dashboard, not via `config.toml`. For each row in the table above:

1. Open **Authentication -> Emails -> Templates**
   (`https://supabase.com/dashboard/project/kogpfmuxgfjfjkdwrsjv/auth/templates`) and pick the template.
2. Set its **Subject** from the subjects table.
3. Paste the matching file's full contents into the **Message body**, and Save.
4. For Confirm signup and Reset password (the live flows), trigger the real action and check the email
   renders and the link lands on the app.

The link target depends on **Authentication -> URL Configuration**: set **Site URL** to
`https://app-tiwani.web.app` and add `https://app-tiwani.web.app/**` and `http://localhost:3000/**` to
**Redirect URLs**, or the link falls back to the Site URL.

### Automated deploy (GitHub Actions, the routine path)

`.github/workflows/supabase-email-templates.yml` makes the manual dashboard steps a fallback. On every
push/PR that touches the templates it runs `supabase/validate-email-templates.py` (tag balance, the
required variables per template, brand-only colours, AA, non-clinical). On a push to `main` it runs
`supabase/deploy-email-templates.sh`, which PATCHes ONLY the 12 mailer fields via the Management API
(`/v1/projects/<ref>/config/auth`) and then GETs to verify each body applied. It is **surgical**: it
never touches the Site URL, the redirect allowlist, the Google provider, or the migrations.

To enable it (one-time, owner):

1. Create a Supabase personal access token at `https://supabase.com/dashboard/account/tokens`.
2. Add it as a repo secret **`SUPABASE_ACCESS_TOKEN`** (Settings -> Secrets and variables -> Actions).
3. Optional: set a repo variable `SUPABASE_PROJECT_REF` (it defaults to the TIWANI project ref).

Until the secret is set the deploy job skips cleanly (a green no-op), so the workflow is safe to merge
before you are ready. After it is set, editing a template and merging to `main` redeploys it. The script
also runs by hand: `SUPABASE_ACCESS_TOKEN=sbp_... bash supabase/deploy-email-templates.sh`.

### Local Supabase CLI (only if it is adopted later)

If this repo ever runs the local stack (`supabase start`), wire the templates in `supabase/config.toml`
and restart the containers (`supabase stop && supabase start`):

```toml
[auth.email.template.confirmation]
subject = "Confirm your email to get started with TIWANI"
content_path = "./supabase/templates/confirmation.html"

[auth.email.template.invite]
subject = "You are invited to join TIWANI"
content_path = "./supabase/templates/invite.html"

[auth.email.template.magic_link]
subject = "Your TIWANI sign-in link"
content_path = "./supabase/templates/magic_link.html"

[auth.email.template.email_change]
subject = "Confirm your new email address for TIWANI"
content_path = "./supabase/templates/email_change.html"

[auth.email.template.recovery]
subject = "Reset your TIWANI password"
content_path = "./supabase/templates/recovery.html"

[auth.email.template.reauthentication]
subject = "Your TIWANI verification code"
content_path = "./supabase/templates/reauthentication.html"
```
