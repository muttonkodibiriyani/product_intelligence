# Runbook: nightly PostgreSQL backup and restore

The local PostgreSQL (`infra/docker-compose.yml`, container `product-intelligence-postgres-1`,
database `pi`) is the only copy of the collected data. Every night at 02:30 UTC,
`infra/scripts/pg_backup.py backup`:

1. runs `pg_dump -Fc` inside the container, so the tool version always matches the server;
2. checks the archive with `pg_restore --list`, and refuses to upload one without table data;
3. **restores it** into a scratch database (`pi_backup_verify`, dropped afterwards) and counts
   every table. A dump that does not restore, or restores no rows, is not uploaded;
4. uploads it to `gs://productintelligence-beeb3-pg-backups/postgres/pi/YYYY/MM/DD/pi-<stamp>.dump`
   as `pi-db-backup@…`, create-only (`ifGenerationMatch=0`), with its md5 sent for GCS to check and
   its sha256 in the object metadata. The per-table row counts from step 3 go next to it as
   `pi-<stamp>.dump.counts.json`;
5. keeps the newest 3 dumps (and their counts) locally in `~/.local/state/pi-backup/`, mode 0700,
   and writes `status.json` there.

At 04:00 UTC `pg_backup.py check` reads `status.json`. While the last run failed or the last success
is older than 26 hours, it exits 1 and keeps `~/.local/state/pi-backup/ATTENTION` present.

**Cost:** one dump is about 3.4 MB (2026-09-30). 14 days of them in me-central1 cost well under
$0.01/month. The upload is built in memory; switch it to a resumable upload if `bytes` in
`status.json` approaches ~100 MB.

> **The 14-day cliff.** The bucket deletes objects by age, not "keep the newest N". If backups
> fail for 14 days and nobody acts, there is **no** off-site copy left (soft delete keeps deleted
> objects 7 more days). That is why `check` runs every day and `ATTENTION` must be watched.

## Who can do what

| Identity | Can | Cannot |
|---|---|---|
| `pi-db-backup@productintelligence-beeb3.iam.gserviceaccount.com` | create objects in the backup bucket | read, list, overwrite or delete them; anything else in the project |
| the server's existing Firebase admin credentials | mint a 15-minute token for `pi-db-backup` (the only right this setup adds) | — |
| project owners | read, restore **and delete** backups | |

The "cannot delete" row is about the uploader only. The server's Firebase admin key already has
broad project rights (including storage), so someone who takes over the host could delete the
backups; soft delete (7 days) is then the only protection. Keeping backups out of that key's reach
would need a second project or a locked retention policy; not done at this size.

`pi-db-backup` has **no key**. The bucket has uniform bucket-level access and enforced public
access prevention. Objects are deleted 14 days after upload; soft delete then keeps them 7 more
days. All of this is in `infra/gcp/pg_backup_setup.sh` and `infra/gcp/pg-backups-lifecycle.json`.

## One-time setup (owner, Google Cloud Shell)

```bash
git clone https://github.com/muttonkodibiriyani/product_intelligence.git && cd product_intelligence/infra/gcp
gcloud config set project productintelligence-beeb3
./pg_backup_setup.sh     # idempotent; prints "ok: ..." at the end
```

## Enable on the server (after setup, merge, and pi_db migration 0002)

