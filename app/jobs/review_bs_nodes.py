"""Reconcile агрегатного лимита БС-нод (NPVPN-1456).

Суммирует node_user_bs_usage по всем is_bs-нодам юзера за текущий месяц,
сравнивает с общим месячным лимитом панели и при превышении
блокирует юзера на ВСЕХ БС-нодах (node_user_blocks). Тяжёлую node_user_usages не трогает.
"""

import time
from datetime import datetime

from sqlalchemy import func

from app import logger, scheduler, xray
from app.db import GetDB
from app.db.crud import get_user_by_id
from app.db.models import Node, NodeUserBlock, NodeUserBsUsage, User
from app.models.user import UserStatus
from app.services.panel_settings import get_bs_monthly_limit
from app.xray.bs_limit import (
    aggregate_bs_usage_by_period,
    bs_usage_period,
    carry_over_pool,
    diff_blocks,
    over_limit_monthly_pool,
    period_keys,
)
from config import JOB_REVIEW_BS_NODES_INTERVAL


def _stale_used_since(rows, since):
    """Сумма расхода по несброшенным периодам, начиная с периода пула (включительно)."""
    return sum(used for period, used in rows if period >= since)


def _effective_pool(bs_extra, extra_period, yyyymm, stale_rows, monthly_limit, personal_limit=None):
    """Купленный пул, приведённый к текущему месяцу, — батчевый аналог нормализации.

    Не через crud.normalize_bs_extra_period: тут разом проверяются все пользователи с
    БС-расходом, а канонический путь — запрос (и запись) на каждого за тик. Расчёт тем
    не менее эквивалентен: та же carry_over_pool и та же нижняя граница по периоду пула
    (extra_period), только батчем и read-only — единственный писатель пула остаётся
    джоба учёта.
    """
    # Сравнение то же, что в crud.normalize_bs_extra_period: период «из будущего» — тоже
    # no-op, иначе строка счётчика с этим периодом пройдёт фильтр stale_rows и срежет
    # потолок, а сводка API и бар подписки в тот же момент покажут юзеру остаток.
    if not extra_period or extra_period >= yyyymm:
        return bs_extra
    if personal_limit is not None:
        return 0
    return carry_over_pool(bs_extra, _stale_used_since(stale_rows, extra_period), monthly_limit)


