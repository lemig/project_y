# flag-suspect-doc — integration test fixtures

These are **synthetic, fictional** documents written for testing the
flag-suspect-doc skill. No real entities, no OLAF case data, no real bank
references. Every fixture is a plain UTF-8 text file representing the
extracted text body of a document, plus a sidecar `*.meta.json` with the
metadata that an Aleph entity would carry.

Three fixtures, designed to exercise the methodology cleanly:

- `invoice_high_risk.txt` — invoice with three independent red flags:
  round-number total (EUR 250,000), vague service description ("strategic
  consulting services"), counterparty registered in a FATF-monitored
  jurisdiction. Should score high.
- `invoice_clean.txt` — well-itemised invoice from a domestic supplier with
  specific deliverables. Should score zero / not produce a Note.
- `contract_unexplained_intermediary.txt` — services contract that
  introduces an agent with no explained role, paid 18% commission. Should
  fire the "intermediary with no apparent role" content signal plus the
  jurisdiction metadata signal.
