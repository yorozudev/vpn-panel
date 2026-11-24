"""Удаление истёкших current/previous per-device VLESS credentials."""

from datetime import datetime

from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload

from app import logger, scheduler, xray
from app.db import GetDB
from app.db.models import UserDevice


def expire_device_credentials(now: datetime | None = None) -> None:
    """Отозвать просроченные UUID, не меняя стабильный device_id и usage."""
    now = now or datetime.utcnow()
    with GetDB() as db:
        devices = (
            db.query(UserDevice)
            .options(joinedload(UserDevice.user))
            .filter(
                UserDevice.status == "active",
                or_(
                    and_(
                        UserDevice.vless_uuid.isnot(None),
                        UserDevice.vless_uuid_expires_at.isnot(None),
                        UserDevice.vless_uuid_expires_at <= now,
                    ),
                    and_(
                        UserDevice.previous_vless_uuid.isnot(None),
                        UserDevice.previous_vless_uuid_expires_at.isnot(None),
                        UserDevice.previous_vless_uuid_expires_at <= now,
                    ),
                ),
            )
            .order_by(UserDevice.id.asc())
            .all()
        )
        for device in devices:
            current_expired = bool(
                device.vless_uuid
                and device.vless_uuid_expires_at is not None
                and device.vless_uuid_expires_at <= now
            )
            previous_expired = bool(
                device.previous_vless_uuid
                and device.previous_vless_uuid_expires_at is not None
                and device.previous_vless_uuid_expires_at <= now
            )
            if not current_expired and not previous_expired:
                continue

            dbuser = device.user
            if current_expired:
                device.vless_uuid = None
                device.vless_uuid_expires_at = None
            if previous_expired:
                device.previous_vless_uuid = None
                device.previous_vless_uuid_expires_at = None
            db.commit()

            if current_expired:
                xray.operations.remove_device_credential(dbuser, device, previous=False)
            if previous_expired:
                xray.operations.remove_device_credential(dbuser, device, previous=True)
            logger.info(
                '[device-credentials] expired credentials revoked user="%s" device_id=%s current=%s previous=%s',
                dbuser.username,
                device.id,
                current_expired,
                previous_expired,
            )


scheduler.add_job(
    expire_device_credentials,
    "interval",
    minutes=5,
    coalesce=True,
    max_instances=1,
)
