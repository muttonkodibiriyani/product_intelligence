# Website publish (Firebase Hosting): version record and rollback

Site `productintelligence-beeb3`. The Deployer publishes by hand until `deploy-web` lands. This
page covers what every publish report must record and how to roll back. Coordinator decision,
2026-10-07 (publish E).

## 1. Record the version before and after

firebase-tools has no command that lists Hosting versions, and no `hosting:rollback`. The version
id comes from the Hosting REST release history of the live channel (newest first, read-only):

```sh
curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://firebasehosting.googleapis.com/v1beta1/sites/productintelligence-beeb3/channels/live/releases?pageSize=5"
```

- **Before:** run it immediately before publishing. `releases[0].version.name` is the live version.
  The last path segment is the version id.
- **After:** run it again. `releases[0]` is now your release, and `releases[1]` must be the
  *before* version with no release in between.

Every publish report states:

- the build id served before and after (§1a);
- the version id before and after, with the release times;
- the rollback command for this publish (§2), with the *before* id filled in.

Copy the record into the decision-log row for that publish.

### 1a. Read the live build id

There is no `/build-id` path. The id is the `"b"` key in the `/app` page payload:

```sh
for l in en ar; do curl -s https://productintelligence-beeb3.web.app/app/$l/ | grep -o '\\"b\\":\\"[0-9a-f]*\\"' | sort -u; done
```

Each line must show the expected id, e.g. `\"b\":\"40fef057c352a191899f\"`. This read *discovers*
which id is live, so it is the one to record. The manifest only *confirms* an id you already know
(it answers 200 only for the build being served), so use it as corroboration, never on its own:

```sh
curl -s -o /dev/null -w '%{http_code}\n' https://productintelligence-beeb3.web.app/app/_next/static/<build id>/_buildManifest.js
```

Both reads cover `/app` only. The root shell is not covered by this id. If a publish changes the
root, check the root's own files (e.g. its `app.<hash>.js` name) as well.

**Settle window.** For about a minute after a release, Hosting's edge can still serve the old
release, and the new build's manifest returns 404. A wrong id or a 404 in that window means "too
early", not "failed", and is never grounds to roll back. Retry the "b" read for up to two
minutes before you conclude anything.

## 2. Roll back

Roll back with a pointer flip to the *before* version. It uploads and rebuilds nothing:

```sh
firebase hosting:clone productintelligence-beeb3@<before versionId> productintelligence-beeb3:live
```

On the same site, `hosting:clone <site>@<version>` only creates a live release of an existing
version (Hosting REST `releases.create`). If the source is already live, it logs "serving
identical versions" and does nothing.

**A rollback reverts the whole site.** `infra/firebase.json` has one hosting entry
(`public: web-dist`), and `web-dist` holds both halves of the site: the root shell
(`apps/web/dist`) and `/app` (`out-assistant`). A version is that whole file set, so a rollback
flips the root and `/app` together; neither half can be rolled back alone. If a change to the root
and a change to `/app` must stay separately revertible, publish them as two releases, one after
the other.

After rolling back, read the live build id (§1a) on both `/app/en/` and `/app/ar/`, check that it
equals the *before* build id, and report it.

Fallbacks:
- the previous release in the Firebase console (Hosting → release history → Rollback);
- or re-publishing that build's commit through the normal publish path.

Do not probe for a firebase subcommand with `--help`. An unknown `hosting:*` subcommand prints
top-level usage and exits 0.

## 3. Example: publish E (#279), 2026-10-07

| | Build | Version | Released |
|---|---|---|---|
| Before (#276, `1dbc86f0`) | `98169f4ffe340d532e33` | `74666ea11dc18b70` | 14:20:30Z |
| After (#279, `67496647`) | `40fef057c352a191899f` | `6d0248891e10a5c8` | 17:13:33Z |

Rollback for E:
`firebase hosting:clone productintelligence-beeb3@74666ea11dc18b70 productintelligence-beeb3:live`
