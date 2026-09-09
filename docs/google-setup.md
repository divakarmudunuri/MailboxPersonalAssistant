# Google setup: OAuth, IMAP, and the Calendar API

The app reads and changes mail over IMAP and manages events through the Google Calendar API, both with one OAuth
token for your Google account. This page takes you from a bare Google account to a working `token.json`.

What you end up with:

| File | Where | What it is |
| --- | --- | --- |
| `credentials.json` | `python-backend/.secrets/` | The OAuth client secret you download from Google Cloud. Identifies the app. |
| `token.json` | `python-backend/.secrets/` | Your consent, saved by the app. Grants the app access to your mailbox and calendar. |

Both are gitignored. Never commit or share them.

## 1. Create a Google Cloud project

1. Open the [Google Cloud Console](https://console.cloud.google.com/) and sign in with the Google account whose
   mailbox the assistant will manage.
2. Create a project, for example `mailbox-assistant`, and make sure it is selected in the top bar.

## 2. Enable the Google Calendar API

1. Go to **APIs & Services → Library**.
2. Search for **Google Calendar API** and click **Enable**.

The inbox manager needs this to create reminders and answer invitations. Mail itself goes over IMAP, which needs no
API enabled, so the Gmail API can stay off.

## 3. Configure the OAuth consent screen

1. Go to **APIs & Services → OAuth consent screen** (called **Google Auth Platform** in newer consoles).
2. Choose the audience **External** if you use a personal Gmail account; **Internal** is only for Google Workspace
   organisations. Fill in the app name and your email as the support and developer contact.
3. Under **Audience → Test users**, add your own Google account. While the app is in **Testing** status, only test
   users can grant it access.
4. Under **Data access → Add or remove scopes**, add these two scopes. You can paste them into the manual entry box:

   ```
   https://mail.google.com/
   https://www.googleapis.com/auth/calendar.events
   ```

   The first is full mailbox access, which IMAP with OAuth requires. The second is read and write of calendar
   events. These are the scopes in `python-backend/src/mail_assistant/gmail_client/auth.py`; if that list and the
   consent screen disagree, consent still works, but Google shows an "unverified app" warning.

## 4. Create the OAuth client

1. Go to **APIs & Services → Credentials → Create credentials → OAuth client ID**.
2. Application type: **Desktop app**. Give it a name and click **Create**.
3. Download the JSON and save it as `python-backend/.secrets/credentials.json` (the folder is created on first run and
   is gitignored).

## 5. Enable IMAP in Gmail

1. In Gmail, open **Settings → See all settings → Forwarding and POP/IMAP**.
2. Under **IMAP access**, choose **Enable IMAP** and save. Newer Gmail accounts have IMAP always on and no longer
   show this switch; that is fine.

Gmail's IMAP limits are 15 simultaneous connections per account and roughly 2.5 GB of downloads per day. The app
opens three connections and reads headers and single messages, so it stays far below both.

## 6. Tell the app which mailbox it is

In `python-backend/.env`, set the address the app should log in as:

```
GMAIL_ADDRESS=you@gmail.com
```

This is the IMAP login name; the token alone does not carry it.

## 7. Grant access

From `python-backend`:

```bash
uv run mail-assistant-auth
```

The script removes any old `token.json`, opens your browser, and asks you to sign in and approve the two scopes.
Because the app is in Testing status you will see a warning that Google has not verified it; click through
**Continue**. When it finishes it prints the granted scopes and saves `token.json`. Then start the app:

```bash
uv run mail-assistant
```

The log (`python-backend/logs/mail_assistant.log`) shows `IMAP connected as you@gmail.com` within a few seconds. If
you skip the auth script, the app runs the same consent flow itself the first time it starts, or whenever the saved
token was granted for narrower scopes than it needs.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Browser says **Access blocked: this app has not completed the Google verification process** | Your account is not a test user, or the consent screen is not configured | Add your account under Test users, then re-run `mail-assistant-auth` |
| `[AUTHENTICATIONFAILED] Invalid credentials (Failure)` in the log | The token lacks the `https://mail.google.com/` scope, or IMAP is disabled in Gmail | Re-run `mail-assistant-auth`; check step 5 |
| Calendar tools fail with **403** or **accessNotConfigured** | The Calendar API is not enabled on the project, or the token lacks `calendar.events` | Enable it (step 2) and re-run `mail-assistant-auth` |
| `ValueError: GMAIL_ADDRESS is not set` | Step 6 skipped | Set it in `.env` |
| Everything worked and then, about a week later, it fails to refresh the token | Apps in **Testing** status get refresh tokens that expire after 7 days | Re-run `mail-assistant-auth`, or move the consent screen to **In production** so tokens stop expiring |
| `token.json was granted [...] but [...] is needed; re-running consent` in the log | The scope list in the code changed since you consented | Expected; approve the new consent once |

## What the app does with the access

- Over IMAP it detects new mail with IDLE, reads messages and threads, checks the Sent folder for your replies, and,
  through the inbox manager, can save drafts, set flags and labels, archive, and move messages to Trash or Spam.
- Through the Calendar API it lists events, creates reminders, and sets your RSVP on invitations.
- It sends mail only when you click Send on a drafted reply in the Inbox tab, over SMTP with the same token; the
  agents themselves never send. Permanent deletion is only possible for messages already in Trash.

Revoke access at any time from your Google account's
[third-party apps and services](https://myaccount.google.com/connections) page, or delete `token.json` to make the app
ask again.
