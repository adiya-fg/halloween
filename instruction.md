# Project: Halloween 2026 Personalized Sticker Generator with Manual Bank Transfer Approval

Build a small, secure web application that allows users to request personalized Halloween 2026 name stickers. Users submit their name and payment information, transfer money to the administrator's bank account, and wait for manual payment verification. After the administrator confirms the payment, the user's Generate button becomes available.

## 1. First, inspect the existing project

Before writing code:
- Inspect the existing repository, framework, folder structure, database, and configuration.
- Reuse the existing technology stack and coding conventions.
- Do not rewrite or replace working components unnecessarily.
- If this is an empty project, use FastAPI, SQLite, HTML, CSS, and vanilla JavaScript.
- Provide a short implementation plan before making significant changes.

## 2. User-facing workflow

### Step 1: Enter personal information

Create a responsive landing page with:
- Title: "Halloween 2026 — Your Personalized Sticker"
- Subtitle: "Create your own spooky Halloween name sticker!"
- Name input (required).
- Optional email input.
- A gallery showing 5–10 Halloween sticker design previews.
- A clearly displayed donation or participation fee.
- A button labeled "Request My Sticker".

Validate the name length, trim whitespace, and escape all user-provided text before rendering it.

### Step 2: Display bank-transfer instructions

When the user submits the form:
- Create a unique request ID, such as `HW26-A7K9Q2`.
- Save the request to the database with status `PENDING_PAYMENT`.
- Display the bank name, account holder, account number, transfer amount, and transfer instructions from administrator-configured settings.
- Tell the user to include the request ID in the bank transfer description when supported.
- Explain that approval happens only after the administrator manually verifies the actual bank transaction.

Provide a "I Have Transferred the Money" button.

When clicked:
- Change the status to `PAYMENT_REPORTED`.
- Record the report timestamp.
- Show a confirmation message: "Your payment report has been received. Your sticker will become available after administrator verification."
- Do not automatically approve the payment.

Prevent duplicate submissions and repeated payment reports from creating duplicate requests.

### Step 3: Waiting page

Every request should have a status page accessible through a secure, unguessable tracking token.

Possible status messages:
- `PENDING_PAYMENT`: Please complete your bank transfer.
- `PAYMENT_REPORTED`: Your payment is awaiting verification.
- `APPROVED`: Your sticker generator is now available.
- `REJECTED`: Your payment could not be verified. Please contact the administrator.
- `EXPIRED`: This request has expired.

While the request is awaiting approval:
- Keep the Generate button hidden or disabled.
- Do not expose high-resolution image download URLs.
- Do not trust a status value supplied by the browser.
- Fetch the authoritative status from the backend.

### Step 4: Generate sticker after approval

Only when the backend confirms that the request is approved:
- Display the "Generate My Sticker" button.
- Allow the user to select a Halloween template.
- Render their name into the selected design.
- Display a preview before downloading.
- Provide a "Download High-Resolution PNG" button.

Use SVG or HTML Canvas to generate deterministic, high-quality artwork without calling a paid AI API for every request.

Target image output:
- At least 3000 × 3000 pixels for square stickers.
- Transparent background option.
- Crisp text and vector-quality graphics.
- Halloween 2026 theme: pumpkins, ghosts, bats, spooky lettering, orange and purple colors.
- Correct rendering of international characters, including Mongolian and Japanese text, where supported by the selected fonts.

Make the name readable, automatically scale long names, and prevent text from overflowing the design.

Important: enforce approval on the server for every protected generation or download endpoint. Hiding the button in JavaScript is not sufficient.

## 3. Admin dashboard

Create a separate administrator login and dashboard.

The dashboard must display:
- Request ID.
- Submitted name.
- Optional email.
- Requested design, if selected.
- Requested payment amount.
- Payment-report timestamp.
- Current status.
- Approval or rejection timestamp.
- Administrator notes.

Provide filters for:
- All requests.
- Awaiting payment.
- Payment reported.
- Approved.
- Rejected.
- Expired.

### Manual payment verification

For each request with status `PAYMENT_REPORTED`, display:
- "Approve Payment"
- "Reject Payment"
- "Add Admin Note"

The administrator must manually check the actual bank account transaction before approving.

On approval:
1. Require confirmation from the administrator.
2. Record the approval timestamp and administrator ID.
3. Change the request status to `APPROVED`.
4. Record a transaction reference if available.
5. Make the Generate button available on the user's status page.

On rejection:
1. Require a rejection reason.
2. Change the status to `REJECTED`.
3. Record the administrator ID and timestamp.
4. Show the reason or appropriate next steps to the user.

Do not allow approval of an already approved request or invalid state transitions. Prevent concurrent requests from causing inconsistent statuses.

Do not automatically approve requests based on screenshots, client-side form values, or a user clicking the payment-report button.

## 4. Database design

Create appropriate database tables.

### `sticker_requests`

