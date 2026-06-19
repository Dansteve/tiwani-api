#!/usr/bin/env bash
# Deploy the TIWANI auth email templates to the hosted Supabase project via the
# Management API. SURGICAL: it PATCHes ONLY the 12 mailer fields (6 subjects + 6
# bodies), so it never touches the Site URL, the redirect allowlist, the Google
# provider, the migrations, or any other auth setting. Idempotent: re-running
# sets the same content. Drives the CI deploy job and can be run by hand.
#
# Required env:
#   SUPABASE_ACCESS_TOKEN   a Supabase personal access token (sbp_...)
# Optional env:
#   SUPABASE_PROJECT_REF    the project ref (defaults to the known TIWANI project)
set -euo pipefail

PROJECT_REF="${SUPABASE_PROJECT_REF:-kogpfmuxgfjfjkdwrsjv}"
: "${SUPABASE_ACCESS_TOKEN:?SUPABASE_ACCESS_TOKEN is required (a Supabase personal access token, sbp_...)}"

TEMPLATES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/templates"
API="https://api.supabase.com/v1/projects/${PROJECT_REF}/config/auth"

# type | subject | file. The subject carries spaces but never a pipe.
TEMPLATES=(
  "confirmation|Confirm your email to get started with TIWANI|confirmation.html"
  "invite|You are invited to join TIWANI|invite.html"
  "magic_link|Your TIWANI sign-in link|magic_link.html"
  "email_change|Confirm your new email address for TIWANI|email_change.html"
  "recovery|Reset your TIWANI password|recovery.html"
  "reauthentication|Your TIWANI verification code|reauthentication.html"
)

# Build the PATCH body with jq so each HTML body is correctly JSON-encoded.
jq_args=()
jq_filter='{}'
for entry in "${TEMPLATES[@]}"; do
  IFS='|' read -r type subject file <<< "$entry"
  path="${TEMPLATES_DIR}/${file}"
  [ -f "$path" ] || { echo "ERROR: missing template $path" >&2; exit 1; }
  jq_args+=(--arg "subj_${type}" "$subject" --rawfile "body_${type}" "$path")
  jq_filter="${jq_filter} + {\"mailer_subjects_${type}\": \$subj_${type}, \"mailer_templates_${type}_content\": \$body_${type}}"
done

body_file="$(mktemp)"
resp_file="$(mktemp)"
trap 'rm -f "$body_file" "$resp_file"' EXIT
jq -n "${jq_args[@]}" "$jq_filter" > "$body_file"

echo "Deploying 6 auth email templates to project ${PROJECT_REF} (mailer fields only)..."
http_code="$(curl -sS -o "$resp_file" -w '%{http_code}' \
  -X PATCH "$API" \
  -H "Authorization: Bearer ${SUPABASE_ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  --data-binary "@${body_file}")"

if [ "$http_code" != "200" ]; then
  echo "ERROR: PATCH returned HTTP ${http_code}" >&2
  # Print only the error fields, never the whole body (it can carry other secrets).
  jq -r '{message, error, msg} | tostring' "$resp_file" 2>/dev/null >&2 || true
  exit 1
fi

# Verify via a fresh GET: a wrong field name would 200 but silently no-op. We read
# back ONLY the mailer content fields (never printing the body, which also holds
# other auth secrets) and confirm each carries the TIWANI template.
curl -sS -o "$resp_file" \
  -H "Authorization: Bearer ${SUPABASE_ACCESS_TOKEN}" "$API"

for entry in "${TEMPLATES[@]}"; do
  IFS='|' read -r type subject file <<< "$entry"
  if ! jq -r ".mailer_templates_${type}_content // \"\"" "$resp_file" | grep -q 'TIWANI'; then
    echo "ERROR: ${type} template did not apply (read-back is missing the expected content)" >&2
    exit 1
  fi
done

echo "All 6 templates deployed and verified."