The nightly restore-verify uses plain `pg_restore`, so the local `pi` must be at pi_db migration
0002 or later ([#49](https://github.com/muttonkodibiriyani/product_intelligence/pull/49)); before
that every run fails (visibly) with `type "field_state" does not exist`. Local `pi` has been at 0003
since 2026-10-01 00:06 UTC.

The crontab lines are installed **by the owner** (as `tm8`, `crontab -e`): an agent's attempt to
install them was refused by Claude Code's safety classifier as persistence (2026-09-30), which is
the intended guard. The checkout and state directory below already exist on the server.

Cron runs from a dedicated checkout pinned to `origin/main`, not the shared clone (other work moves
that one). As `tm8`:

```bash
git -C /home/tm8/projects/product_intelligence fetch origin
git -C /home/tm8/projects/product_intelligence worktree add --detach /home/tm8/projects/pi-backup-cron origin/main
mkdir -p -m 700 ~/.local/state/pi-backup
```

To pick up a later change: `git -C /home/tm8/projects/pi-backup-cron checkout --detach origin/main`
after a fetch. Nothing else uses that directory. Then add with `crontab -e`:

```cron
30 2 * * * cd /home/tm8/projects/pi-backup-cron && GOOGLE_APPLICATION_CREDENTIALS=/home/tm8/.config/firebase-sa/productintelligence-beeb3.json /usr/bin/flock -n /home/tm8/.local/state/pi-backup/lock /home/tm8/.local/bin/uv run --script infra/scripts/pg_backup.py backup >> /home/tm8/.local/state/pi-backup/backup.log 2>&1
0 4 * * * cd /home/tm8/projects/pi-backup-cron && /home/tm8/.local/bin/uv run --script infra/scripts/pg_backup.py check >> /home/tm8/.local/state/pi-backup/check.log 2>&1
```

Run the backup once by hand the same way; the first object should appear within a minute.

## Is it working?

```bash
test -e ~/.local/state/pi-backup/ATTENTION && cat ~/.local/state/pi-backup/ATTENTION   # set by the 04:00 check
uv run --script infra/scripts/pg_backup.py check   # exit 0 "backup ok"; exit 1 "ATTENTION ..."
tail -5 ~/.local/state/pi-backup/backup.log         # a failure line starts with "FAILED"
```

Whoever watches this server (the ops monitor or the infra agent) reads `ATTENTION` on each pass
and raises it to the owner. Any stronger notification channel is the owner's choice.

`check` fails when the last run failed, or when the last success is older than 26 hours. As an
owner, `gcloud storage ls -l gs://productintelligence-beeb3-pg-backups/postgres/pi/**` lists what
is actually stored.

## Restore

1. Download the dump and its counts (owner credentials), and check the dump against the sha256
   in its metadata:

   ```bash
   OBJ=gs://productintelligence-beeb3-pg-backups/postgres/pi/2026/10/01/pi-20261001T023000Z.dump
   gcloud storage cp "$OBJ" pi.dump && gcloud storage cp "$OBJ.counts.json" pi.dump.counts.json
   gcloud storage objects describe "$OBJ" --format='value(custom_fields.sha256)'; sha256sum pi.dump
   ```

2. Restore into a scratch database first. The command below creates `pi_restore_check` in the
   same container, restores, counts every table, and drops it afterwards:

   ```bash
   uv run --script infra/scripts/pg_backup.py restore-test pi.dump   # reads pi.dump.counts.json
   ```

   `COMPLETE` means exactly the tables and row counts recorded when the dump was taken (the counts
   file must carry this dump's sha256). Live counts are printed for information only.

3. To replace `pi` itself, first stop every writer (crawlers, loaders), keep the current volume
   (`docker volume ls`), then:

   ```bash
   docker exec product-intelligence-postgres-1 psql -U pi -d postgres -c "DROP DATABASE pi" -c "CREATE DATABASE pi"
   docker exec -i product-intelligence-postgres-1 pg_restore -U pi -d pi --no-owner --exit-on-error < pi.dump
   ```

### Known issue: dumps taken before the pi_db search_path fix

`public.pi_field_state_valid` names the `field_state` enum without its schema. pg_restore runs
with an empty `search_path`, so a plain restore stops at the first `ATTACH PARTITION` with
`type "field_state" does not exist`. The dump itself is complete. pi_db migration 0002
([#49](https://github.com/muttonkodibiriyani/product_intelligence/pull/49)) qualifies the type;
dumps taken after `alembic upgrade head` restore with plain `pg_restore`. Local `pi` was upgraded
at 2026-09-30 23:57 UTC, so every object in the backup bucket is a plain-restore dump. For any dump taken
before it, restore through SQL with that one reference qualified:

```bash
docker exec -i product-intelligence-postgres-1 pg_restore -f - --no-owner < pi.dump \
  | sed 's/enum_range(NULL::field_state)/enum_range(NULL::public.field_state)/' > pi.sql
grep -c 'NULL::public.field_state' pi.sql      # must print 1
docker exec -i product-intelligence-postgres-1 psql -U pi -d <target_db> -q -v ON_ERROR_STOP=1 < pi.sql
```

## Restore test record

| Date (UTC) | Dump | Size | Method | Result |
|---|---|---|---|---|
| 2026-09-30 23:27 | `pi-20260930T232735Z.dump` (local, same code path as nightly), sha256 `58aefde8…95ca53` | 3,383,756 B, 48 table-data entries | plain `pg_restore`: **failed** (known issue above); SQL route with the one-token fix: **COMPLETE** | 49 tables, 26,632 rows, all equal to live (no writes between dump and count); 24 `offer_observation` partitions attached; scratch DB dropped |
| 2026-09-30 23:37 | `backup` with the restore-verify step, local `pi` at 0001 | 3,383,756 B | nightly code path | **failed before upload**, as intended: `pg_restore failed: … type "field_state" does not exist`; `check` exit 1 and `ATTENTION` written |
| 2026-09-30 23:58 | `gs://…-pg-backups/postgres/pi/2026/09/30/pi-20260930T235729Z.dump` (first object in GCS; manual run of the nightly path, `pi` at 0002), sha256 `0ccfafce…effdae6f` | 4,768,432 B, 48 table-data entries | downloaded from GCS; sha256 equal to object metadata; `restore-test` (plain `pg_restore`) | **COMPLETE**: 49 tables, 38,370 rows, every table equal to the counts file; scratch DB dropped; `check` → `backup ok` |
| 2026-10-01 00:05 | `pi-20261001T000511Z.dump` (pre-0003 safety copy) and `pi-20261001T000552Z.dump` (after 0003) | 4,768,432 / 4,768,505 B | nightly code path (restore-verify before upload) | both restore-verified, 49 tables / 38,370 rows; live counts after `alembic upgrade` 0002 → 0003 identical to the pre-upgrade counts file |

Row counts from that test (all tables not listed had 0 rows in both live and restored):

| table | live | restored |
|---|---:|---:|
| public.alembic_version | 1 | 1 |
| public.brand | 158 | 158 |
| public.crawl_run | 2 | 2 |
| public.evidence | 2,600 | 2,600 |
| public.listing_content | 5,967 | 5,967 |
| public.offer_observation (all in p202609) | 5,967 | 5,967 |
| public.source | 1 | 1 |
| public.source_context | 2 | 2 |
| public.source_listing | 5,967 | 5,967 |

Next entry: the first object written by the 02:30 cron, once the owner has installed it.
