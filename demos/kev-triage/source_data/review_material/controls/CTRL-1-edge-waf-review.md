# Control Review: CTRL-1 Edge WAF

`CTRL-1` (`Edge WAF`) is attached to `ASSET-1` and `ASSET-6` by deterministic
inventory data. Security Engineering reviewed the deployed policy set and
concluded it materially reduces exposure to Apache path traversal and rewrite
exploit attempts against public Apache HTTP Server instances.

Expected governed actions:

- Propose `control_reduces_exposure_to` from `CTRL-1` to `CVE-2021-41773`
- Propose `control_reduces_exposure_to` from `CTRL-1` to `CVE-2024-38475`
