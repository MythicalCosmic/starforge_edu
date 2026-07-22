"""Static safety contracts for production backup and restore scripts."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUP_SCRIPT = (ROOT / "scripts" / "backup_production.sh").read_text(encoding="utf-8")
RESTORE_SCRIPT = (ROOT / "scripts" / "verify_restore.sh").read_text(encoding="utf-8")
DEPLOY_SCRIPT = (ROOT / "scripts" / "deploy_production.sh").read_text(encoding="utf-8")
BACKUP_EXAMPLE = (ROOT / "docker" / "backup.env.example").read_text(encoding="utf-8")


def test_backup_mode_preserves_offsite_and_requires_hardened_local_repository():
    assert 'BACKUP_MODE="${BACKUP_MODE:-offsite}"' in BACKUP_SCRIPT
    assert "BACKUP_MODE must be either local or offsite" in BACKUP_SCRIPT
    assert "LOCAL_BACKUP_ROOT must be an absolute non-root path" in BACKUP_SCRIPT
    assert "0:0:700" in BACKUP_SCRIPT
    assert "LOCAL_BACKUP_ROOT must be separate from deploy and repository paths" in BACKUP_SCRIPT
    assert "type=bind,src=${local_backup_root},dst=/repository" in BACKUP_SCRIPT
    assert "--network none" in BACKUP_SCRIPT


def test_backup_is_locked_capacity_gated_and_validates_dump_before_snapshot():
    lock = BACKUP_SCRIPT.index("flock -n 8")
    capacity = BACKUP_SCRIPT.index("require_local_capacity preflight")
    dump = BACKUP_SCRIPT.index('pg_dump -U "$POSTGRES_USER"')
    dump_validation = BACKUP_SCRIPT.index("pg_restore --list")
    snapshot = BACKUP_SCRIPT.index('backup /backup --host "$RESTIC_HOST"')

    assert lock < capacity < dump < dump_validation < snapshot
    assert "LOCAL_BACKUP_MIN_FREE_BYTES:-5368709120" in BACKUP_SCRIPT


def test_backup_creates_one_atomic_staged_snapshot_with_stable_retention():
    assert 'mkdir -p "$tmp_dir/minio"' in BACKUP_SCRIPT
    assert 'mkdir -p "$tmp_dir/deployment"' in BACKUP_SCRIPT
    assert BACKUP_SCRIPT.count("backup /backup") == 1
    assert "backup /objects" not in BACKUP_SCRIPT
    assert "backup /deployment" not in BACKUP_SCRIPT
    assert '--host "$RESTIC_HOST" --tag starforge --tag production' in BACKUP_SCRIPT
    assert "--group-by host,paths" in BACKUP_SCRIPT
    assert "--keep-last 5 --keep-daily 14 --keep-weekly 8 --keep-monthly 12" in BACKUP_SCRIPT
    assert '--network "container:${minio_container}"' in BACKUP_SCRIPT
    assert "http://127.0.0.1:9000" in BACKUP_SCRIPT


def test_verified_marker_is_written_only_after_retention_and_integrity_check():
    retention = BACKUP_SCRIPT.index("restic_run forget --prune")
    integrity = BACKUP_SCRIPT.index("restic_run check --read-data")
    marker = BACKUP_SCRIPT.index("${DEPLOY_DIR}/last_verified_backup")
    assert retention < integrity < marker


def test_restore_uses_the_local_mount_and_one_exact_atomic_snapshot():
    assert "type=bind,src=${local_backup_root},dst=/repository" in RESTORE_SCRIPT
    assert "last_verified_backup" in RESTORE_SCRIPT
    assert 'restore "$snapshot" --host "$RESTIC_HOST" --tag starforge' in RESTORE_SCRIPT
    assert "--tag postgres" not in RESTORE_SCRIPT
    assert "--tag minio" not in RESTORE_SCRIPT
    assert "--tag configuration" not in RESTORE_SCRIPT
    assert "--no-owner --no-acl" in RESTORE_SCRIPT
    assert "--memory=384m --cpus=0.5 --pids-limit=100" in RESTORE_SCRIPT


def test_deployment_verifies_the_new_snapshot_before_migrations():
    backup = DEPLOY_SCRIPT.index("scripts/backup_production.sh")
    restore = DEPLOY_SCRIPT.index("scripts/verify_restore.sh")
    migrations = DEPLOY_SCRIPT.index('echo "Applying public and tenant migrations..."')
    assert backup < restore < migrations


def test_backup_environment_documents_offsite_default_and_local_fallback():
    assert "BACKUP_MODE=offsite" in BACKUP_EXAMPLE
    assert "RESTIC_HOST=starforge-production" in BACKUP_EXAMPLE
    assert "# BACKUP_MODE=local" in BACKUP_EXAMPLE
    assert "# LOCAL_BACKUP_ROOT=/var/backups/starforge" in BACKUP_EXAMPLE
    assert "# RESTIC_REPOSITORY=/repository/restic" in BACKUP_EXAMPLE
