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
from django.utils.html import format_html

from grid.models import (
    GridStrategy, GridLevel, GridOrder, Trade, Position, StrategyLog,
)
from grid.services import okx_client as okx
from grid.services import runner
from grid.services.grid_engine import GridEngine


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
    list_display = (
        "name", "inst_id", "status_badge", "runner_badge", "grid_type", "levels",
        "p_min", "p_max", "order_size", "open_chart",
    )
    list_filter = ("status", "grid_type", "is_demo", "inst_type")
    search_fields = ("name", "inst_id")
    inlines = [PositionInline, GridLevelInline, StrategyLogInline]
    readonly_fields = (
        "trading_controls",
        "tick_sz", "lot_sz", "min_sz", "is_demo",
        "runner_pid", "runner_started_at", "created_at", "updated_at",
    )
    fieldsets = (
        ("Основное", {
            "fields": ("name", "inst_id", "inst_type", "td_mode", "status", "trading_controls"),
        }),
        ("Диапазон сетки (раздел 2.1)", {
            "fields": ("p_max", "p_min", "levels", "grid_type", "order_size"),
        }),
        ("Параметры инструмента (раздел 2.2, с биржи)", {
            "fields": ("tick_sz", "lot_sz", "min_sz", "is_demo"),
        }),
        ("Стоп-лосс (раздел 4.2)", {"fields": ("stop_loss_enabled", "stop_loss_price")}),
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

    @admin.display(description="Графики")
    def open_chart(self, obj):
        return format_html('<a href="/dashboard/{}/" target="_blank">📈 открыть</a>', obj.id)

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

    @admin.action(description="🧮 Рассчитать уровни сетки (без размещения)")
    def action_build_levels(self, request, queryset):
        for s in queryset:
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


admin.site.site_header = "Cripto — Grid Trading"
admin.site.site_title = "Cripto Admin"
admin.site.index_title = "Управление сеточными стратегиями"
# Главная страница админки с дополнительным блоком «Графики торговли»
admin.site.index_template = "admin/custom_index.html"