Suggested columns:
- `id`: primary key.
- `request_code`: unique public reference.
- `tracking_token_hash`: hash of a securely generated tracking token.
- `name`: submitted name.
- `email`: nullable.
- `template_id`: selected template.
- `amount`: expected payment amount.
- `currency`: configured currency.
- `status`: controlled status value.
- `payment_reported_at`: nullable timestamp.
- `approved_at`: nullable timestamp.
- `rejected_at`: nullable timestamp.
- `rejection_reason`: nullable.
- `admin_notes`: nullable.
- `transaction_reference`: nullable.
- `approved_by`: nullable administrator ID.
- `created_at`: timestamp.
- `updated_at`: timestamp.

### `admins`

Suggested columns:
- `id`.
- `username`.
- `password_hash`.
- `created_at`.
- `last_login_at`.

### `audit_logs`

Record security-sensitive operations, including:
- Administrator login attempts.
- Payment approvals and rejections.
- Status changes.
- Changes to payment configuration.

Never store administrator passwords in plaintext. Store monetary amounts as integer minor units or use a suitable exact decimal representation.

## 5. Security requirements

Implement these requirements from the beginning:

- Admin authentication with securely hashed passwords.
- Secure session cookies and logout.
- CSRF protection for authenticated state-changing requests.
- Rate limiting on public endpoints and login attempts.
- Cryptographically random tracking tokens.
- Store only token hashes when practical.
- Never use sequential database IDs as authorization credentials.
- Validate and authorize all protected backend requests.
- Prevent SQL injection and cross-site scripting.
- Restrict access to admin routes and APIs.
- Use environment variables for secrets and deployment configuration.
- Never commit real bank account details, passwords, or secret keys.
- Avoid exposing personal information through public request listings or predictable URLs.
- Add basic anti-spam controls.
- Validate payment amount and currency on the server.
- Make approval and rejection operations auditable.
- Do not allow users to approve themselves by modifying frontend requests.
- Apply appropriate privacy and data-retention practices.

## 6. Payment configuration

Create a configuration section in the admin dashboard for:
- Bank name.
- Account holder name.
- Account number.
- Transfer amount.
- Currency.
- Payment instructions.
- Request expiration period.

Do not invent bank details. Use placeholder configuration during development.

Changes to the expected payment amount should apply predictably to existing requests. Store the agreed amount and currency on each request when it is created.

The application must not connect to a bank API or claim to verify transactions automatically. Verification is manual.

## 7. Suggested API endpoints

Adapt these endpoints to the existing project structure.

Public:
- `POST /api/requests`
- `POST /api/requests/{token}/report-payment`
- `GET /api/requests/{token}`
- `POST /api/requests/{token}/generate`
- `GET /api/requests/{token}/download`

Admin:
- `POST /api/admin/login`
- `POST /api/admin/logout`
- `GET /api/admin/requests`
- `POST /api/admin/requests/{id}/approve`
- `POST /api/admin/requests/{id}/reject`
- `PATCH /api/admin/settings`

These are proposed routes, not mandatory if the existing architecture uses another convention.

Every protected operation must check the current database status and authorization on the server.

## 8. User interface and design

Create a polished, mobile-first Halloween website:
- Dark purple background.
- Orange highlights.
- Friendly ghost and pumpkin illustrations.
- Attractive sticker gallery.
- Clear payment instructions.
- Large buttons and readable status indicators.
- Responsive design for mobile phones and desktop.
- Accessible form labels and keyboard navigation.

Do not make the interface look like a banking application. Keep it fun and simple.

## 9. Testing

Write automated tests covering at least these cases:

1. A new request starts in `PENDING_PAYMENT`.
2. Reporting a payment changes it to `PAYMENT_REPORTED`.
3. A pending user cannot generate or download a sticker.
4. A reported payment cannot generate or download a sticker.
5. An administrator can approve a reported payment.
6. An approved user can generate and download a sticker.
7. An administrator can reject a reported payment.
8. A rejected user cannot generate or download a sticker.
9. An unauthenticated user cannot access admin operations.
10. A user cannot approve a request by modifying the request URL or API payload.
11. Invalid status transitions are rejected.
12. Long names and non-ASCII characters render correctly.
13. Repeated submissions do not create unintended duplicate requests.
14. Invalid or expired tracking tokens are rejected.
15. Concurrent approval attempts cannot corrupt request state.

## 10. Delivery requirements

Implement the application incrementally.

After implementation:
- Run the automated tests.
- Fix any failing tests.
- Verify the full user journey from request creation to bank-transfer report, admin approval, generation, and high-resolution download.
- Provide setup instructions, database initialization steps, admin account creation instructions, environment variable documentation, and local run commands.
- Include a README with deployment guidance.
- Summarize all changed files and any remaining limitations.

Do not expose a default production administrator password. Provide a secure first-admin creation command or setup process.

Prioritize a working, secure MVP over unnecessary complexity. Avoid paid external APIs unless explicitly requested.