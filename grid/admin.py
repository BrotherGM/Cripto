"""Админка для управления сеточными стратегиями.

Действия на странице стратегий выполняют шаги из документа:
    * проверка подключения к OKX
    * синхронизация параметров инструмента (tickSz/lotSz/minSz)
    * расчёт уровней сетки
    * размещение начальной сетки
    * штатная остановка (отмена всех ордеров)
"""
from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import path
from django.utils.html import format_html

import json
import os
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.http import FileResponse, Http404

from grid.forms import QuickStrategyForm
from grid.models import (
    GridStrategy, GridLevel, GridOrder, Trade, Position, StrategyLog, Instrument,
    Document, GridType, StrategyType,
)
from grid.services import okx_client as okx
from grid.services import runner
from grid.services.builder import (
    create_strategy_for_pair, create_typed_strategy, DEFAULT_PARAMS,
)
from grid.services.grid_engine import GridEngine
from grid.services.instruments import refresh_instruments


# --- инлайны -----------------------------------------------------------------
class GridLevelInline(admin.TabularInline):
    model = GridLevel
    extra = 0
    fields = ("index", "price", "side", "status", "active_order")
    readonly_fields = ("index", "price", "side", "status", "active_order")
    ordering = ("index",)
    can_delete = False
    show_change_link = True


class PositionInline(admin.StackedInline):
    model = Position
    extra = 0
    readonly_fields = ("base_qty", "avg_price", "realized_pnl", "updated_at")
    can_delete = False


class StrategyLogInline(admin.TabularInline):
    model = StrategyLog
    extra = 0
    fields = ("created_at", "level", "message")
    readonly_fields = ("created_at", "level", "message")
    ordering = ("-created_at",)
    can_delete = False
    max_num = 0  # только просмотр (добавление через инлайн запрещено)


