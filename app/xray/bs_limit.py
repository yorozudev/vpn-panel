"""Чистые функции для по-нодного лимита БС-нод (NPVPN-1456).

Без зависимостей от БД/окружения — тестируются как cascade_config/inbound_filter.
"""



BS_RESET_STRATEGY_TO_DAYS = {
    "day": 1,
    "week": 7,
    "month": 30,
    "year": 365,
}


def period_keys(now):
    """Календарный месяц докупки bs_extra; период базового лимита не использует его."""
    return now.strftime("%Y-%m")


def _strategy_value(strategy):
    return getattr(strategy, "value", strategy) or "month"


def bs_period_anchor(last_reset_at, created_at):
    return last_reset_at or created_at


def bs_usage_period(strategy, last_reset_at, created_at, now):
    """Стабильный маркер текущего BS-периода пользователя.

    Период начинается с последнего сброса, как и обычный traffic reset. Старые
    объекты без anchor продолжают читать legacy-счётчик YYYY-MM до первого сброса.
    """
    anchor = bs_period_anchor(last_reset_at, created_at)
    if last_reset_at is None:
        return period_keys(now)
    return anchor.isoformat(timespec="seconds")


def bs_reset_due(strategy, last_reset_at, created_at, now):
    """Те же rolling day/week/month/year и правило `.days`, что у обычного reset."""
    anchor = bs_period_anchor(last_reset_at, created_at)
    if anchor is None:
        return False
    days = BS_RESET_STRATEGY_TO_DAYS[_strategy_value(strategy)]
    return (now - anchor).days >= days


def bs_counter_step(existing, delta, period):
    """Новые значения счётчика с ленивым сбросом выбранного периода.

    existing — dict с ключами monthly_used/monthly_period либо None (строки ещё нет).
    """
    existing = existing or {}
    monthly_base = existing.get("monthly_used", 0) if existing.get("monthly_period") == period else 0
    return {
        "monthly_used": monthly_base + delta,
        "monthly_period": period,
    }


def diff_blocks(desired, current):
    """desired/current — множества (node_id, user_id). → (to_block, to_unblock)."""
    return desired - current, current - desired


def aggregate_bs_usage(rows, period):
    """rows: iterable of dict(user_id, monthly_used, monthly_period).
    → {user_id: monthly_used}, считая только актуальный период."""
    totals = {}
    for r in rows:
        if r.get("monthly_period") != period:
            continue
        uid = r["user_id"]
        totals[uid] = totals.get(uid, 0) + (r.get("monthly_used") or 0)
    return totals


def aggregate_bs_usage_by_period(rows, periods):
    """Агрегат для пользователей с разными стратегиями в одном batch."""
    totals = {}
    for row in rows:
        uid = row["user_id"]
        if row.get("monthly_period") != periods.get(uid):
            continue
        totals[uid] = totals.get(uid, 0) + (row.get("monthly_used") or 0)
    return totals


def over_limit(monthly_used, monthly_limit):
    """True, если превышен заданный (>0) месячный лимит. 0/None = лимит не задан."""
    if monthly_limit and monthly_used >= monthly_limit:
        return True
    return False


def monthly_effective_limit(monthly_limit, bs_extra_remaining):
    """Месячный потолок: база + остаток купленного пула."""
    if not monthly_limit:
        return 0
    return int(monthly_limit) + int(bs_extra_remaining or 0)


def carry_over_pool(pool, prev_used, monthly_limit):
    """Пул, переносимый на новый месяц: из купленного вычитается расход сверх базы.

    Сгорает только потраченное — неизрасходованная часть пула живёт дальше.
    monthly_limit == 0 (лимит не задан) → пул не трогаем.
    """
    if not monthly_limit:
        return int(pool or 0)
    return max(0, int(pool or 0) - max(0, int(prev_used) - int(monthly_limit)))


def over_limit_monthly_pool(monthly_used, monthly_limit, bs_extra_remaining):
    """Блок: месячный лимит+пул исчерпаны."""
    if not monthly_limit:
        return False
    return int(monthly_used) >= monthly_effective_limit(monthly_limit, bs_extra_remaining)


_GIB = 1024**3


def format_gib_label(n_bytes) -> str:
    """Гибибайты с одной цифрой после запятой. Целые без дроби: 3, не 3,0."""
    n = max(0, int(n_bytes or 0))
    tenths = (n * 10 + _GIB // 2) // _GIB
    whole, frac = divmod(tenths, 10)
    if frac == 0:
        return str(whole)
    return f"{whole},{frac}"


def format_bs_usage_suffix(used_bytes, limit_bytes) -> str:
    """Хвост имени БС-хоста: « - (1,2/3 ГБ)»."""
    return f" - ({format_gib_label(used_bytes)}/{format_gib_label(limit_bytes)} ГБ)"


def pick_bs_bar(monthly_used, monthly_limit_eff):
    """(used, total) для месячного лимита; None, если лимит не задан."""
    if not monthly_limit_eff:
        return None
    return monthly_used, monthly_limit_eff


def bs_stub_remark(text_list):
    """Имя сервера-заглушки БС-лимита из настройки sub_bs_limit_server_text.

    БС-хост заменяется заглушкой НА СВОЁМ МЕСТЕ (один хост → одна заглушка),
    поэтому многострочный текст склеивается в одно имя сервера. Пустые строки
    отбрасываются. Принимает список строк, одну строку или None.
    """
    if not text_list:
        return ""
    lines = [text_list] if isinstance(text_list, str) else list(text_list)
    parts = [str(x).strip() for x in lines]
    return " ".join(p for p in parts if p)


def strip_blocked_clients(config, blocked_user_ids):
    """Копия config без клиентов заблокированных user_id во всех инбаундах.

    Матчинг по префиксу email '<uid>.' (email клиента = '<user_id>.<username>').
    Пустой набор → исходный объект без копирования (no-op). Затронутые инбаунды
    пересобираются новыми dict, поэтому функция корректна даже при поверхностном
    config.copy() и не мутирует вход.
    """
    if not blocked_user_ids:
        return config
    cfg = config.copy()
    prefixes = tuple(f"{uid}." for uid in blocked_user_ids)
    new_inbounds = []
    for inbound in cfg["inbounds"]:
        settings = inbound.get("settings")
        clients = settings.get("clients") if settings else None
        if not clients:
            new_inbounds.append(inbound)
            continue
        new_settings = dict(settings)
        new_settings["clients"] = [c for c in clients if not str(c.get("email", "")).startswith(prefixes)]
        new_inbound = dict(inbound)
        new_inbound["settings"] = new_settings
        new_inbounds.append(new_inbound)
    cfg["inbounds"] = new_inbounds
    return cfg
