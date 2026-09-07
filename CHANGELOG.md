# Changelog

## 1.9.0

Fixes for the findings in the code audit of this fork (4 critical, 9 high,
11 medium, 9 low). IDs below refer to that audit.

### Security

- **C1** — Saved responses no longer land in `custom_components/eero/api/responses`
  (inside the component source tree, so included in every backup). They go to
  `.storage/eero_responses`, every `/2.2/login*` exchange is skipped outright,
  and `user_token`, `password`, `psk`, `master_key`,
  `commissioning_credential` and `active_operational_dataset` are redacted
  from whatever is written.
- **C2** — `EeroException` no longer logs at WARNING from its constructor and
  no longer carries the response body. An Eero 500 on a network endpoint used
  to dump the WiFi PSK, the guest PSK and the Thread dataset into
  `home-assistant.log` with no option enabled. Error messages now name the URL
  path only, so query strings never reach the log.
- **H8** — The `thread_enabled` switch no longer publishes the Thread master
  key, commissioning credential or active operational dataset as state
  attributes, and the guest network switch no longer publishes the guest WiFi
  password. State attributes are readable by every logged-in user and are
  written to the recorder database.
- **M5** — The firmware manifest URL, which comes from the API response, must
  be https on `eero.com` or `e2ro.com` and is fetched with a bare request
  rather than the session that talks to the auth endpoint.
- **M6** — The login identifier and the one-time verification code are no
  longer written to the debug log, and config-entry migration logs key names
  rather than values.

### Reliability

- **C3** — The session refresh is bounded: at most one refresh per call, and a
  session that cannot be refreshed raises `EeroSessionExpired`. That becomes
  `ConfigEntryAuthFailed`, and a reauth step in the config flow asks for a new
  verification code and stores the new token. Previously a dead session sent
  hundreds of auth POSTs per poll and then crash-looped forever with no way
  out but delete-and-re-add.
- **C4** — API errors are no longer swallowed. `update()` raises, the
  coordinator marks the update failed, and entities become unavailable instead
  of reporting the values they had when the failure started. Presence
  automations now see a failure rather than a frozen `home`.
- **H1** — Every request carries a `(connect, read)` timeout, taking the
  configured polling timeout as the read value. `requests` transport errors
  (`ConnectionError`, `SSLError`, timeouts) all become `EeroException`.
- **H2** — A refreshed session token is written back to the config entry, so a
  restart no longer reloads a token Eero has already rotated.
- **H3** — A resource that disappears from the API is reported as missing
  rather than silently replaced by the network object, which is what produced
  `'EeroNetwork' object has no attribute 'paused'`. Unique IDs are built from
  configured IDs, so an entity can no longer attach itself to the wrong device.
- **H4** — The update loop treats every field of the response as optional: no
  Thread border router, no `backup_access_point` capability, no `updates`
  block and no timezone no longer break setup.
- **H5** — Data usage sensors report unknown instead of raising
  `TypeError: NoneType + NoneType` right after a period rolls over.
- **H6** — Status light brightness handles an eero that reports no
  `led_brightness`, and rounds instead of truncating.
- **H7** — Firmware entities cope with a network that has no release notes.
- **H9** — `EeroProfile.ad_block` no longer raises `TypeError` when
  `premium_dns` is unpopulated, which used to prevent the entire switch
  platform from creating a single entity.
- **M1** — The request retried after a session refresh is checked.
- **M2** — 429 raises `EeroRateLimited` carrying `Retry-After`. Release notes
  are cached per manifest URL instead of refetched every poll. The polling
  floor moves 30s → 120s and the default 120s → 300s.
- **M9** — Entity discovery no longer uses bare `hasattr`, so one broken
  property cannot abort a whole platform's setup and failures are logged.
  (Partial: the audit's declarative `supported_resources` redesign was not
  attempted.)
- **M10** — The `requests.Session` is closed when the entry unloads.
- **L7, L8** — `preferred_update_hour` and `EeroClient.signal` no longer raise
  on unexpected values.

### Behaviour and naming

- **M7** — `has_entity_name` is adopted. Entities are named for what they
  measure ("Signal Strength") and Home Assistant composes the friendly name
  from the device name; the network prefix and wired/wireless suffix moved to
  the device. **This changes generated entity IDs**, which is why it ships
  before first install. Unique IDs are unchanged.
- **Image platform removed.** The two QR-code image entities per network are
  gone, along with the `pypng` and `PyQRCode` requirements (sdist-only, last
  released 2019 and 2016; a requirements install failure takes down the whole
  integration) and the `show_eero_logo` option. This also resolves **M3** (QR
  PNGs re-encoded on the event loop on every state write) and **M4**
  (hardcoded `/config` paths).
- **M8** — Profile clients are constructed with their network, not their
  profile.
- **M11** — `EeroNetwork.update()` is now `install_firmware_update()`: it
  updates every eero on the network, which the old name did not say.
- **L5** — `secondary_wan_deny_access` is now `secondary_wan_allow_access`,
  matching what it returns and what the switch is labelled.
- **L6** — Networks with no geolocation no longer appear as
  "MyNetwork (None, None)".
- **L1, L2, L3, L4, L9** — Real type annotations instead of `str[EntityCategory]`,
  working form prefill in the config flow, consistent entity base-class order,
  dead `camera` translations removed, `quality_scale` dropped, `loggers` set,
  and the coordinator gets `config_entry`.

### Fixes to the PRs merged into this fork

- PR #170's `except (KeyError, ValueError): pass` is now a KeyError-only
  handler that logs and explains the cause (a snapshot of the device registry
  being iterated while entries are removed). It has nothing to do with
  Python 3.14, contrary to the commit message.
- PR #171 dropped the `ip`, `mac` and `host_name` device_tracker attributes
  when it moved to `BaseScannerEntity`. Restored.
- PR #174's unreachable `.strip()` removed; the attribute is named
  `channel_width_rx`, which is the field it reads.
- `light.turn_on` with `brightness: 1` mapped to 0 and turned the light off.
  Clamped to 1.

### Tests

`tests/` holds a pytest suite for the api package that runs without Home
Assistant installed:

```bash
python3 -m venv .venv && .venv/bin/pip install pytest requests
.venv/bin/python -m pytest -q
```

## 1.8.1 and earlier

See the upstream project: https://github.com/schmittx/home-assistant-eero
