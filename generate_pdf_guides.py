#!/usr/bin/env python3
"""
Генератор обновленных PDF инструкций для Cripto
Создает красивые профессиональные PDF с описанием нового интерфейса
"""

from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from datetime import datetime
import os

class CriptoPDFGenerator:
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self.width, self.height = A4
        self.setup_styles()

    def setup_styles(self):
        """Подготовить стили для документа"""
        # Заголовок документа
        self.styles.add(ParagraphStyle(
            name='DocTitle',
            parent=self.styles['Heading1'],
            fontSize=28,
            textColor=colors.HexColor('#1a1a1a'),
            spaceAfter=6,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        ))

        # Подзаголовок
        self.styles.add(ParagraphStyle(
            name='DocSubtitle',
            parent=self.styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#666666'),
            spaceAfter=12,
            alignment=TA_CENTER,
            fontName='Helvetica'
        ))

        # Основной заголовок раздела
        self.styles.add(ParagraphStyle(
            name='SectionTitle',
            parent=self.styles['Heading2'],
            fontSize=16,
            textColor=colors.HexColor('#0066cc'),
            spaceAfter=12,
            spaceBefore=12,
            fontName='Helvetica-Bold',
            borderPadding=10,
            borderColor=colors.HexColor('#0066cc'),
            borderWidth=1,
            borderRadius=3
        ))

        # Подзаголовок раздела
        self.styles.add(ParagraphStyle(
            name='SubsectionTitle',
            parent=self.styles['Heading3'],
            fontSize=12,
            textColor=colors.HexColor('#0066cc'),
            spaceAfter=6,
            spaceBefore=6,
            fontName='Helvetica-Bold'
        ))

        # Обычный текст
        self.styles.add(ParagraphStyle(
            name='BodyText',
            parent=self.styles['BodyText'],
            fontSize=10,
            textColor=colors.HexColor('#333333'),
            spaceAfter=6,
            alignment=TA_JUSTIFY,
            fontName='Helvetica'
        ))

        # Выделенный текст
        self.styles.add(ParagraphStyle(
            name='Highlight',
            parent=self.styles['BodyText'],
            fontSize=10,
            textColor=colors.HexColor('#cc0000'),
            spaceAfter=6,
            fontName='Helvetica-Bold'
        ))

    def create_trades_instruction(self):
        """Создать инструкцию по таблице торгов"""
        doc = SimpleDocTemplate("docs/Инструкция_по_торговле_ОБНОВЛЕНО_Cripto.pdf", pagesize=A4)
        story = []

        # Титульная страница
        story.append(Spacer(1, 1*cm))
        story.append(Paragraph("📊 Инструкция по таблице торгов", self.styles['DocTitle']))
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph("Cripto Grid Trading Bot", self.styles['DocSubtitle']))
        story.append(Spacer(1, 0.2*cm))
        story.append(Paragraph(f"Версия 2.0 | {datetime.now().strftime('%d.%m.%Y')}", self.styles['DocSubtitle']))
        story.append(Spacer(1, 2*cm))

        # Содержание
        story.append(Paragraph("📑 Содержание", self.styles['SectionTitle']))
        story.append(Paragraph("1. Обзор таблицы торгов<br/>2. Структура колонок<br/>3. Автообновление<br/>4. Пагинация<br/>5. Фильтры и экспорт",
                              self.styles['BodyText']))
        story.append(Spacer(1, 1*cm))

        # Раздел 1
        story.append(Paragraph("1️⃣ Обзор таблицы торгов", self.styles['SectionTitle']))
        story.append(Paragraph(
            "Таблица торгов отображает все закрытые сделки по всем активным стратегиям. "
            "Данные обновляются автоматически каждые 5 секунд. "
            "Таблица позволяет мониторить профитность, просматривать детали сделок и экспортировать результаты.",
            self.styles['BodyText']
        ))
        story.append(Spacer(1, 0.3*cm))

        # Раздел 2 - Структура колонок
        story.append(Paragraph("2️⃣ Структура колонок", self.styles['SectionTitle']))

        cols_data = [
            ['Колонка', 'Описание'],
            ['🕐 Время', 'Время закрытия сделки (UTC)'],
            ['📝 Название', 'Название стратегии (Grid, Scalping, DCA и т.д.)'],
            ['💰 Сумма', 'Вложено средств в позицию'],
            ['📈 Цена вход/выход', 'Цена входа и выхода из позиции'],
            ['💵 Профит USD', 'Прибыль/убыток в долларах'],
            ['📊 Профит %', 'Прибыль/убыток в процентах от вложения'],
            ['⏱️ Длительность', 'Время удержания позиции'],
            ['🎯 Статус', 'Закрыто (успешно завершено)'],
        ]

        table = Table(cols_data, colWidths=[2*cm, 4.5*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0066cc')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f5f5f5')),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
        ]))
        story.append(table)
        story.append(Spacer(1, 0.5*cm))

        # Раздел 3 - Автообновление
        story.append(PageBreak())
        story.append(Paragraph("3️⃣ Автообновление данных", self.styles['SectionTitle']))
        story.append(Paragraph(
            "<b>Интервал обновления:</b> Используйте выпадающее меню 'Обновление' для выбора интервала автоматического обновления таблицы.",
            self.styles['BodyText']
        ))
        story.append(Spacer(1, 0.2*cm))

        refresh_data = [
            ['Интервал', 'Описание', 'Рекомендация'],
            ['1 сек', 'Максимально часто, высокая нагрузка', 'Для активного мониторинга'],
            ['5 сек', 'Оптимально для большинства', '✅ По умолчанию'],
            ['10 сек', 'Экономит трафик и ресурсы', 'Для слабого интернета'],
            ['30 сек', 'Редкое обновление', 'Для фонового мониторинга'],
            ['Отключено', 'Ручное обновление по F5', 'Для экономии трафика'],
        ]

        table = Table(refresh_data, colWidths=[1.5*cm, 3.5*cm, 3*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#28a745')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f0f7f0')),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
        ]))
        story.append(table)
        story.append(Spacer(1, 0.3*cm))

        # Раздел 4 - Пагинация
        story.append(Paragraph("4️⃣ Пагинация (записей на странице)", self.styles['SectionTitle']))
        story.append(Paragraph(
            "<b>Размер страницы:</b> Используйте меню 'На странице' для выбора количества отображаемых сделок на одной странице. "
            "Увеличение размера может замедлить загрузку больших таблиц.",
            self.styles['BodyText']
        ))
        story.append(Spacer(1, 0.2*cm))

        page_data = [
            ['Размер', 'Количество сделок', 'Рекомендация'],
            ['10', '10 записей', 'Для медленного интернета'],
            ['20', '20 записей', '✅ По умолчанию'],
            ['50', '50 записей', 'Для быстрого интернета'],
            ['100', '100 записей', 'Для просмотра большого объема'],
            ['Все', 'Все доступные', 'Требует много оперативной памяти'],
        ]

        table = Table(page_data, colWidths=[1.5*cm, 3*cm, 3.5*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ffc107')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#fffbf0')),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
        ]))
        story.append(table)
        story.append(Spacer(1, 0.5*cm))

        # Раздел 5 - Фильтры и экспорт
        story.append(PageBreak())
        story.append(Paragraph("5️⃣ Фильтры и экспорт", self.styles['SectionTitle']))

        story.append(Paragraph("<b>📋 Фильтры:</b>", self.styles['SubsectionTitle']))
        story.append(Paragraph(
            "• <b>По стратегии:</b> Выберите конкретную стратегию для просмотра только её сделок<br/>"
            "• <b>По типу:</b> Фильтруйте по типу торговли (Grid, Scalping и т.д.)<br/>"
            "• <b>По дате:</b> Выберите дату или диапазон дат<br/>"
            "• <b>По режиму:</b> Demo или Live торговля",
            self.styles['BodyText']
        ))
        story.append(Spacer(1, 0.3*cm))

        story.append(Paragraph("<b>📊 Экспорт в Excel:</b>", self.styles['SubsectionTitle']))
        story.append(Paragraph(
            "Нажмите кнопку 'Экспорт в Excel' для скачивания всех видимых сделок в формате .xlsx. "
            "Файл будет содержать все колонки и применённые фильтры.",
            self.styles['BodyText']
        ))
        story.append(Spacer(1, 0.5*cm))

        # Советы
        story.append(Paragraph("💡 Полезные советы", self.styles['SectionTitle']))
        story.append(Paragraph(
            "• Установите интервал 5-10 сек для оптимального баланса свежести данных и нагрузки<br/>"
            "• Используйте размер 20-50 записей для быстрой загрузки на мобильных устройствах<br/>"
            "• Экспортируйте сделки в конце дня для анализа и бухгалтерии<br/>"
            "• Фильтруйте по стратегиям для сравнения их эффективности",
            self.styles['BodyText']
        ))

        # Подвал
        story.append(Spacer(1, 1*cm))
        story.append(Paragraph(
            f"<i>Документ создан: {datetime.now().strftime('%d.%m.%Y %H:%M')}<br/>Cripto Grid Trading Bot v2.0</i>",
            self.styles['BodyText']
        ))

        doc.build(story)
        print("✅ Создана инструкция: Инструкция_по_торговле_ОБНОВЛЕНО_Cripto.pdf")

    def create_admin_guide(self):
        """Создать руководство по админ-панели"""
        doc = SimpleDocTemplate("docs/Руководство_админ_панели_ОБНОВЛЕНО_Cripto.pdf", pagesize=A4)
        story = []

        story.append(Spacer(1, 1*cm))
        story.append(Paragraph("⚙️ Руководство админ-панели", self.styles['DocTitle']))
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph("Управление стратегиями и мониторинг воркера", self.styles['DocSubtitle']))
        story.append(Spacer(1, 0.2*cm))
        story.append(Paragraph(f"Версия 2.0 | {datetime.now().strftime('%d.%m.%Y')}", self.styles['DocSubtitle']))
        story.append(Spacer(1, 2*cm))

        # Раздел 1 - Статус воркера
        story.append(Paragraph("1️⃣ Мониторинг статуса воркера", self.styles['SectionTitle']))
        story.append(Paragraph(
            "В админ-панели добавлен новый раздел 'Статус воркера' для отслеживания работы торгового бота.",
            self.styles['BodyText']
        ))
        story.append(Spacer(1, 0.2*cm))

        worker_data = [
            ['Показатель', 'Описание'],
            ['✓ Статус', 'Зелёная галочка = воркер запущен и работает'],
            ['⏱️ Последнее обновление', 'Времени прошло с последнего сигнала (сек)'],
            ['🔄 Циклов', 'Количество завершённых торговых циклов'],
            ['📦 Ордеров', 'Всего обработано ордеров'],
            ['⚠️ Ошибки', 'Последняя ошибка (если была)'],
        ]

        table = Table(worker_data, colWidths=[3*cm, 4.5*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#17a2b8')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f0f7fa')),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
        ]))
        story.append(table)
        story.append(Spacer(1, 0.5*cm))

        # Раздел 2 - Управление стратегиями
        story.append(Paragraph("2️⃣ Управление стратегиями", self.styles['SectionTitle']))
        story.append(Paragraph(
            "<b>В админ-панели можно:</b><br/>"
            "• <b>Создавать</b> новые стратегии (Grid, Scalping, DCA, Trend, Arbitrage)<br/>"
            "• <b>Редактировать</b> параметры существующих стратегий<br/>"
            "• <b>Запускать/останавливать</b> торговлю по каждой стратегии<br/>"
            "• <b>Переключаться</b> между Demo и Live режимом<br/>"
            "• <b>Устанавливать</b> Stop-loss и risk management",
            self.styles['BodyText']
        ))
        story.append(Spacer(1, 0.5*cm))

        # Раздел 3 - Параметры стратегии
        story.append(Paragraph("3️⃣ Ключевые параметры стратегии", self.styles['SectionTitle']))

        params_data = [
            ['Параметр', 'Тип', 'Описание'],
            ['Название', 'Текст', 'Произвольное имя стратегии'],
            ['Пара', 'Выбор', 'BTC/USDT, ETH/USDT и т.д.'],
            ['Режим', 'Demo/Live', 'Тестовая или реальная торговля'],
            ['Начальный баланс', 'Число', 'Сумма для начала торговли (USDT)'],
            ['Количество уровней', 'Число', 'Для Grid: число сеток'],
            ['Верхняя цена', 'Число', 'Максимальная цена диапазона'],
            ['Нижняя цена', 'Число', 'Минимальная цена диапазона'],
            ['Stop Loss %', 'Число', 'Процент убытка для закрытия'],
        ]

        table = Table(params_data, colWidths=[2*cm, 1.5*cm, 3.5*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#dc3545')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#faf5f5')),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
        ]))
        story.append(table)
        story.append(Spacer(1, 0.5*cm))

        # Раздел 4 - Состояние стратегии
        story.append(PageBreak())
        story.append(Paragraph("4️⃣ Состояния стратегии", self.styles['SectionTitle']))

        states_data = [
            ['Состояние', 'Описание', 'Действие'],
            ['🟢 Активна', 'Торговля идёт', 'Остановить'],
            ['🔴 Остановлена', 'Ждёт команды', 'Запустить'],
            ['📦 Архив', 'История, не торгует', 'Восстановить'],
            ['⚠️ Ошибка', 'Произошла ошибка', 'Проверить логи'],
        ]

        table = Table(states_data, colWidths=[2*cm, 3*cm, 3*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6f42c1')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f5f0fa')),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
        ]))
        story.append(table)
        story.append(Spacer(1, 0.5*cm))

        # Раздел 5 - Аналитика
        story.append(Paragraph("5️⃣ Просмотр аналитики", self.styles['SectionTitle']))
        story.append(Paragraph(
            "<b>Информация по каждой стратегии:</b><br/>"
            "• Общий профит/убыток в USD и %<br/>"
            "• Плечо и маржа (для маржинальной торговли)<br/>"
            "• Количество открытых ордеров<br/>"
            "• Информация о рисках<br/>"
            "• Логи ошибок и событий",
            self.styles['BodyText']
        ))
        story.append(Spacer(1, 0.3*cm))

        story.append(Paragraph(
            "Нажмите на название стратегии для просмотра подробной информации и всех связанных ордеров.",
            self.styles['BodyText']
        ))
        story.append(Spacer(1, 0.5*cm))

        # Раздел 6 - Безопасность
        story.append(Paragraph("6️⃣ Безопасность администратора", self.styles['SectionTitle']))
        story.append(Paragraph(
            "<b>🔒 Требования:</b><br/>"
            "• Доступ в админ-панель только для администраторов<br/>"
            "• Используйте надёжный пароль (минимум 15 символов)<br/>"
            "• Двухфакторная аутентификация рекомендуется<br/>"
            "• Все действия логируются и могут быть проверены",
            self.styles['BodyText']
        ))

        # Подвал
        story.append(Spacer(1, 1*cm))
        story.append(Paragraph(
            f"<i>Документ создан: {datetime.now().strftime('%d.%m.%Y %H:%M')}<br/>Cripto Grid Trading Bot v2.0</i>",
            self.styles['BodyText']
        ))

        doc.build(story)
        print("✅ Создана инструкция: Руководство_админ_панели_ОБНОВЛЕНО_Cripto.pdf")

    def create_update_guide(self):
        """Создать руководство по обновлению"""
        doc = SimpleDocTemplate("docs/Руководство_обновление_ОБНОВЛЕНО_Cripto.pdf", pagesize=A4)
        story = []

        story.append(Spacer(1, 1*cm))
        story.append(Paragraph("🚀 Руководство по обновлению приложения", self.styles['DocTitle']))
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph("Для приложений на сервере с автоматическим обновлением", self.styles['DocSubtitle']))
        story.append(Spacer(1, 0.2*cm))
        story.append(Paragraph(f"Версия 2.0 | {datetime.now().strftime('%d.%m.%Y')}", self.styles['DocSubtitle']))
        story.append(Spacer(1, 2*cm))

        # Содержание
        story.append(Paragraph("📑 Содержание", self.styles['SectionTitle']))
        story.append(Paragraph(
            "1. Быстрый старт<br/>"
            "2. Способ 1: Ручное обновление<br/>"
            "3. Способ 2: Автоматическое обновление (CI/CD)<br/>"
            "4. Откат изменений<br/>"
            "5. Устранение проблем",
            self.styles['BodyText']
        ))
        story.append(Spacer(1, 1*cm))

        # Раздел 1
        story.append(Paragraph("1️⃣ Быстрый старт", self.styles['SectionTitle']))
        story.append(Paragraph(
            "<b>Минимум действий для обновления:</b>",
            self.styles['BodyText']
        ))
        story.append(Paragraph(
            "ssh user@server.com<br/>"
            "cd /app<br/>"
            "./update.sh",
            self.styles['Highlight']
        ))
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph(
            "<b>Время выполнения:</b> 2-3 минуты<br/>"
            "<b>Что делает скрипт:</b> автоматически делает резервную копию БД, получает код, "
            "применяет миграции, перезагружает сервисы и проверяет здоровье приложения.",
            self.styles['BodyText']
        ))
        story.append(Spacer(1, 0.5*cm))

        # Раздел 2
        story.append(Paragraph("2️⃣ Способ 1: Ручное обновление (рекомендуется)", self.styles['SectionTitle']))

        story.append(Paragraph("<b>Шаг 1: Подключиться к серверу</b>", self.styles['SubsectionTitle']))
        story.append(Paragraph("ssh user@ваш-ip-адрес", self.styles['Highlight']))
        story.append(Spacer(1, 0.2*cm))

        story.append(Paragraph("<b>Шаг 2: Перейти в папку приложения</b>", self.styles['SubsectionTitle']))
        story.append(Paragraph("cd /app", self.styles['Highlight']))
        story.append(Spacer(1, 0.2*cm))

        story.append(Paragraph("<b>Шаг 3: Запустить скрипт обновления</b>", self.styles['SubsectionTitle']))
        story.append(Paragraph("./update.sh", self.styles['Highlight']))
        story.append(Spacer(1, 0.2*cm))

        story.append(Paragraph(
            "<b>✅ Результат:</b><br/>"
            "• Создана резервная копия БД (в папке backups/)<br/>"
            "• Получен свежий код из GitHub<br/>"
            "• Применены новые миграции<br/>"
            "• Перезагружены веб и воркер сервисы<br/>"
            "• Проверено здоровье приложения",
            self.styles['BodyText']
        ))
        story.append(Spacer(1, 0.5*cm))

        # Раздел 3
        story.append(PageBreak())
        story.append(Paragraph("3️⃣ Способ 2: Автоматическое обновление (GitHub Actions)", self.styles['SectionTitle']))

        story.append(Paragraph(
            "<b>Как работает:</b> Каждый раз когда вы делаете 'git push' в main ветку, "
            "GitHub Actions автоматически обновляет приложение на сервере.",
            self.styles['BodyText']
        ))
        story.append(Spacer(1, 0.3*cm))

        story.append(Paragraph("<b>🔧 Одноразовая настройка (15 минут):</b>", self.styles['SubsectionTitle']))

        story.append(Paragraph("<b>1. На сервере: сгенерировать SSH ключ</b>", self.styles['SubsectionTitle']))
        story.append(Paragraph(
            "ssh-keygen -t ed25519 -f ~/.ssh/deploy_key -N \"\"<br/>"
            "cat ~/.ssh/deploy_key  # Скопировать полный текст",
            self.styles['Highlight']
        ))
        story.append(Spacer(1, 0.2*cm))

        story.append(Paragraph("<b>2. На GitHub: добавить secrets</b>", self.styles['SubsectionTitle']))
        story.append(Paragraph(
            "Settings → Secrets and variables → Actions<br/>"
            "Добавить 4 переменные:",
            self.styles['BodyText']
        ))

        secrets_data = [
            ['Имя', 'Значение'],
            ['SERVER_HOST', 'Ваш IP адрес сервера (например: 91.210.191.80)'],
            ['SERVER_USER', 'Пользователь на сервере (например: deploy)'],
            ['SERVER_PORT', 'SSH порт (обычно 22)'],
            ['SERVER_SSH_KEY', 'Приватный ключ из ~/.ssh/deploy_key'],
        ]

        table = Table(secrets_data, colWidths=[2.5*cm, 4.5*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e83e8c')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#faf5fa')),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
        ]))
        story.append(table)
        story.append(Spacer(1, 0.3*cm))

        story.append(Paragraph(
            "<b>3. Готово!</b> Теперь каждый 'git push origin main' обновляет сервер автоматически.",
            self.styles['BodyText']
        ))
        story.append(Spacer(1, 0.5*cm))

        # Раздел 4 - Откат
        story.append(Paragraph("4️⃣ Откат изменений (если что-то сломалось)", self.styles['SectionTitle']))

        story.append(Paragraph("<b>Вариант 1: Восстановить БД из резервной копии</b>", self.styles['SubsectionTitle']))
        story.append(Paragraph(
            "# Посмотреть доступные бэкапы<br/>"
            "ls -lh backups/<br/>"
            "<br/>"
            "# Восстановить конкретный бэкап<br/>"
            "gunzip &lt; backups/cripto_20260721_120000.sql.gz | psql -U cripto -d cripto_prod",
            self.styles['Highlight']
        ))
        story.append(Spacer(1, 0.3*cm))

        story.append(Paragraph("<b>Вариант 2: Вернуть код на предыдущий коммит</b>", self.styles['SubsectionTitle']))
        story.append(Paragraph(
            "git log --oneline  # Найти commit хеш<br/>"
            "git reset --hard &lt;commit-hash&gt;<br/>"
            "./update.sh",
            self.styles['Highlight']
        ))
        story.append(Spacer(1, 0.5*cm))

        # Раздел 5
        story.append(PageBreak())
        story.append(Paragraph("5️⃣ Устранение проблем", self.styles['SectionTitle']))

        problems = [
            ("Скрипт не найден", "chmod +x update.sh  # Сделать скрипт исполняемым"),
            ("Ошибка миграции БД", "ssh на сервер → проверить логи → ./update.sh ещё раз"),
            ("Сервис не запустился", "systemctl status cripto-web  # Проверить ошибку"),
            ("GitHub Actions не работает", "Проверить secrets, SSH доступ, права пользователя"),
        ]

        story.append(Paragraph("<b>Частые проблемы:</b>", self.styles['SubsectionTitle']))
        for problem, solution in problems:
            story.append(Paragraph(f"<b>⚠️ {problem}</b><br/>→ {solution}", self.styles['BodyText']))
            story.append(Spacer(1, 0.2*cm))

        # Подвал
        story.append(Spacer(1, 1*cm))
        story.append(Paragraph(
            f"<i>Документ создан: {datetime.now().strftime('%d.%m.%Y %H:%M')}<br/>Cripto Grid Trading Bot v2.0</i>",
            self.styles['BodyText']
        ))

        doc.build(story)
        print("✅ Создана инструкция: Руководство_обновление_ОБНОВЛЕНО_Cripto.pdf")

    def generate_all(self):
        """Создать все PDF файлы"""
        print("📄 Создание обновленных PDF инструкций...\n")
        self.create_trades_instruction()
        self.create_admin_guide()
        self.create_update_guide()
        print("\n✅ Все PDF файлы успешно созданы в папке docs/")
        print("📁 Новые файлы:")
        print("  • Инструкция_по_торговле_ОБНОВЛЕНО_Cripto.pdf")
        print("  • Руководство_админ_панели_ОБНОВЛЕНО_Cripto.pdf")
        print("  • Руководство_обновление_ОБНОВЛЕНО_Cripto.pdf")

if __name__ == "__main__":
    generator = CriptoPDFGenerator()
    generator.generate_all()