@admin.register(GridStrategy)
class GridStrategyAdmin(admin.ModelAdmin):
    change_list_template = "admin/grid/gridstrategy/change_list.html"
    list_display = (
        "name", "type_badge", "inst_id", "status_badge", "runner_badge",
        "order_size", "open_chart",
    )
    list_filter = ("strategy_type", "status", "is_demo", "inst_type")
    search_fields = ("name", "inst_id")
    inlines = [PositionInline, GridLevelInline, StrategyLogInline]
    readonly_fields = (
        "trading_controls", "params_help",
        "tick_sz", "lot_sz", "min_sz", "is_demo",
        "runner_pid", "runner_started_at", "created_at", "updated_at",
    )
    fieldsets = (
        ("Основное", {
            "fields": ("name", "strategy_type", "inst_id", "inst_type", "td_mode",
                       "status", "trading_controls"),
        }),
        ("Параметры стратегии (DCA / Trend / Scalping / Arbitrage)", {
            "fields": ("params", "params_help"),
            "description": "JSON-параметры для не-сеточных типов. Схему см. ниже.",
        }),
        ("Диапазон сетки (только для типа «Сетка»)", {
            "fields": ("p_max", "p_min", "levels", "grid_type", "order_size"),
            "classes": ("collapse",),
        }),
        ("Параметры инструмента (с биржи)", {
            "fields": ("tick_sz", "lot_sz", "min_sz", "is_demo"),
        }),
        ("Стоп-лосс (сетка)", {"fields": ("stop_loss_enabled", "stop_loss_price"),
                               "classes": ("collapse",)}),
        ("Рабочий цикл", {"fields": ("runner_pid", "runner_started_at")}),
        ("Служебное", {"fields": ("created_at", "updated_at")}),
    )
    actions = (
        "action_start_trading", "action_stop_trading", "action_check_connection",
        "action_sync_instrument", "action_build_levels",
    )

    @admin.display(description="Статус")
    def status_badge(self, obj):
        colors = {
            "draft": "#888", "ready": "#0a7", "running": "#0a0",
            "stopped": "#c80", "emergency": "#c00",
        }
        return format_html(
            '<b style="color:{}">{}</b>', colors.get(obj.status, "#000"),
            obj.get_status_display(),
        )

    @admin.display(description="Цикл")
    def runner_badge(self, obj):
        if runner.is_running(obj):
            return format_html('<b style="color:#0a0">● работает</b>')
        return format_html('<span style="color:#999">○ остановлен</span>')

    @admin.display(description="Тип")
    def type_badge(self, obj):
        colors = {"grid": "#2471a3", "dca": "#117a3d", "trend": "#8e44ad",
                  "arbitrage": "#b9770e", "scalping": "#a93226"}
        return format_html('<b style="color:{}">{}</b>',
                           colors.get(obj.strategy_type, "#000"),
                           obj.get_strategy_type_display())

    @admin.display(description="Графики")
    def open_chart(self, obj):
        return format_html('<a href="/dashboard/{}/" target="_blank">📈 открыть</a>', obj.id)

    # Схемы параметров (params) по типам стратегий — подсказка в форме
    PARAM_SCHEMAS = {
        "dca": ('{"mode":"dip", "base_amount":100, "safety_amount":50, '
                '"price_deviation_pct":2, "safety_count":5, "volume_scale":1.5, '
                '"take_profit_pct":3}  ·  для расписания: {"mode":"schedule", '
                '"base_amount":50, "interval_hours":24, "take_profit_pct":3}'),
        "trend": ('{"bar":"1H", "fast":9, "slow":21, "order_amount":100, '
                  '"use_rsi":true, "rsi_period":14, "rsi_overbought":70}'),
        "scalping": '{"order_amount":50, "target_pct":0.3, "stop_pct":0.5}',
        "arbitrage": ('{"base":"USDT", "mid":"BTC", "cross":"ETH", "amount":50, '
                      '"min_profit_pct":0.3, "fee_pct":0.1, "execute":false}'),
        "grid": "Сетка использует отдельные поля ниже (Pmax/Pmin/уровни/объём), params не нужен.",
    }

    @admin.display(description="Схема параметров")
    def params_help(self, obj):
        schema = self.PARAM_SCHEMAS.get(getattr(obj, "strategy_type", "grid"), "")
        return format_html(
            '<div style="font-size:12px; color:#555">Пример params для типа '
            '<b>{}</b>:<br><code style="display:block; background:#f4f5f7; '
            'padding:8px; border-radius:6px; margin-top:4px; white-space:pre-wrap">{}</code>'
            '</div>',
            obj.get_strategy_type_display() if obj and obj.pk else "—", schema,
        )

    @admin.display(description="Управление торговлей")
    def trading_controls(self, obj):
        """Кнопки запуска/остановки торговли и ссылка на графики.

        Кнопки — submit'ы той же формы; их обрабатывает response_change().
        """
        if not obj or not obj.pk:
            return "Сохраните стратегию, чтобы управлять торговлей."
        return format_html(
            '<div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">'
            '<input type="submit" name="_start_trading" value="▶️ Запустить торговлю" '
            'style="background:#1f7a3d; color:#fff; padding:6px 12px; border:0; '
            'border-radius:6px; cursor:pointer;">'
            '<input type="submit" name="_stop_trading" value="⏹ Остановить торговлю" '
            'style="background:#a33; color:#fff; padding:6px 12px; border:0; '
            'border-radius:6px; cursor:pointer;">'
            '<a class="button" href="/dashboard/{}/" target="_blank" '
            'style="background:#264b7a; color:#fff;">📈 Открыть графики</a>'
            '</div>',
            obj.pk,
        )

    # --- кнопки запуска/остановки на странице объекта ------------------------
    def response_change(self, request, obj):
        if "_start_trading" in request.POST:
            self._do(request, obj, runner.start_trading)
            return HttpResponseRedirect(request.path)
        if "_stop_trading" in request.POST:
            self._do(request, obj, runner.stop_trading)
            return HttpResponseRedirect(request.path)
        return super().response_change(request, obj)

    def _do(self, request, obj, fn):
        try:
            res = fn(obj)
            self.message_user(
                request, res["msg"],
                messages.SUCCESS if res.get("ok") else messages.WARNING,
            )
        except Exception as e:  # noqa: BLE001
            self.message_user(request, f"Ошибка: {e}", messages.ERROR)

    # --- быстрое создание стратегии по паре ----------------------------------
    def get_urls(self):
        custom = [
            path("quick-create/", self.admin_site.admin_view(self.quick_create_view),
                 name="grid_gridstrategy_quick_create"),
        ]
        return custom + super().get_urls()

    def quick_create_view(self, request):
        """Мастер: выбираешь тип и пары -> стратегии создаются с авто-заполнением."""
        if request.method == "POST":
            form = QuickStrategyForm(request.POST)
            if form.is_valid():
                cd = form.cleaned_data
                stype = cd["strategy_type"]
                raw = cd["pairs"].replace(",", "\n").splitlines()
                pairs = [p.strip() for p in raw if p.strip()]
                created = 0
                for pair in pairs:
                    try:
                        if stype == StrategyType.GRID:
                            res = create_strategy_for_pair(
                                pair, range_pct=cd.get("range_pct") or 10,
                                levels=cd.get("levels") or 10,
                                order_notional=cd.get("order_notional") or 15,
                                grid_type=cd.get("grid_type") or GridType.ARITHMETIC,
                            )
                        else:
                            res = create_typed_strategy(pair, stype, cd.get("params") or {})
                    except Exception as e:  # noqa: BLE001
                        self.message_user(request, f"{pair}: ошибка — {e}", messages.ERROR)
                        continue
                    self.message_user(
                        request, res["msg"],
                        messages.SUCCESS if res["ok"] else messages.WARNING,
                    )
                    if res["ok"]:
                        created += 1
                        if cd.get("start"):
                            self._do(request, res["strategy"], runner.start_trading)
                if created:
                    return redirect("admin:grid_gridstrategy_changelist")
        else:
            form = QuickStrategyForm()

        instruments = list(
            Instrument.objects.filter(active=True)
            .order_by("inst_id").values_list("inst_id", flat=True)
        )
        ctx = {
            **self.admin_site.each_context(request),
            "title": "Мастер создания стратегии",
            "opts": self.model._meta,
            "form": form,
            # дефолтные params по типам — для авто-заполнения в форме (JS)
            "defaults_json": json.dumps(
                {str(k): v for k, v in DEFAULT_PARAMS.items()}, ensure_ascii=False),
            # справочник пар для выбора (кнопка «Обновить пары с биржи» в разделе Инструменты)
            "instruments": instruments,
        }
        return render(request, "admin/grid/quick_create.html", ctx)

    # --- массовые действия запуска/остановки --------------------------------
    @admin.action(description="▶️ Запустить торговлю")
    def action_start_trading(self, request, queryset):
        for s in queryset:
            self._do(request, s, runner.start_trading)

    @admin.action(description="⏹ Остановить торговлю")
    def action_stop_trading(self, request, queryset):
        for s in queryset:
            self._do(request, s, runner.stop_trading)

    # --- вспомогательные действия --------------------------------------------
    @admin.action(description="🔌 Проверить подключение к OKX")
    def action_check_connection(self, request, queryset):
        try:
            info = okx.check_connection()
            self.message_user(
                request,
                f"OKX на связи. Демо: {info['demo']}, время сервера: {info['server_time_ms']}.",
                messages.SUCCESS,
            )
        except Exception as e:  # noqa: BLE001
            self.message_user(request, f"OKX недоступен: {e}", messages.ERROR)

    @admin.action(description="📐 Синхронизировать параметры инструмента")
    def action_sync_instrument(self, request, queryset):
        for s in queryset:
            try:
                GridEngine(s).sync_instrument()
                self.message_user(
                    request,
                    f"[{s.name}] tickSz={s.tick_sz}, lotSz={s.lot_sz}, minSz={s.min_sz}",
                    messages.SUCCESS,
                )
            except Exception as e:  # noqa: BLE001
                self.message_user(request, f"[{s.name}] ошибка: {e}", messages.ERROR)

    @admin.action(description="🧮 Рассчитать уровни сетки (только тип «Сетка»)")
    def action_build_levels(self, request, queryset):
        for s in queryset:
            if s.strategy_type != "grid":
                self.message_user(
                    request, f"[{s.name}] расчёт уровней только для сеток — пропущено.",
                    messages.WARNING)
                continue
            try:
                n = GridEngine(s).build_levels()
                self.message_user(request, f"[{s.name}] рассчитано уровней: {n}", messages.SUCCESS)
            except Exception as e:  # noqa: BLE001
                self.message_user(request, f"[{s.name}] ошибка: {e}", messages.ERROR)


