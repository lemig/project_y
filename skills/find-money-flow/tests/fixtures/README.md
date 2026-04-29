# find-money-flow integration fixtures

Three synthetic documents constructed to exercise a textbook layering
chain: anchor account `IT60X0542811101000000123456` → intermediary
`LU28 0019 4006 4475 0000` → BVI-registered shell `BVI-NB-99281` →
cash withdrawal at a Caribbean branch, all within four days, with a
~2k EUR drop per hop consistent with intermediary fee structuring.

These are NOT real entities or accounts. They are constructed test
data designed to:

- exercise multilingual quote handling (doc-001 is Italian; doc-002
  and doc-003 are English),
- give the substring quote verifier real character offsets to assert
  against,
- give the layering stop-condition (3 rapid hops, no economic
  substance) a clean positive case.

Brief that should drive the chain (used by the integration test):

> Trace the money out of contract C-2024-077.
