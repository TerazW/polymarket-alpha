# Billing FAQ

**Market Sensemaking**
**https://marketsensemaking.com**

**Last Updated:** [DATE]

---

## Table of Contents

1. [Subscription Plans](#1-subscription-plans)
2. [Pricing](#2-pricing)
3. [Payment Methods](#3-payment-methods)
4. [Billing Cycle](#4-billing-cycle)
5. [Cancellation](#5-cancellation)
6. [Refunds](#6-refunds)
7. [Upgrades & Downgrades](#7-upgrades--downgrades)
8. [Taxes](#8-taxes)
9. [Invoices & Receipts](#9-invoices--receipts)
10. [Usage Limits](#10-usage-limits)
11. [Troubleshooting](#11-troubleshooting)
12. [Contact](#12-contact)

---

## 1. Subscription Plans

### What plans are available?

| Plan | Description | Typical Use Case |
|------|-------------|------------------|
| **Observer** | Basic access, limited markets | Personal exploration |
| **Analyst** | Extended access, more markets | Serious research |
| **Institution** | Full access, highest limits | Professional use |

### What's included in each plan?

| Feature | Observer | Analyst | Institution |
|---------|----------|---------|-------------|
| Tracked markets | 10 | 50 | 200+ |
| Heatmap LOD (min) | 5s | 1s | 250ms |
| WebSocket topics | alerts | alerts, states | alerts, states, health |
| API rate limit | 100/min | 500/min | 2000/min |
| Historical replay | 7 days | 30 days | 90 days |
| Evidence bundles | Basic | Full | Full + Attestation |
| Support | Email | Priority email | Priority + Slack |

### Is there a free tier?

Currently, we do not offer a free tier. However, we may offer trial periods for new users. Check our website for current offers.

---

## 2. Pricing

### How is pricing structured?

Pricing is per-seat, per-month (or annual with discount). Prices are listed on our pricing page and may vary by region.

### Are there discounts for annual billing?

Yes. Annual billing typically offers a discount equivalent to 2 months free compared to monthly billing.

### Can prices change?

Yes. We reserve the right to change prices with 30 days advance notice. Price changes do not affect current billing periods.

### Is there startup or academic pricing?

Contact us at sales@marketsensemaking.com to discuss special pricing for:
- Startups (< 2 years old, < $1M funding)
- Academic/research institutions
- Non-profits
- Volume discounts (5+ seats)

---

## 3. Payment Methods

### What payment methods do you accept?

| Method | Available |
|--------|-----------|
| Credit card (Visa, Mastercard, Amex) | ✓ |
| Debit card | ✓ |
| PayPal | Contact us |
| Wire transfer | Institution only |
| Crypto | Not currently |

### Is my payment information secure?

Yes. We do NOT store your full credit card number. All payment processing is handled by Stripe, a PCI-DSS compliant payment processor.

### Can I change my payment method?

Yes. Go to Account Settings → Billing → Payment Method to update your card or payment information.

---

## 4. Billing Cycle

### When am I billed?

- **Monthly plans:** Billed on the same day each month (e.g., if you subscribed on the 15th, you're billed on the 15th)
- **Annual plans:** Billed once per year on your subscription anniversary

### What if my billing date doesn't exist in a month?

If you subscribed on the 31st and a month has fewer days, you'll be billed on the last day of that month.

### When does my subscription renew?

Subscriptions renew automatically at the end of each billing period unless cancelled.

### How do I know when my next billing date is?

Go to Account Settings → Billing to view your next billing date.

---

## 5. Cancellation

### How do I cancel my subscription?

1. Go to Account Settings → Billing
2. Click "Cancel Subscription"
3. Confirm cancellation
4. You'll receive a confirmation email

Alternatively, email support@marketsensemaking.com with your account email and request cancellation.

### What happens after I cancel?

- Your subscription remains active until the end of the current billing period
- You retain full access until that date
- After the period ends, access is revoked
- Your account and data are retained for 90 days (then deleted per our Privacy Policy)

### Can I cancel anytime?

Yes. You can cancel at any time. There are no cancellation fees.

### Can I reactivate after cancelling?

Yes. If you reactivate:
- **Within 90 days:** Your account data is restored
- **After 90 days:** You start fresh (historical data is deleted)

### Do I get a refund when I cancel?

Generally, no. See the [Refunds](#6-refunds) section for exceptions.

---

## 6. Refunds

### What is your refund policy?

**Generally, no pro-rata refunds are provided for partial billing periods.**

### When can I get a refund?

Refunds may be issued for:

| Situation | Refund |
|-----------|--------|
| Duplicate charge | Full refund of duplicate |
| Extended outage (>24 hours, our fault) | Pro-rata credit |
| Billing error | Correction |
| First-time subscriber dissatisfaction (within 7 days) | Case-by-case |

### How do I request a refund?

1. Email support@marketsensemaking.com within 14 days of the charge
2. Include: Account email, transaction date, reason for request
3. We'll respond within 5 business days

### How long does a refund take?

- Credit card refunds: 5-10 business days
- Other methods: Varies by payment processor

### What about annual subscriptions?

Annual subscriptions are generally non-refundable after the first 14 days. Exceptions may be made for documented extended outages.

---

## 7. Upgrades & Downgrades

### How do I upgrade my plan?

1. Go to Account Settings → Billing
2. Click "Change Plan"
3. Select your new plan
4. Confirm upgrade

### When does an upgrade take effect?

Immediately. You'll be charged a prorated amount for the remainder of your current billing period.

### How do I downgrade my plan?

1. Go to Account Settings → Billing
2. Click "Change Plan"
3. Select your new plan
4. Confirm downgrade

### When does a downgrade take effect?

At the start of your next billing period. You retain your current plan's features until then.

### Will I get a refund when I downgrade?

No. You keep your current plan until the end of the billing period, then switch to the lower plan.

### What happens to my data if I downgrade?

| Data Type | Behavior |
|-----------|----------|
| Tracked markets (excess) | Oldest tracked markets are paused |
| High-res heatmap tiles | Access revoked, data retained |
| Historical replay (excess) | Oldest data becomes inaccessible |
| Evidence bundles | Remain accessible within new limits |

---

## 8. Taxes

### Are prices inclusive of taxes?

Prices displayed on our website are typically **exclusive of taxes** unless otherwise stated.

### What taxes might I pay?

Depending on your location:

| Tax | Where |
|-----|-------|
| GST/HST | Canada |
| VAT | European Union, UK |
| Sales tax | Various US states |
| Other local taxes | Varies by jurisdiction |

### How do I know what taxes apply?

Taxes are calculated at checkout based on your billing address. The final amount (including taxes) is shown before you confirm.

### Can I get a tax exemption?

If you're a tax-exempt organization:
1. Email billing@marketsensemaking.com with your exemption certificate
2. We'll update your account
3. Future charges will exclude applicable taxes

### Do I receive tax invoices?

Yes. All receipts include tax breakdowns for your records.

---

## 9. Invoices & Receipts

### How do I get my invoices?

1. Go to Account Settings → Billing → Invoices
2. View or download any past invoice

Invoices are also emailed after each charge.

### What's included on invoices?

- Invoice number and date
- Your account/billing details
- Plan and period
- Amount and tax breakdown
- Payment method (last 4 digits)
- Our company details

### Can I get a consolidated invoice?

For Institution plans with multiple seats, contact billing@marketsensemaking.com for consolidated invoicing options.

### Can I update my billing details on invoices?

Yes. Update your billing information in Account Settings → Billing. Future invoices will reflect the changes.

---

## 10. Usage Limits

### What happens if I exceed my plan limits?

| Limit Type | Behavior |
|------------|----------|
| Tracked markets | Cannot add more; existing continue |
| API rate limit | Requests are throttled (429 error) |
| WebSocket topics | Unauthorized topics rejected |
| Historical replay | Older data inaccessible |

### Do unused limits roll over?

No. Monthly limits reset at the start of each billing period.

### How do I check my usage?

1. Go to Dashboard → Usage
2. View current usage vs. plan limits
3. Set up usage alerts (optional)

### Can I buy additional capacity?

For one-time needs, contact sales@marketsensemaking.com. For ongoing higher capacity, consider upgrading your plan.

---

## 11. Troubleshooting

### My payment failed. What do I do?

Common reasons and solutions:

| Reason | Solution |
|--------|----------|
| Insufficient funds | Ensure adequate balance |
| Card expired | Update payment method |
| Fraud block | Contact your bank, then retry |
| Address mismatch | Verify billing address |
| International block | Contact your bank to allow |

### I was charged twice. What do I do?

1. Check your invoice history to confirm
2. Email support@marketsensemaking.com with transaction details
3. We'll investigate and refund any duplicates

### My subscription shows as inactive but I paid

1. Wait 5 minutes (processing delay)
2. Refresh your browser / re-login
3. Check spam folder for confirmation email
4. Contact support@marketsensemaking.com if still not resolved

### I can't access features I paid for

1. Verify your plan in Account Settings → Billing
2. Ensure billing is current (no failed payments)
3. Log out and log back in
4. Contact support@marketsensemaking.com if the issue persists

---

## 12. Contact

### Billing Support

- **Email:** billing@marketsensemaking.com
- **Response time:** 1-2 business days

### General Support

- **Email:** support@marketsensemaking.com
- **Response time:** Same day (business hours)

### Sales / Enterprise

- **Email:** sales@marketsensemaking.com

### Website

- **URL:** https://marketsensemaking.com

---

## Quick Reference

| Question | Answer |
|----------|--------|
| Can I cancel anytime? | Yes |
| Do I get a refund if I cancel? | Generally, no |
| When am I billed? | Monthly or annually, same date |
| Can I change plans? | Yes, anytime |
| Are taxes included? | Usually not (calculated at checkout) |
| How do I update payment? | Account Settings → Billing |
| What if payment fails? | Update method, retry |

---

**For questions not covered here, contact support@marketsensemaking.com.**

---

<footer>

**Market Sensemaking**

Website: https://marketsensemaking.com
Billing: billing@marketsensemaking.com
Support: support@marketsensemaking.com
Sales: sales@marketsensemaking.com

© 2025 Market Sensemaking. All rights reserved.

*Evidence-only. Not advice. Your decisions, your responsibility.*

</footer>
