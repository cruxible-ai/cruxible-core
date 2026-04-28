# Control Review: CTRL-1 Edge WAF

## Summary

`CTRL-1` (`Edge WAF`) is attached to `ASSET-1` and `ASSET-6` in deterministic
seed data. Security Engineering reviewed the deployed policy set after the two
Apache incidents and concluded it materially reduces exposure to path traversal
and rewrite-based exploitation attempts against public Apache HTTP Server
instances.

## Candidate graph facts

- Proposed `control_reduces_exposure_to`:
  `CTRL-1 -> CVE-2021-41773`
  `validation_basis=Validated against replay of observed path traversal requests`
- Proposed `control_reduces_exposure_to`:
  `CTRL-1 -> CVE-2024-38475`
  `validation_basis=Emergency mod_rewrite blocking rule tested on production mirror`

## Caveat

The review notes that `CTRL-1` should likely remain `unsure` rather than full
`support` for non-HTTP attack paths or for assets that do not terminate traffic
behind the shared edge tier.
