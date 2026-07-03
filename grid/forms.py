import json

from django import forms

from grid.models import GridType, StrategyType


class QuickStrategyForm(forms.Form):
    """Мастер быстрого создания стратегии любого типа.

    Для сетки — параметры считаются по рынку (диапазон/объём); для остальных
    типов — JSON-параметры, предзаполняемые дефолтами под выбранный тип.
    """

    strategy_type = forms.ChoiceField(
        label="Тип стратегии", choices=StrategyType.choices, initial=StrategyType.GRID,
    )
    pairs = forms.CharField(
        label="Пары",
        widget=forms.Textarea(attrs={"rows": 3, "cols": 40,
                                     "placeholder": "BTC-USDT\nETH-USDT"}),
        help_text="По одной паре в строке (или через запятую), формат BASE-USDT.",
    )

    # --- параметры сетки (тип «grid») ---
    range_pct = forms.DecimalField(
        label="Сетка: диапазон ± %", initial=10, required=False, min_value=1, max_value=90)
    levels = forms.IntegerField(
        label="Сетка: число уровней N", initial=10, required=False, min_value=2, max_value=100)
    order_notional = forms.DecimalField(
        label="Сетка: объём ордера ~USDT", initial=15, required=False, min_value=1)
    grid_type = forms.ChoiceField(
        label="Сетка: тип", choices=GridType.choices, initial=GridType.ARITHMETIC, required=False)

    # --- параметры остальных типов ---
    params = forms.CharField(
        label="Параметры (JSON)", required=False,
        widget=forms.Textarea(attrs={"rows": 8, "cols": 50}),
        help_text="Заполняются автоматически по типу — можно отредактировать перед созданием.",
    )

    start = forms.BooleanField(
        label="Сразу запустить торговлю", required=False,
        help_text="Разместить ордера и поднять рабочий цикл (иначе стратегия останется «Готова»).",
    )

    def clean_params(self):
        raw = (self.cleaned_data.get("params") or "").strip()
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise forms.ValidationError(f"Невалидный JSON: {e}")
        if not isinstance(data, dict):
            raise forms.ValidationError("Параметры должны быть JSON-объектом {…}.")
        return data
