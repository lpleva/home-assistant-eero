# Changelog

## 1.9.1

Two fixes from the first run on Home Assistant 2026.9.1.

- The release-notes host allowlist added in 1.9.0 (**M5**) was too strict: it
  carried `eero.com` and `e2ro.com` only, while the firmware manifest URL in
  the API response points at `eeroassets.com`, Eero's own asset host. Every
  poll logged "Refusing to fetch release notes from unexpected host:
  eeroassets.com" and no release notes were shown. `eeroassets.com` and its
  subdomains are now allowed; the fetch is still https-only and still uses a
  bare request rather than the authenticated session.
- Child devices are linked to their network with `via_device_id` instead of
  `via_device`. Home Assistant deprecated the identifier-tuple `via_device`
  (it is removed in 2027.8) and warned once per platform on every start. The
  network device is now looked up in the device registry and its ID passed
  instead. Eeros, profiles, clients and backup networks sit under their
  network exactly as before.

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
  floor moves 30s → 60s and the default 120s → 300s.
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

### Post-review fixes

An independent review of these changes raised one blocking regression and
seven smaller items, all fixed here.

- **B1** — Home Assistant fires an entry's update listeners on any change,
  data included, so the token written back by the H2 fix reloaded the whole
  integration on every session rotation: entities removed and re-added,
  `consider_home` clocks reset, the `requests.Session` closed under an
  executor thread, and a second poll started on top of the one in flight.
  `async_update_listener` now reloads only when the options changed or when
  the entry's token differs from the one the running API object holds, which
  is true of a token from the reauth flow and false of one this integration
  persisted itself.
- **N1** — The asyncio timeout around the whole poll is gone. It gave the
  entire multi-request poll the budget of one request, and cancelling it never
  killed the executor thread, which is what H1's per-request timeout is for.
- **N2** — A failed release-notes fetch logs a warning instead of failing the
  poll. A 404 on the firmware manifest used to take every entity in the house
  unavailable over a decoration on the update entities.
- **N3** — A release-notes URL on an unexpected host is refused once and the
  refusal cached, instead of warning every poll forever.
- **N4** — The reauth step passes `reload_even_if_entry_is_unchanged=False`.
  Asking `async_update_reload_and_abort` to schedule a reload on an entry that
  has an update listener is deprecated and breaks in Home Assistant 2026.12;
  the listener owns the reload.
- **N5** — Reauth fails closed when the verification response carries no
  `log_id`, rather than skipping the wrong-account check and writing the token
  in unverified.
- **N6** — An account response with no `networks` member raises instead of
  building an empty account. On a cold start it used to set the integration up
  successfully with no entities and no reason logged.
- **N7** — The scan interval is clamped to the floor when read, in both the
  setup path and the options form, so a stored value below a raised floor
  cannot make the form unsubmittable. The floor is 60s (the default stays
  300s).
- **N8** — Comment only: `device_info` returning None is permanent, since
  Home Assistant reads it once at registration.

### Tests

`tests/` holds 41 tests for the api package, running without Home Assistant
installed:

```bash
python3 -m venv .venv && .venv/bin/pip install pytest requests
.venv/bin/python -m pytest -q
```

## 1.8.1 and earlier

See the upstream project: https://github.com/schmittx/home-assistant-eero