@admin.register(GridLevel)
class GridLevelAdmin(admin.ModelAdmin):
    list_display = ("strategy", "index", "price", "side", "status", "active_order")
    list_filter = ("status", "side", "strategy")
    search_fields = ("strategy__name",)
    ordering = ("strategy", "index")


@admin.register(GridOrder)
class GridOrderAdmin(admin.ModelAdmin):
    list_display = (
        "strategy", "side", "price", "size", "state",
        "filled_size", "ord_id", "created_at",
    )
    list_filter = ("state", "side", "strategy")
    search_fields = ("ord_id", "cl_ord_id", "strategy__name")
    readonly_fields = ("raw", "created_at", "updated_at")
    date_hierarchy = "created_at"


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display = ("strategy", "side", "fill_price", "fill_size", "fee", "ts")
    list_filter = ("side", "strategy")
    search_fields = ("trade_id", "strategy__name")
    date_hierarchy = "ts"


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ("strategy", "base_qty", "avg_price", "realized_pnl", "updated_at")
    search_fields = ("strategy__name",)


@admin.register(StrategyLog)
class StrategyLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "strategy", "level", "message")
    list_filter = ("level", "strategy")
    search_fields = ("message", "strategy__name")
    date_hierarchy = "created_at"


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    """Справочник торговых пар с биржи + кнопка обновления."""
    change_list_template = "admin/grid/instrument/change_list.html"
    list_display = ("inst_id", "active", "base_ccy", "quote_ccy", "min_sz",
                    "tick_sz", "state", "updated_at")
    list_editable = ("active",)
    list_filter = ("active", "inst_type", "quote_ccy", "state")
    search_fields = ("inst_id", "base_ccy", "quote_ccy")
    ordering = ("inst_id",)
    list_per_page = 50
    actions = ("make_active", "make_inactive")

    @admin.action(description="✅ Сделать Active")
    def make_active(self, request, queryset):
        n = queryset.update(active=True)
        self.message_user(request, f"Активировано пар: {n}", messages.SUCCESS)

    @admin.action(description="🚫 Снять Active")
    def make_inactive(self, request, queryset):
        n = queryset.update(active=False)
        self.message_user(request, f"Деактивировано пар: {n}", messages.WARNING)

    def get_urls(self):
        custom = [
            path("refresh/", self.admin_site.admin_view(self.refresh_view),
                 name="grid_instrument_refresh"),
        ]
        return custom + super().get_urls()

    def refresh_view(self, request):
        """Кнопка «Обновить пары с биржи»: тянет инструменты с OKX."""
        try:
            res = refresh_instruments("SPOT")
            self.message_user(request, res["msg"], messages.SUCCESS)
        except Exception as e:  # noqa: BLE001
            self.message_user(request, f"Ошибка обновления: {e}", messages.ERROR)
        return redirect("admin:grid_instrument_changelist")