def review_bs_nodes():
    t0 = time.monotonic()
    now = datetime.utcnow()
    yyyymm = period_keys(now)
    to_block, to_unblock = set(), set()

    with GetDB() as db:
        bs_node_ids = {nid for (nid,) in db.query(Node.id).filter(Node.is_bs.is_(True)).all()}
        if not bs_node_ids:
            return

        usage_rows = (
            db.query(
                NodeUserBsUsage.user_id,
                NodeUserBsUsage.monthly_used,
                NodeUserBsUsage.monthly_period,
            )
            .filter(NodeUserBsUsage.node_id.in_(bs_node_ids))
            .all()
        )

        # Персональный 0 блокирует даже без строк расхода. А старые строки тоже
        # включаем в список: после rolling reset пользователь должен разблокироваться.
        override_user_ids = {
            uid
            for (uid,) in db.query(User.id).filter(User.bs_monthly_limit.is_not(None)).all()
        }
        user_ids = list({r.user_id for r in usage_rows} | override_user_ids)
        stale_rows = (
            db.query(
                NodeUserBsUsage.user_id,
                NodeUserBsUsage.monthly_period,
                func.sum(NodeUserBsUsage.monthly_used).label("used"),
            )
            .filter(
                NodeUserBsUsage.node_id.in_(bs_node_ids),
                NodeUserBsUsage.user_id.in_(user_ids),
            )
            .group_by(NodeUserBsUsage.user_id, NodeUserBsUsage.monthly_period)
            .all()
            if user_ids
            else []
        )
        stale = {}
        for r in stale_rows:
            stale.setdefault(r.user_id, []).append((r.monthly_period, int(r.used or 0)))

        monthly_limit = get_bs_monthly_limit(db)
        user_info = (
            {
                r.id: {
                    "personal_limit": r.bs_monthly_limit,
                    "bs_extra": r.bs_extra or 0,
                    "extra_period": r.bs_extra_period,
                    "usage_period": bs_usage_period(
                        r.bs_reset_strategy, r.bs_last_reset_at, r.created_at, now
                    ),
                }
                for r in db.query(
                    User.id,
                    User.bs_monthly_limit,
                    User.bs_extra,
                    User.bs_extra_period,
                    User.bs_reset_strategy,
                    User.bs_last_reset_at,
                    User.created_at,
                )
                .filter(User.id.in_(user_ids))
                .all()
            }
            if user_ids
            else {}
        )
        totals = aggregate_bs_usage_by_period(
            [
                {
                    "user_id": r.user_id,
                    "monthly_used": r.monthly_used,
                    "monthly_period": r.monthly_period,
                }
                for r in usage_rows
            ],
            {uid: info["usage_period"] for uid, info in user_info.items()},
        )

        over_users = set()
        for uid in user_ids:
            info = user_info.get(uid)
            if info is None:
                continue
            personal_limit = info["personal_limit"]
            bs_extra = info["bs_extra"]
            extra_period = info["extra_period"]
            monthly_used = totals.get(uid, 0)
            # В отличие от глобального 0 (лимит не задан), персональный 0 — запрет.
            if personal_limit == 0:
                over_users.add(uid)
                continue
            base_limit = personal_limit if personal_limit is not None else monthly_limit
            pool = _effective_pool(
                bs_extra,
                extra_period,
                yyyymm,
                stale.get(uid, []),
                base_limit,
                personal_limit,
            )
            if over_limit_monthly_pool(monthly_used, base_limit, pool):
                over_users.add(uid)

        desired = {(nid, uid) for uid in over_users for nid in bs_node_ids}

        current_rows = db.query(NodeUserBlock.id, NodeUserBlock.node_id, NodeUserBlock.user_id).all()
        current = {(r.node_id, r.user_id) for r in current_rows}
        block_id = {(r.node_id, r.user_id): r.id for r in current_rows}

        to_block, to_unblock = diff_blocks(desired, current)

        for node_id, user_id in to_block:
            dbuser = get_user_by_id(db, user_id)
            if not dbuser:
                continue
            db.add(NodeUserBlock(node_id=node_id, user_id=user_id, period="agg", created_at=datetime.utcnow()))
            db.commit()
            try:
                xray.operations.remove_user_from_node(dbuser, node_id)
            except Exception as e:
                logger.warning(
                    f"[review_bs_nodes] remove failed node={node_id} user_id={user_id}: {type(e).__name__}: {e}"
                )
            logger.info(f"[review_bs_nodes] blocked user_id={user_id} on node_id={node_id}")

        for node_id, user_id in to_unblock:
            bid = block_id.get((node_id, user_id))
            if bid is not None:
                db.query(NodeUserBlock).filter(NodeUserBlock.id == bid).delete()
                db.commit()
            dbuser = get_user_by_id(db, user_id)
            if dbuser and dbuser.status in (UserStatus.active, UserStatus.on_hold):
                try:
                    xray.operations.add_user_to_node(dbuser, node_id)
                except Exception as e:
                    logger.warning(
                        f"[review_bs_nodes] add failed node={node_id} user_id={user_id}: {type(e).__name__}: {e}"
                    )
            logger.info(f"[review_bs_nodes] unblocked user_id={user_id} on node_id={node_id}")

    if to_block or to_unblock:
        logger.info(
            f"[review_bs_nodes] done blocked={len(to_block)} unblocked={len(to_unblock)} "
            f"dt={time.monotonic() - t0:.2f}s"
        )


scheduler.add_job(review_bs_nodes, "interval", seconds=JOB_REVIEW_BS_NODES_INTERVAL, coalesce=True, max_instances=1)
