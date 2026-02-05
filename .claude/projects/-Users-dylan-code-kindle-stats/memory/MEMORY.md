# Kindle Stats Project

## Key Facts
- Amazon Parent Dashboard is at `www.amazon.com/parentdashboard/activities/household-summary`
- API endpoint: `POST /parentdashboard/ajax/get-weekly-activities-v2`
- API requires CSRF token from `ft-panda-csrf-token` cookie and `x-amzn-csrf` header
- API payload: `{childDirectedId, startTime, endTime, aggregationInterval: 86400, timeZone}`
- Response structure: `activityV2Data[].intervals[].aggregatedActivityResults[]`
- Durations are in **seconds**, not minutes
- Amazon only retains ~3 months of activity history (older weeks return HTTP 500)
- Child IDs are discovered from `get-household` response (`members` with `role: "CHILD"`)

## 1Password Integration
- Vault and item name stored in `config.json` (gitignored), prompted on first run
- Use `op read "op://<vault>/<item>/password"` for credentials (NOT `op item get --fields`)
- Use `op item get <item> --otp` for TOTP codes (op read returns the seed, not the code)
- Playwright `fill()` works for email but `type(delay=20)` needed for password on Amazon

## Login Flow
- Amazon splits login: email → Continue → password → Sign In → MFA
- Use `#ap_email`, `#continue`, `#ap_password`, `#signInSubmit`, `#auth-mfa-otpcode`, `#auth-signin-button`
- `#continue` matches multiple elements — use `.first`
