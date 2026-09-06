# Project write replay: remaining costs

Diagnostic replay of the earlier seven-member (five Claims, two Subjects)
project-state checkpoint at accepted OID
`968e294fcee5b1a87946b4142cb2173bf33971ea`, using branch `1b6567c8`.
A private copied instance was opened with its trust root and retained custody;
no managed instance was opened in-process or modified by this experiment.

These cProfile numbers include substantial instrumentation overhead and cold
process caches. They are attribution evidence, not live benchmarks. Service
calls exclude HTTP and attached-workspace advertisement. The actual earlier
managed SDK sample was submit 7.505 s and accept 12.597 s.

| Profiled stage | Total | Dominant work |
|---|---:|---|
| Open/recovery | 11.46 s | Verify retained checkpoint/history |
| First create | 20.92 s | Validate 27 intent streams for cold fingerprint lookup |
| Prepare | 4.97 s | Initial evaluation state, lowering and subject index |
| Submit | 16.24 s | Two complete review-note indexes: 11.71 s combined; 47 candidate evidence decodes, 92 review commit-address derivations |
| Acceptance | 23.78 s | Projection prebuild: 18.70 s; parse/normalize: 12.99 s; explanation generation: 4.01 s within that; SQLite load: 2.71 s |

Submission's initial candidate-summary cache is cold in this replay. The second
index build reuses summary validation but still enumerates evidence and derives
aliases. Do not attribute all 11.71 seconds to repeated warm work.

The next performance design should target two boundaries:

1. Review-note maintenance: build only affected commit groups while preserving
   every colliding original/advisory alias. A new candidate can complete an older
   interrupted admission sharing its digest, so merely appending the new proposal
   to the old index is insufficient. Notes remain rebuildable from evidence; stale,
   edited and partial notes must retain current corruption/recovery behavior.
2. Projection assembly: separate artifact-local compiled facts from coordinate-
   and dependency-sensitive facts. Reuse unchanged compilation from verified bytes,
   regenerate affected relationships and coordinate bindings, and retain complete
   canonical row/digest parity with a cold rebuild. Explanation facts embed current
   coordinates; copying old rows wholesale would be incorrect. Generation authority
   still comes solely from signed ledger/Git state.

No partial incremental projection implementation was introduced in this batch.
The SDK/floor integration is complete; this remains the next design/implementation
slice. Named parity checks must cover schema/compiler skew, competing claims,
changed source/citation dependencies, history-based explanation, restart rebuild,
and interrupted note publication. No Rust dependency is justified by this profile.
