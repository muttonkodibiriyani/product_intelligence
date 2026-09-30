# Runbook: nightly PostgreSQL backup and restore

The local PostgreSQL (`infra/docker-compose.yml`, container `product-intelligence-postgres-1`,
database `pi`) is the only copy of the collected data. Every night at 02:30 UTC,
`infra/scripts/pg_backup.py backup`:

1. runs `pg_dump -Fc` inside the container, so the tool version always matches the server;
2. checks the archive with `pg_restore --list`, and refuses to upload one without table data;
3. uploads it to `gs://productintelligence-beeb3-pg-backups/postgres/pi/YYYY/MM/DD/pi-<stamp>.dump`
   as `pi-db-backup@…`, create-only (`ifGenerationMatch=0`), with its sha256 in the object
   metadata, then compares the md5 GCS computed with the local one;
4. keeps the newest 3 dumps locally in `~/.local/state/pi-backup/`, and writes `status.json` there.

**Cost:** one dump is about 3.4 MB (2026-09-30). 14 days of them in me-central1 cost well under
$0.01/month.

## Who can do what

| Identity | Can | Cannot |
|---|---|---|
| `pi-db-backup@productintelligence-beeb3.iam.gserviceaccount.com` | create objects in the backup bucket | read, list, overwrite or delete them; anything else in the project |
| the server's existing Firebase admin credentials | mint a 15-minute token for `pi-db-backup` only | (no new rights on anything else) |
| project owners | read and restore backups | |

`pi-db-backup` has **no key**. The bucket has uniform bucket-level access and enforced public
access prevention. Objects are deleted 14 days after upload; soft delete then keeps them 7 more
days. All of this is in `infra/gcp/pg_backup_setup.sh` and `infra/gcp/pg-backups-lifecycle.json`.

## One-time setup (owner, Google Cloud Shell)

```bash
git clone https://github.com/muttonkodibiriyani/product_intelligence.git && cd product_intelligence/infra/gcp
gcloud config set project productintelligence-beeb3
./pg_backup_setup.sh     # idempotent; prints "ok: ..." at the end
```

## Enable on the server (after setup and merge)

Create the state directory once (`mkdir -p ~/.local/state/pi-backup`), then add this line with
`crontab -e` (as `tm8`, from the shared clone on `main`):

```cron
30 2 * * * cd /home/tm8/projects/product_intelligence && GOOGLE_APPLICATION_CREDENTIALS=/home/tm8/.config/firebase-sa/productintelligence-beeb3.json /usr/bin/flock -n /home/tm8/.local/state/pi-backup/lock /home/tm8/.local/bin/uv run --script infra/scripts/pg_backup.py backup >> /home/tm8/.local/state/pi-backup/backup.log 2>&1
```

Run it once by hand the same way; the first object should appear within a minute.

## Is it working?

```bash
uv run --script infra/scripts/pg_backup.py check   # exit 0 "backup ok"; exit 1 "ATTENTION ..."
tail -5 ~/.local/state/pi-backup/backup.log         # a failure line starts with "FAILED"
```

`check` fails when the last run failed, or when the last success is older than 26 hours. As an
owner, `gcloud storage ls -l gs://productintelligence-beeb3-pg-backups/postgres/pi/**` lists what
is actually stored.

## Restore

1. Download the dump (owner credentials) and check it against the sha256 in its metadata:

   ```bash
   OBJ=gs://productintelligence-beeb3-pg-backups/postgres/pi/2026/10/01/pi-20261001T023000Z.dump
   gcloud storage cp "$OBJ" pi.dump
   gcloud storage objects describe "$OBJ" --format='value(metadata.sha256)'; sha256sum pi.dump
   ```

2. Restore into a scratch database first, and compare row counts with live. The command below
   creates `pi_restore_check` in the same container and drops it afterwards:

   ```bash
   uv run --script infra/scripts/pg_backup.py restore-test pi.dump
   ```

   `COMPLETE` means every table is present and none has more rows than live. Live may have more
   rows if data was written after the dump.

3. To replace `pi` itself, first stop every writer (crawlers, loaders), keep the current volume
   (`docker volume ls`), then:

   ```bash
   docker exec product-intelligence-postgres-1 psql -U pi -d postgres -c "DROP DATABASE pi" -c "CREATE DATABASE pi"
   docker exec -i product-intelligence-postgres-1 pg_restore -U pi -d pi --no-owner --exit-on-error < pi.dump
   ```

### Known issue: dumps taken before the pi_db search_path fix

`public.pi_field_state_valid` names the `field_state` enum without its schema. pg_restore runs
with an empty `search_path`, so a plain restore stops at the first `ATTACH PARTITION` with
`type "field_state" does not exist`. The dump itself is complete. Until the pi_db migration that
qualifies the type is merged, **and for any dump taken before it**, restore through SQL with that
one reference qualified:

```bash
docker exec -i product-intelligence-postgres-1 pg_restore -f - --no-owner < pi.dump \
  | sed 's/enum_range(NULL::field_state)/enum_range(NULL::public.field_state)/' > pi.sql
grep -c 'NULL::public.field_state' pi.sql      # must print 1
docker exec -i product-intelligence-postgres-1 psql -U pi -d <target_db> -q -v ON_ERROR_STOP=1 < pi.sql
```

## Restore test record

| Date (UTC) | Dump | Size | Method | Result |
|---|---|---|---|---|
| 2026-09-30 23:27 | `pi-20260930T232735Z.dump` (local, same code path as nightly), sha256 `58aefde8…95ca53` | 3,383,756 B, 48 table-data entries | plain `pg_restore`: **failed** (known issue above); SQL route with the one-token fix: **COMPLETE** | 49 tables, 26,632 rows, all equal to live; 24 `offer_observation` partitions attached; scratch DB dropped |

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

Next entry: the first nightly object downloaded from GCS and restored with `restore-test`, once
the setup has run and the pi_db fix is merged.
