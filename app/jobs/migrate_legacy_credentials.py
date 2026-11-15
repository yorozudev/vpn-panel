from datetime import datetime

from sqlalchemy.orm import selectinload

from app import logger, scheduler, xray
from app.db import GetDB
from app.db.models import User
from app.models.user import UserStatus
from app.xray.legacy_migration import legacy_migration_status
from config import DEVICE_LEGACY_MIGRATION_GRACE_PERIOD, JOB_DEVICE_LEGACY_MIGRATION_INTERVAL


def migrate_legacy_credentials() -> None:
    """Отключить legacy VLESS только у индивидуально готовых пользователей."""
    now = datetime.utcnow()
    with GetDB() as db:
        users = (
            db.query(User)
            .options(selectinload(User.devices))
            .filter(
                User.legacy_vless_enabled.is_(True),
                User.status.in_([UserStatus.active, UserStatus.on_hold]),
            )
            .all()
        )
        ready_users = [
            user
            for user in users
            if legacy_migration_status(
                user,
                user.devices,
                now=now,
                grace_seconds=DEVICE_LEGACY_MIGRATION_GRACE_PERIOD,
            )[0]
        ]
        for user in ready_users:
            # Повторно проверяем флаг в UPDATE: ручной rollback в соседнем запросе
            # не должен быть перезаписан этим проходом.
            user.legacy_vless_enabled = False
            user.legacy_vless_disabled_at = now
            db.commit()
            db.refresh(user)
            xray.operations.remove_legacy_vless(user)
            logger.info('[device-migration] legacy VLESS disabled for user "%s"', user.username)


scheduler.add_job(
    migrate_legacy_credentials,
    "interval",
    seconds=JOB_DEVICE_LEGACY_MIGRATION_INTERVAL,
    coalesce=True,
    max_instances=1,
)
