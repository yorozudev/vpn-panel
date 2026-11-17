"""Независимый rolling reset базового БС-расхода.

Календарный пул bs_extra сначала нормализуется по старым счётчикам, затем они
удаляются. Так смена BS-периода не может ни обнулить докупку, ни списать её дважды.
"""

from datetime import datetime

from app import logger, scheduler
from app.db import GetDB, crud
from app.db.models import User
from app.models.user import UserStatus
from app.services.panel_settings import get_bs_monthly_limit
from app.xray.bs_limit import bs_reset_due, period_keys


def reset_user_bs_data_usage():
    now = datetime.utcnow()
    yyyymm = period_keys(now)
    with GetDB() as db:
        monthly_limit = get_bs_monthly_limit(db)
        users = (
            db.query(User)
            .filter(User.status.in_((UserStatus.active, UserStatus.limited)))
            .order_by(User.id)
            .all()
        )
        for user in users:
            if not bs_reset_due(user.bs_reset_strategy, user.bs_last_reset_at, user.created_at, now):
                continue

            base_limit = user.bs_monthly_limit if user.bs_monthly_limit is not None else monthly_limit
            # До удаления строк: глобальная докупка переносит только расход сверх
            # базы, персональная докупка по-прежнему живёт один календарный месяц.
            crud.normalize_bs_extra_period(db, user.id, int(base_limit or 0), yyyymm, persist=True)
            crud.reset_user_bs_usage(db, user, now)
            logger.info('User BS data usage reset for User "%s"', user.username)


scheduler.add_job(reset_user_bs_data_usage, "interval", coalesce=True, hours=1, max_instances=1)