DOCS_DIR = settings.BASE_DIR / "docs"


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    """Пункт «Документы»: динамический список PDF из папки docs/."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return True

    def get_model_perms(self, request):
        # Пустые права -> модель НЕ показывается в группе Grid (это отдельный
        # пункт меню). URL страницы при этом остаётся рабочим.
        return {}

    def get_urls(self):
        return [
            path("", self.admin_site.admin_view(self.list_view),
                 name="grid_document_changelist"),
            path("open/<str:filename>/", self.admin_site.admin_view(self.serve_view),
                 name="grid_document_open"),
        ]

    def list_view(self, request):
        files = []
        if DOCS_DIR.exists():
            for f in sorted(DOCS_DIR.glob("*.pdf")):
                stt = f.stat()
                files.append({
                    "name": f.name,
                    "size_kb": round(stt.st_size / 1024),
                    "mtime": datetime.fromtimestamp(stt.st_mtime, tz=dt_timezone.utc),
                })
        ctx = {
            **self.admin_site.each_context(request),
            "title": "Документы",
            "opts": self.model._meta,
            "files": files,
            "docs_dir": str(DOCS_DIR),
        }
        return render(request, "admin/grid/documents.html", ctx)

    def serve_view(self, request, filename):
        # безопасность: только имя файла (без путей), только .pdf, только из docs/
        name = os.path.basename(filename)
        path_ = (DOCS_DIR / name).resolve()
        if (not name.lower().endswith(".pdf") or not path_.exists()
                or DOCS_DIR.resolve() not in path_.parents):
            raise Http404("Документ не найден")
        as_attach = request.GET.get("download") == "1"
        return FileResponse(open(path_, "rb"), content_type="application/pdf",
                            as_attachment=as_attach, filename=name)


admin.site.site_header = "Cripto — Grid Trading"
admin.site.site_title = "Cripto Admin"
admin.site.index_title = "Управление сеточными стратегиями"
# Главная страница админки с дополнительным блоком «Графики торговли»
admin.site.index_template = "admin/custom_index.html"
