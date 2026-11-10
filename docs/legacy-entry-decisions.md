# Legacy Data (Old Register): transaction entry

Implementation approved by owner. Deployment requires a separate approval.
Scope: English UI, new endorsements and claims, draft ownership/confirmation,
Accounting reconciliation and receipts/payments, endorsement Production.
Historical import/correction/void/withdrawal writes remain unavailable.

Confirmed follow-up decisions:
- Old Reference is editable on new drafts; retain the original source transaction relation and reference snapshot.
- Endorsements and claims are separate business transactions; valid Finance offsets may combine them.
- Claims have no commission, tax, brokerage or processing fee; two equal legs.
- DOL is required at confirmation and must fall inclusively within the source transaction period.
- Endorsement Effective Date replaces the copied Effective Date; no separate date field.
- Expiry Date remains the source expiry and Effective Date must not exceed it.
- Endorsement No. is required at confirmation, distinct from the generated LTX number.
- Claims may be negative: Cedant recovery before returning funds to the reinsurer.
- Both directions cap cumulative claim payments at recovered funds, including valid offsets.
- Negative claims do not require a link to the original claim; a reason is mandatory.
- Claims have no Revenue Month and never contribute to Production.
- Drafts may omit required fields; only their owner edits/confirms.
- Use latest deployed VM rules and fixed dependency versions. Test candidate images in isolation.
- All API suites, all standard UI phases, and new lifecycle scenarios required before deployment approval.

Historical workbook values, original file, identifiers, settlement state and audit must be preserved.
Global Audit pause and SMTP-off remain unchanged.

Owner confirmed 2026-11-10: post-review/payment business amount corrections are deferred. This release includes new entry, receipt/payment registration and whole-registration reversal; untouched entries may return to draft. Deployment still requires separate approval.
