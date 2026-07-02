from django import forms

from grid.models import GridType


class QuickStrategyForm(forms.Form):
    """Форма быстрого создания стратегий по парам (с авто-заполнением полей)."""

    pairs = forms.CharField(
        label="Пары",
        widget=forms.Textarea(attrs={"rows": 4, "cols": 40,
                                     "placeholder": "XRP-USDT\nETH-USDT\nSOL-USDT"}),
        help_text="По одной паре в строке (или через запятую), формат BASE-USDT.",
    )
    range_pct = forms.DecimalField(
        label="Диапазон, ± %", initial=10, min_value=1, max_value=90,
        help_text="Границы Pmax/Pmin = текущая цена ± этот процент.",
    )
    levels = forms.IntegerField(
        label="Число уровней N", initial=10, min_value=2, max_value=100,
    )
    order_notional = forms.DecimalField(
        label="Объём ордера, ~USDT", initial=15, min_value=1,
        help_text="Целевой размер одного ордера; в базовую валюту пересчитается автоматически.",
    )
    grid_type = forms.ChoiceField(
        label="Тип сетки", choices=GridType.choices, initial=GridType.ARITHMETIC,
    )
    start = forms.BooleanField(
        label="Сразу запустить торговлю", required=False,
        help_text="Разместить сетку и запустить цикл (иначе стратегия останется «Готова»).",
    )
