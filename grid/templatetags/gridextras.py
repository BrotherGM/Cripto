"""Шаблонные фильтры для управления порядком приложений в меню админки."""
from django import template

register = template.Library()


@register.filter
def apps_except(app_list, labels):
    """Приложения из app_list, КРОМЕ перечисленных app_label (через запятую)."""
    labs = {s.strip() for s in labels.split(",")}
    return [a for a in app_list if a.get("app_label") not in labs]


@register.filter
def apps_only(app_list, labels):
    """Только приложения из app_list с указанными app_label (через запятую)."""
    labs = {s.strip() for s in labels.split(",")}
    return [a for a in app_list if a.get("app_label") in labs]
