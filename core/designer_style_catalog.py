#!/usr/bin/env python3
"""Canonical catalog of visual directions for Designer."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_STYLE_ID = "free-default"

PALETTE_MODE_CATALOG: Tuple[Dict[str, str], ...] = (
    {
        "id": "recommended",
        "label": "Рекомендуемая",
        "description": "Основная палитра, которая лучше всего выражает это визуальное семейство.",
    },
    {
        "id": "pastel",
        "label": "Пастельная",
        "description": "Мягкая, светлая и более дружелюбная версия семейства.",
    },
    {
        "id": "solid",
        "label": "Плотная",
        "description": "Цвет с большим визуальным весом и более прямым контрастом.",
    },
    {
        "id": "monochrome",
        "label": "Монохромная",
        "description": "Сдержанная шкала для продуктов, которым нужны фокус и дисциплина.",
    },
    {
        "id": "earth",
        "label": "Земляная",
        "description": "Органичная, тёплая и менее технологичная основа.",
    },
    {
        "id": "dopamine",
        "label": "Дофаминовая",
        "description": "Энергичная и очень заметная версия для мгновенного эффекта.",
    },
)


def _specimen_url(font_name: str) -> str:
    return f"https://fonts.google.com/specimen/{font_name.replace(' ', '+')}"


def _css_url(*families: str) -> str:
    family_query = "&".join(
        f"family={family.replace(' ', '+')}:wght@400;500;700" for family in families
    )
    return f"https://fonts.googleapis.com/css2?{family_query}&display=swap"


def _reference(label: str, url: str) -> Dict[str, str]:
    return {"label": label, "url": url}


def _font_pairing(
    pairing_id: str,
    label: str,
    headings: str,
    body: str,
    *,
    notes: str,
) -> Dict[str, str]:
    return {
        "id": pairing_id,
        "label": label,
        "headings": headings,
        "body": body,
        "notes": notes,
        "headings_specimen_url": _specimen_url(headings),
        "body_specimen_url": _specimen_url(body),
        "css_url": _css_url(headings, body),
        "source": "google-fonts",
    }


def _palette(
    surface: str,
    surface_alt: str,
    ink: str,
    muted: str,
    accent: str,
    accent_alt: str,
) -> Dict[str, str]:
    return {
        "surface": surface,
        "surface_alt": surface_alt,
        "ink": ink,
        "muted": muted,
        "accent": accent,
        "accent_alt": accent_alt,
    }


def _style_cues(
    *,
    visual_principles: List[str],
    layout_grammar: str,
    surface_treatment: str,
    shape_language: str,
    motion_language: str,
    signature_elements: List[str],
    implementation_guardrails: List[str],
    prompt_seed: str,
) -> Dict[str, Any]:
    return {
        "visual_principles": list(visual_principles),
        "layout_grammar": layout_grammar,
        "surface_treatment": surface_treatment,
        "shape_language": shape_language,
        "motion_language": motion_language,
        "signature_elements": list(signature_elements),
        "implementation_guardrails": list(implementation_guardrails),
        "prompt_seed": prompt_seed,
    }


STYLE_SYSTEM_CUES: Dict[str, Dict[str, Any]] = {
    "free-default": _style_cues(
        visual_principles=[
            "Намеренная нейтральность: айдентика рождается из продукта, а не из навязанного тренда.",
            "Ясная иерархия, чистые блоки и визуальный язык, который легко расширять.",
            "Выразительность появляется только там, где её оправдывает продукт.",
        ],
        layout_grammar="Упорядоченная сетка, стабильный ритм и модули, которые легко систематизировать.",
        surface_treatment="Светлые фоны, спокойный контраст и сдержанная глубина.",
        shape_language="Чистые прямоугольники, неброские капсулы и средние радиусы.",
        motion_language="Мягкие функциональные микровзаимодействия без лишнего визуального акцента.",
        signature_elements=["ясный hero", "доминирующий CTA", "читаемое социальное доказательство"],
        implementation_guardrails=[
            "Не навязывай трендовую эстетику, если продукт её пока не просит.",
            "Избегай лишнего орнамента и визуальных слоёв, которые усложняют базовую систему.",
        ],
        prompt_seed="Используй контекстное и выполнимое направление: сначала ясность, характер только там, где он помогает продукту.",
    ),
    "maximalism-neo-retro": _style_cues(
        visual_principles=[
            "Видимые слои, коллаж и журнальная энергия с контролируемым хаосом.",
            "Цвет и композиция должны ощущаться культурными, а не корпоративными.",
            "Интерфейс должен выглядеть сделанным с графическим вкусом, а не по шаблонам SaaS.",
        ],
        layout_grammar="Постер + стикер + наклонённый вторичный элемент, с ритмом коллажа и асимметричной иерархией.",
        surface_treatment="Насыщенные поля, тёплые градиенты и элементы, которые выглядят напечатанными или наклеенными.",
        shape_language="Скруглённые постеры, наклонённые билеты и очень заметные цветные полосы.",
        motion_language="Игривые сдвиги, наложения и короткие отскоки с журнальным характером.",
        signature_elements=["заметные стикеры", "наклонённый коллаж", "главная цветная полоса"],
        implementation_guardrails=[
            "Не превращай это в детский поп без редакционного вкуса.",
            "Не вычищай композицию настолько, что пропадут ретро-характер и графическое напряжение.",
        ],
        prompt_seed="Используй настоящий неоретро-максимализм: журнальный коллаж, насыщенный цвет и элементы с графическим напряжением; избегай корпоративной нейтральности.",
    ),
    "kinetic-typography": _style_cues(
        visual_principles=[
            "Типографика главная: заголовок это структура, а не декор.",
            "Контраст между масштабами должен ощущаться как перформанс.",
            "Композиция должна дышать ради текста, а не спорить с ним.",
        ],
        layout_grammar="Гигантские заголовки, типографское эхо, полосы чтения и вторичные рельсы как опора.",
        surface_treatment="Чистые поверхности, чтобы текст и полосы делали визуальную работу.",
        shape_language="Полосы, подчёркивания, рельсы и типографские массы на переднем плане.",
        motion_language="Типографские сдвиги, построчные reveals и эхо текста, а не декоративный blur.",
        signature_elements=["гигантский заголовок", "типографское эхо", "напряжённые полосы"],
        implementation_guardrails=[
            "Не прячь типографский характер за типовыми карточками.",
            "Не добавляй слишком много вторичных виджетов, которые отнимают внимание у текста.",
        ],
        prompt_seed="Используй настоящую кинетическую типографику: текст в главной роли, драматичные масштабы и визуальный ритм из слов и полос.",
    ),
    "interactive-3d-webgl": _style_cues(
        visual_principles=[
            "Сначала глубина и объект: продукт должен ощущаться пространственным.",
            "Главный элемент должен выглядеть объектом или сценой, а не плоской карточкой.",
            "Остальной layout сопровождает его как панель управления или исследования.",
        ],
        layout_grammar="Главная сцена + боковая панель или вспомогательные блоки, которые вращаются вокруг объекта.",
        surface_treatment="Холодные градиенты, мягкие блики и поля со сдержанной глубиной.",
        shape_language="Объёмные объекты, парящие плоскости и панели с техническим характером.",
        motion_language="Parallax, тонкое вращение и контролируемое пространственное смещение.",
        signature_elements=["3D-объект в hero", "сцена с глубиной", "вспомогательная боковая панель"],
        implementation_guardrails=[
            "Не превращай это в типовой glass без ощущения объекта.",
            "Не заполняй сцену орнаментом, если главный объект уже говорит сам.",
        ],
        prompt_seed="Используй настоящее интерактивное 3D: объект в главной роли, пространственная глубина и вспомогательные панели; избегай плоских карточек с гримом.",
    ),
    "glassmorphism-2": _style_cues(
        visual_principles=[
            "Зрелые полупрозрачные слои, а не декоративное стекло без иерархии.",
            "Глубина должна ощущаться лёгкой и технологичной.",
            "Blur нужен, чтобы разделять слои, а не размывать контент.",
        ],
        layout_grammar="Парящая главная панель + orb или вторичная панель, которая усиливает глубину и слои.",
        surface_treatment="Полупрозрачные панели, внутренние блики и контролируемый холодный свет.",
        shape_language="Мягкие капсулы, скруглённые панели и овальный orb как акцент глубины.",
        motion_language="Мягкие сдвиги, контролируемый blur и жидкий отклик, никогда не резкий.",
        signature_elements=["glass-панель в hero", "светящийся orb", "полупрозрачные chips"],
        implementation_guardrails=[
            "Не скатывайся в типовую серую тень с blur повсюду.",
            "Не теряй читаемость из-за избытка прозрачности или выцветшего света.",
        ],
        prompt_seed="Используй настоящий glassmorphism 2.0: полупрозрачные панели с элегантной глубиной, контролируемый свет и высокая читаемость.",
    ),
    "dopamine-colors": _style_cues(
        visual_principles=[
            "Мгновенный эмоциональный отклик через цвет и энергичный контраст.",
            "Композиция должна ощущаться быстрой, заметной и весёлой.",
            "Система должна оставаться продуктом, а не превращаться в бесполезный плакат.",
        ],
        layout_grammar="Цветовые массы, пузыри, strips и акцентные точки с прямым прочтением.",
        surface_treatment="Яркие поля, электрические градиенты и насыщенный свет с высоким контрастом.",
        shape_language="Скруглённые пузыри, pills, цветные strips и очень выраженные цветные точки.",
        motion_language="Пульсы, быстрые сдвиги и короткие реакции с высокой энергией.",
        signature_elements=["цветные пузыри", "электрический strip", "дофаминовые точки"],
        implementation_guardrails=[
            "Не переиспользуй ретро-композицию: это должно ощущаться более цифровым и мгновенным.",
            "Не снижай насыщенность настолько, что результат станет просто приятным.",
        ],
        prompt_seed="Используй настоящие дофаминовые цвета: мгновенная цветовая энергия, скруглённые цифровые формы и живые контрасты; избегай вялой SaaS-эстетики.",
    ),
    "nature-distilled": _style_cues(
        visual_principles=[
            "Органичное тепло и подлинность без наивной деревенщины.",
            "Интерфейс должен дышать и ощущаться тактильным, неспешным и продуманным.",
            "Мягкие кривые и текстуры должны доминировать над жёсткой сеткой.",
        ],
        layout_grammar="Главный органичный элемент + спокойный редакционный или статистический блок, с большим количеством воздуха между элементами.",
        surface_treatment="Кремовые поля, мягкие пятна и очень сдержанные органичные градиенты.",
        shape_language="Мягкие неровные кривые, тактильные карточки и спокойные капсулы.",
        motion_language="Мягкие органичные переходы с ощущением дыхания.",
        signature_elements=["органичное медиа", "земляной chip", "спокойные изогнутые блоки"],
        implementation_guardrails=[
            "Не превращай это в типовой бежевый wellness-бренд.",
            "Не делай сетку настолько жёсткой, что пропадёт органичное ощущение.",
        ],
        prompt_seed="Используй настоящий nature distilled: мягкие кривые, редакционное спокойствие и органичная тактильность; избегай жёстких сеток и холодного технологичного блеска.",
    ),
    "neo-brutalism": _style_cues(
        visual_principles=[
            "Жёсткие блоки, чёрные рамки и смещённые тени с полной фронтальностью.",
            "Композиции нужны контролируемое несовершенство и видимое напряжение.",
            "Никакого glass, blur и корпоративной мягкости: это должно ощущаться физическим.",
        ],
        layout_grammar="Смещённые коробки, стикеры, сухие top lines и смелая фронтальная иерархия.",
        surface_treatment="Кремовые или плотные фоны, матовые заливки и очень заметные чёрные контуры.",
        shape_language="Напряжённые прямоугольники, весомые капсулы и stat cards с брутальной тенью.",
        motion_language="Сухой отклик, короткий толчок и чёткое смещение без размытия.",
        signature_elements=["смещённая коробка", "жёсткий стикер", "CTA с брутальной тенью"],
        implementation_guardrails=[
            "Не скругляй лишнего и не смягчай тени до вида friendly SaaS.",
            "Не добавляй эфирный glow или прозрачность, которые спорят с брутальной материальностью.",
        ],
        prompt_seed="Используй настоящий необрутализм: чёрные рамки, жёсткие тени, смещённые блоки и ноль glass-мягкости.",
    ),
    "ai-hyperminimalism": _style_cues(
        visual_principles=[
            "Визуальная тишина, точность и элегантная технология без шума.",
            "Всё должно ощущаться намеренным, просторным и тонко настроенным.",
            "Изысканность рождается из сдержанности, а не из декора.",
        ],
        layout_grammar="Большие пустоты, одна или две главные массы и очень тонкие вспомогательные линии.",
        surface_treatment="Чистые белые или холодные серые, очень тонкие градиенты и почти невидимая глубина.",
        shape_language="Сдержанные карточки, тонкие полосы, мягкие блоки и минимум орнамента.",
        motion_language="Почти незаметные, очень отполированные микропереходы без шума.",
        signature_elements=["пустота в главной роли", "тонкая полоса", "чистая панель"],
        implementation_guardrails=[
            "Не добавляй лишние гаджеты, которые нарушают визуальную тишину.",
            "Не делай всё настолько пустым, что теряется важная информация или иерархия.",
        ],
        prompt_seed="Используй настоящий гиперминимализм: воздух, точность и тихая технология; избегай любого графического жеста, который перетягивает внимание.",
    ),
    "narrative-scroll-gamification": _style_cues(
        visual_principles=[
            "Страница читается как последовательность, а не как статичная доска.",
            "Прогресс, этапы и checkpoints должны быть видны внутри layout.",
            "Нарратив должен вести к действию, не теряя ясности продукта.",
        ],
        layout_grammar="Рельс прогресса + карточка этапа + checkpoints или микросостояния, распределённые по последовательности.",
        surface_treatment="Чистые плоскости с мягкими градиентами, которые подсказывают движение и направление.",
        shape_language="Рельсы, шаги, checkpoints, панели по фазам и последовательные top lines.",
        motion_language="Продвижение по этапам, цепочки reveals и отклик о прогрессе.",
        signature_elements=["рельс прогресса", "видимый checkpoint", "карточка этапа"],
        implementation_guardrails=[
            "Не ограничивайся плоскими карточками без ощущения последовательности.",
            "Не перегибай с геймификацией до игрушки, когда продукт требует доверия.",
        ],
        prompt_seed="Используй настоящий нарративный скролл: последовательность, рельсы, checkpoints и ритм по этапам; избегай статичного layout с тремя обычными коробками.",
    ),
}


def _with_style_cues(style: Dict[str, Any]) -> Dict[str, Any]:
    enriched = deepcopy(style)
    cues = STYLE_SYSTEM_CUES.get(enriched["id"], {})
    for key, value in cues.items():
        enriched[key] = deepcopy(value)
    return enriched


STYLE_CATALOG: Tuple[Dict[str, Any], ...] = (
    {
        "id": DEFAULT_STYLE_ID,
        "name": "Свободный / Контекстный",
        "summary": "Designer работает как раньше и выбирает направление от продукта, не привязывая проект к заранее выбранному тренду.",
        "description": "Режим без заранее заданной дизайн-системы. Подходит, когда лучший ответ рождается из PRD, пользователя и реального контекста продукта.",
        "when_to_use": "Подходит, когда тебе нужен визуальный вкус без навязывания конкретного течения с самого начала.",
        "anti_patterns": [
            "Не заставляет выглядеть трендовым брендом, если продукт просит другого.",
            "Не превращает визуальную фазу в голосование за moodboards без контекста.",
        ],
        "context_signals": [
            "Продукт со смешанными или пока плохо определёнными потребностями.",
            "Команда хочет, чтобы Designer начинал с задачи, а не с эстетики.",
        ],
        "references": [],
        "palette_modes": ["recommended", "pastel", "solid", "monochrome"],
        "recommended_palette_mode": "recommended",
        "palettes": {
            "recommended": _palette("#f4efe9", "#e8e0d7", "#181311", "#6f635c", "#2f6fed", "#12284c"),
            "pastel": _palette("#f6f2ec", "#eed8de", "#1d1715", "#796c66", "#d8a7c4", "#88b5ff"),
            "solid": _palette("#f1ece5", "#e1d4c7", "#171210", "#655852", "#1847c9", "#0f1d40"),
            "monochrome": _palette("#f2efeb", "#e4dfd8", "#141414", "#666666", "#4a4a4a", "#272727"),
        },
        "font_pairings": (
            _font_pairing(
                "contextual-sans",
                "Contextual Sans",
                "Space Grotesk",
                "Inter",
                notes="Нейтральная пара, чтобы систему задавал продукт, а не типографика.",
            ),
            _font_pairing(
                "contextual-editorial",
                "Contextual Editorial",
                "Fraunces",
                "DM Sans",
                notes="Когда продукт просит больше вкуса или более продуманный тон.",
            ),
        ),
        "suggested_density": "Сбалансированная, с фокусом на ясном чтении и понятной иерархии.",
        "suggested_tone": "Гибкий, современный и ведомый продуктом.",
        "suggested_component": "Ясный hero с ценностным предложением, социальным доказательством и главным CTA.",
    },
    {
        "id": "maximalism-neo-retro",
        "name": "Максимализм и неоретро",
        "summary": "Слои, текстуры, насыщенность и контролируемый хаос с журнальным и человечным характером.",
        "description": "Направление, богатое цветом, контрастом и графикой. Работает, когда бренд может позволить себе выразительный шум и мгновенный характер.",
        "when_to_use": "Подходит, когда продукту нужны яркий характер, визуальная запоминаемость и живое человечное ощущение без стерильности.",
        "anti_patterns": [
            "Не лучший вариант для плотного мониторинга или серьёзного backoffice.",
            "Не подходит, если быстрое чтение и визуальная сдержанность в абсолютном приоритете.",
        ],
        "context_signals": [
            "Бренд с выразительным или культурным тоном.",
            "Нужно отличаться от типовых SaaS-интерфейсов.",
        ],
        "references": [
            _reference("Vacation", "https://www.vacation.inc"),
            _reference("Wix Trends 2026", "https://www.wix.com/blog/web-design-trends"),
        ],
        "palette_modes": ["recommended", "pastel", "solid", "dopamine"],
        "recommended_palette_mode": "recommended",
        "palettes": {
            "recommended": _palette("#f7cf44", "#ff8a65", "#1d1020", "#61474f", "#ff4268", "#2f1ec9"),
            "pastel": _palette("#f8e9a8", "#f6c7bb", "#201417", "#705d62", "#f28bb2", "#b39df6"),
            "solid": _palette("#ffcd00", "#ff6b35", "#170d14", "#5b4d52", "#ff1f63", "#3c27ff"),
            "dopamine": _palette("#ffe75b", "#ff6fa3", "#160d22", "#59496c", "#ff275e", "#19a7ff"),
        },
        "font_pairings": (
            _font_pairing(
                "maxi-retro",
                "Журнальное ретро",
                "Bricolage Grotesque",
                "Newsreader",
                notes="Заголовки с жестом и основной текст, который читается как журнал.",
            ),
            _font_pairing(
                "maxi-saturated",
                "Насыщенный и человечный",
                "Archivo Black",
                "DM Sans",
                notes="Больше прямого эффекта и меньше утончённой ностальгии.",
            ),
        ),
        "suggested_density": "Выше средней, с видимыми слоями, быстрым ритмом и блоками, которые намеренно наезжают друг на друга.",
        "suggested_tone": "Выразительный, человечный и с чувством визуальной культуры.",
        "suggested_component": "Многослойный hero со стикерами, наклонёнными карточками и главным CTA.",
    },
    {
        "id": "kinetic-typography",
        "name": "Кинетическая типографика",
        "summary": "Текст доминирует в опыте: гигантский, драматизированный и задуманный как визуальный жест.",
        "description": "Направление, построенное на заголовках и типографском ритме. Типографика перестаёт быть опорой и становится структурой.",
        "when_to_use": "Очень хороша, когда коммерческое или нарративное сообщение сильнее графики и должно управлять страницей.",
        "anti_patterns": [
            "Не идеальна, если продукт зависит от множества второстепенных объяснений поверх главного claim.",
            "Не подходит, если бренду нужны сдержанность или классический корпоративный голос.",
        ],
        "context_signals": [
            "Проект с сильными claims или очень ясным позиционированием.",
            "Нужно превратить заголовки и скролл в опыт.",
        ],
        "references": [
            _reference("Grog Shop", "https://grog.shop"),
            _reference("Made by Analogue", "https://www.madebyanalogue.com"),
        ],
        "palette_modes": ["recommended", "pastel", "solid", "monochrome"],
        "recommended_palette_mode": "recommended",
        "palettes": {
            "recommended": _palette("#fbf6ef", "#efe4d6", "#111111", "#5a524b", "#111111", "#ef5338"),
            "pastel": _palette("#fbf4ef", "#f1d5dc", "#141111", "#746966", "#ea8aa2", "#7cb6ff"),
            "solid": _palette("#f8efe6", "#e9d4c1", "#121212", "#62574d", "#121212", "#ff4b2b"),
            "monochrome": _palette("#f3f3f3", "#d9d9d9", "#0f0f0f", "#5e5e5e", "#121212", "#303030"),
        },
        "font_pairings": (
            _font_pairing(
                "kinetic-core",
                "Kinetic Core",
                "Archivo Black",
                "Space Grotesk",
                notes="Огромные заголовки и сдержанный основной текст, который с ними не спорит.",
            ),
            _font_pairing(
                "kinetic-editorial",
                "Kinetic Editorial",
                "Syne",
                "IBM Plex Sans",
                notes="Больше органичного жеста и меньше геометрической жёсткости.",
            ),
        ),
        "suggested_density": "Средняя, с доминирующими заголовками и сильным контрастом масштабов.",
        "suggested_tone": "Прямой, энергичный и перформативный.",
        "suggested_component": "Hero с гигантским текстом, напряжёнными словами и неброским вторичным CTA.",
    },
    {
        "id": "interactive-3d-webgl",
        "name": "Интерактивное 3D и WebGL",
        "summary": "Объём, глубина и объекты как часть сообщения продукта.",
        "description": "Направление для продуктов, которым нужны объект, пространство или иммерсивная визуальная демонстрация до подробных объяснений.",
        "when_to_use": "Подходит, когда опыт или продукт сильно выигрывают, если воспринимаются как объект, которым можно управлять, или как иммерсивная среда.",
        "anti_patterns": [
            "Не подходит для landing, где конверсия зависит от мгновенного чтения и низкой визуальной нагрузки.",
            "Не лучший первый вариант, если команда не сможет поддерживать амбициозный визуальный слой.",
        ],
        "context_signals": [
            "Продукт с пространственной, визуальной или осязаемой составляющей.",
            "Нужно создать глубину и ощущение исследования.",
        ],
        "references": [
            _reference("Nike", "https://www.nike.com"),
            _reference("Spline", "https://spline.design"),
        ],
        "palette_modes": ["recommended", "pastel", "solid", "monochrome"],
        "recommended_palette_mode": "recommended",
        "palettes": {
            "recommended": _palette("#eef2ff", "#dfe5ff", "#111827", "#546179", "#4f46e5", "#0ea5e9"),
            "pastel": _palette("#f2f4ff", "#e1e7ff", "#152033", "#687487", "#9aa7ff", "#87d2ff"),
            "solid": _palette("#e8eeff", "#d5e0ff", "#0f172a", "#4f5a72", "#4338ca", "#0284c7"),
            "monochrome": _palette("#f2f4f7", "#dde2e8", "#111827", "#667085", "#1f2937", "#475467"),
        },
        "font_pairings": (
            _font_pairing(
                "3d-core",
                "Immersive Sans",
                "Sora",
                "Inter",
                notes="Технологичная, но без дешёвой научной фантастики.",
            ),
            _font_pairing(
                "3d-product",
                "Product Spatial",
                "Outfit",
                "Manrope",
                notes="Мягче и коммерчески точнее для современного продукта.",
            ),
        ),
        "suggested_density": "Средняя, с фокусом на очень заметном объекте или сцене в hero.",
        "suggested_tone": "Иммерсивный, амбициозный и очень визуальный.",
        "suggested_component": "Hero с главным 3D-объектом и боковой панелью с сообщением и CTA.",
    },
    {
        "id": "glassmorphism-2",
        "name": "Glassmorphism 2.0",
        "summary": "Полупрозрачные панели, сдержанная глубина и интерфейс с мягкими зрелыми слоями.",
        "description": "Более сдержанная версия glassmorphism. Меньше модного трюка и больше системы с ясными слоями, blur, светом и глубиной.",
        "when_to_use": "Работает, когда продукт хочет выглядеть продвинутым и отполированным без брутализма и крайнего минимализма.",
        "anti_patterns": [
            "Не подходит, если бренду нужны грубость, трение или индустриальное ощущение.",
            "Не лучший вариант, когда контекст требует максимальной типографской прочности и ноля орнамента.",
        ],
        "context_signals": [
            "Цифровой продукт с премиальными амбициями.",
            "Нужны слои, состояние и глубина с современным ощущением.",
        ],
        "references": [
            _reference("Apple HIG", "https://developer.apple.com/design/human-interface-guidelines"),
            _reference("UX Collective", "https://uxdesign.cc/the-most-popular-experience-design-trends-of-2026-3ca85c8a3e3d"),
        ],
        "palette_modes": ["recommended", "pastel", "solid", "monochrome"],
        "recommended_palette_mode": "recommended",
        "palettes": {
            "recommended": _palette("#edf4ff", "#d9e8ff", "#0f172a", "#526176", "#7c9cff", "#c36bff"),
            "pastel": _palette("#f4f7ff", "#e6defc", "#172033", "#67748c", "#b4c4ff", "#d4b6ff"),
            "solid": _palette("#e7f0ff", "#d7e5ff", "#0b1326", "#4b5a73", "#5a7fff", "#a855f7"),
            "monochrome": _palette("#f3f4f6", "#e2e5ea", "#111827", "#667085", "#475467", "#98a2b3"),
        },
        "font_pairings": (
            _font_pairing(
                "glass-premium",
                "Liquid Premium",
                "Sora",
                "Manrope",
                notes="Мягкая, отполированная и с премиальным духом современного продукта.",
            ),
            _font_pairing(
                "glass-ui",
                "Полупрозрачный UI",
                "Outfit",
                "Plus Jakarta Sans",
                notes="Больше интерфейса и меньше редакционной айдентики.",
            ),
        ),
        "suggested_density": "Средняя, с парящими блоками, чистыми разделениями и иерархией слоёв.",
        "suggested_tone": "Отполированный, премиальный и технологичный без агрессии.",
        "suggested_component": "Панель hero с полупрозрачными карточками, trust bar и чётким CTA.",
    },
    {
        "id": "dopamine-colors",
        "name": "Дофаминовые цвета",
        "summary": "Высокая насыщенность, мгновенная энергия и UI, который ищет быстрый эмоциональный отклик.",
        "description": "Цветное, молодёжное и ударное направление. Бренд входит сначала через цвет, потом через структуру.",
        "when_to_use": "Очень хороша, когда бренду нужны радость, энергия, заметность и он не боится выглядеть явно некорпоративным.",
        "anti_patterns": [
            "Не подходит для регуляторных контекстов, сдержанного B2B или продуктов, которым нужно тихое доверие.",
            "Не подходит, если цветовой доступностью не занимаются дисциплинированно.",
        ],
        "context_signals": [
            "Молодёжный бренд или бренд с очень заметным тоном.",
            "Нужно создать энергию и эмоциональную мгновенность.",
        ],
        "references": [
            _reference("Lush", "https://www.lush.com"),
            _reference("Starface", "https://www.starface.world"),
        ],
        "palette_modes": ["recommended", "pastel", "solid", "dopamine"],
        "recommended_palette_mode": "recommended",
        "palettes": {
            "recommended": _palette("#fff46a", "#ffb800", "#161019", "#5d5267", "#ff4fa3", "#2266ff"),
            "pastel": _palette("#fff8b3", "#ffd6ea", "#1a1520", "#685f71", "#ff9ecb", "#9ebcff"),
            "solid": _palette("#ffe500", "#ff9900", "#120d19", "#5a4e66", "#ff2f92", "#1f5dff"),
            "dopamine": _palette("#f9ff57", "#ff7a00", "#0f0a18", "#564b63", "#ff2478", "#00a6ff"),
        },
        "font_pairings": (
            _font_pairing(
                "dopamine-pop",
                "Насыщенный поп",
                "Bungee",
                "DM Sans",
                notes="Сильное присутствие бренда и очень читаемый основной текст.",
            ),
            _font_pairing(
                "dopamine-clean",
                "Читаемая энергия",
                "Syne",
                "Work Sans",
                notes="Проще поддерживать долго без потери энергии.",
            ),
        ),
        "suggested_density": "Выше средней, с ясными блоками, цветом в главной роли и быстрым ритмом.",
        "suggested_tone": "Энергичный, заметный и очень эмоциональный.",
        "suggested_component": "Hero с коротким claim, ярким CTA и очень цветной мозаикой преимуществ.",
    },
    {
        "id": "nature-distilled",
        "name": "Nature distilled / Органика",
        "summary": "Земляные тона, мягкие кривые и интерфейс, который дышит теплом и подлинностью.",
        "description": "Органичное и спокойное направление. Меньше жёсткой сетки, больше контролируемой асимметрии, тепла и тактильности.",
        "when_to_use": "Подходит, когда продукту нужны человеческое доверие, устойчивость, спокойствие или менее синтетический бренд.",
        "anti_patterns": [
            "Не лучший путь для чисто технических или крайне операционных продуктов.",
            "Не подходит, если цель в графическом напряжении, коммерческой агрессии или индустриальном ощущении.",
        ],
        "context_signals": [
            "Бренд с человечным и подлинным тоном.",
            "Нужно передать устойчивость, спокойствие или близость.",
        ],
        "references": [
            _reference("Gormley & Gamble", "https://www.gormleyandgamble.com"),
            _reference("Elementor Trends", "https://elementor.com/blog/web-design-trends-2026/"),
        ],
        "palette_modes": ["recommended", "pastel", "earth", "monochrome"],
        "recommended_palette_mode": "recommended",
        "palettes": {
            "recommended": _palette("#efe6d8", "#d7c4aa", "#1f1a17", "#695f57", "#8c6a42", "#5f7b5c"),
            "pastel": _palette("#f5efe5", "#e8d8c6", "#201a17", "#766a61", "#c3a385", "#a8c2a4"),
            "earth": _palette("#e8dccb", "#ccb18c", "#1f1814", "#6a5c4c", "#9b6b3a", "#5b7850"),
            "monochrome": _palette("#f1ece6", "#ddd4c8", "#181614", "#68615a", "#5f5750", "#2a2623"),
        },
        "font_pairings": (
            _font_pairing(
                "nature-warm",
                "Органичное тепло",
                "Fraunces",
                "Work Sans",
                notes="Фактурный serif и функциональный sans для человечного баланса.",
            ),
            _font_pairing(
                "nature-soft",
                "Спокойная редакционная",
                "Cormorant Garamond",
                "Manrope",
                notes="Более чувственная и редакционная для продуманных брендов.",
            ),
        ),
        "suggested_density": "Воздушная, с плавными секциями и спокойной иерархией.",
        "suggested_tone": "Человечный, спокойный и осязаемый.",
        "suggested_component": "Органичный hero с фотографией или мягким пятном, ценностью и сдержанным CTA.",
    },
    {
        "id": "neo-brutalism",
        "name": "Антидизайн / Необрутализм",
        "summary": "Жёсткие рамки, чёрные тени, сломанная сетка и контролируемое несовершенство с сильным характером.",
        "description": "Направление с высоким формальным контрастом. Выглядит человечным, антикорпоративным и явно не синтетическим.",
        "when_to_use": "Отлично работает, когда бренду нужны напряжение, ирония, визуальное трение и айдентика, которую трудно спутать.",
        "anti_patterns": [
            "Не подходит, если продукту нужны тихая элегантность или отполированная премиальная изысканность.",
            "Не лучший первый вариант для очень плотных dashboards или продуктов с ультраконсервативной аудиторией.",
        ],
        "context_signals": [
            "Бренд со своим голосом, который не готов выглядеть типовым.",
            "Нужно сильное присутствие простыми визуальными средствами.",
        ],
        "references": [
            _reference("Brutalist Websites", "https://www.brutalistwebsites.com"),
            _reference("WannaThis Trends", "https://wannathis.one/blog/web-design-trends-2026"),
        ],
        "palette_modes": ["recommended", "pastel", "solid", "monochrome"],
        "recommended_palette_mode": "recommended",
        "palettes": {
            "recommended": _palette("#f7f0e8", "#efc6d2", "#111111", "#4b4b4b", "#111111", "#bfd4f4"),
            "pastel": _palette("#f7f0e8", "#f3d1a9", "#111111", "#4f4f4f", "#111111", "#cfc6ee"),
            "solid": _palette("#fff0b3", "#ff6b6b", "#111111", "#525252", "#111111", "#4d96ff"),
            "monochrome": _palette("#f4f4f4", "#dadada", "#101010", "#5f5f5f", "#111111", "#373737"),
        },
        "font_pairings": (
            _font_pairing(
                "brutal-core",
                "Brutal Core",
                "Archivo Black",
                "IBM Plex Mono",
                notes="Заголовок как удар молотом и основной текст в тоне системы или терминала.",
            ),
            _font_pairing(
                "brutal-readable",
                "Читаемый брутализм",
                "Archivo Black",
                "Space Grotesk",
                notes="Сохраняет брутальную энергию при менее сухом чтении.",
            ),
        ),
        "suggested_density": "Средняя, с жёсткими коробками, резкой иерархией и доминированием заголовков.",
        "suggested_tone": "Прямой, ироничный и намеренно неотполированный.",
        "suggested_component": "Hero из смещённых коробок, кривых тегов и CTA с брутальной тенью.",
    },
    {
        "id": "ai-hyperminimalism",
        "name": "AI-гиперминимализм",
        "summary": "Свет, мягкие градиенты, много воздуха и элегантная технология без шума.",
        "description": "Чистое и очень сдержанное направление. Изысканность идёт от композиции, типографики и микродеталей, а не от орнамента.",
        "when_to_use": "Очень подходит для AI-продуктов, премиального tooling или брендов, которым нужны ясность и уровень без корпоративной пустоты.",
        "anti_patterns": [
            "Не лучший вариант, если бренду нужны эксцентричность или очень шероховатая айдентика.",
            "Не подходит, если продукт просит выразительного хаоса или очень коммерческой энергии.",
        ],
        "context_signals": [
            "Продукт с технико-премиальным позиционированием.",
            "Нужны высокая ясность, порядок и сдержанная изысканность.",
        ],
        "references": [
            _reference("OpenAI", "https://openai.com"),
            _reference("ElevenLabs", "https://elevenlabs.io"),
        ],
        "palette_modes": ["recommended", "pastel", "solid", "monochrome"],
        "recommended_palette_mode": "recommended",
        "palettes": {
            "recommended": _palette("#f7f9fc", "#ecf1f8", "#101828", "#667085", "#7c8cff", "#86d2ff"),
            "pastel": _palette("#fafbff", "#eff2fb", "#111827", "#6b7280", "#b3bcff", "#b6e6ff"),
            "solid": _palette("#f5f7fb", "#e8eef8", "#0f172a", "#5b667d", "#6475ff", "#54b8ff"),
            "monochrome": _palette("#f8fafc", "#e2e8f0", "#0f172a", "#64748b", "#334155", "#94a3b8"),
        },
        "font_pairings": (
            _font_pairing(
                "hyperminimal-core",
                "Hyperminimal Core",
                "Manrope",
                "Inter",
                notes="Очень чистый, актуальный и в духе премиального tooling.",
            ),
            _font_pairing(
                "hyperminimal-soft",
                "Soft Precision",
                "Sora",
                "Public Sans",
                notes="Чуть более редакционный без потери чистоты.",
            ),
        ),
        "suggested_density": "Воздушная, с большим негативным пространством и малошумной иерархией.",
        "suggested_tone": "Точный, элегантный и уверенный.",
        "suggested_component": "Чистый hero с градиентом, мягкими chips и очень чётким главным CTA.",
    },
    {
        "id": "narrative-scroll-gamification",
        "name": "Нарративный скролл и геймификация",
        "summary": "Landing проходится как история: прогресс, этапы и последовательный ритм.",
        "description": "Направление для страниц, которые лучше конвертируют, когда воспринимаются как ведомый маршрут, а не статичная мозаика.",
        "when_to_use": "Подходит, когда продукту нужно обучать, выстраивать мысленную прогрессию или переводить сложность в ясную последовательность.",
        "anti_patterns": [
            "Не идеально, если визит должен решить всё за очень короткий взгляд.",
            "Не подходит, если бренду нужно одно впечатление от hero без дальнейшего нарратива.",
        ],
        "context_signals": [
            "Продукт с onboarding, фазами или ясной историей.",
            "Нужно превратить скролл в постепенное объяснение.",
        ],
        "references": [
            _reference("Stripe", "https://www.stripe.com"),
            _reference("Duolingo", "https://www.duolingo.com"),
        ],
        "palette_modes": ["recommended", "pastel", "solid", "monochrome"],
        "recommended_palette_mode": "recommended",
        "palettes": {
            "recommended": _palette("#f5f7fb", "#dbe7ff", "#111827", "#667085", "#2f6fed", "#16b364"),
            "pastel": _palette("#f8f9ff", "#e5eefc", "#162032", "#6a768e", "#9ab8ff", "#9ee2bb"),
            "solid": _palette("#f2f6ff", "#d5e0ff", "#0f172a", "#55637a", "#1d4ed8", "#12b76a"),
            "monochrome": _palette("#f8fafc", "#e2e8f0", "#0f172a", "#64748b", "#334155", "#94a3b8"),
        },
        "font_pairings": (
            _font_pairing(
                "narrative-flow",
                "Narrative Flow",
                "Syne",
                "Space Grotesk",
                notes="Задаёт ритм скролла, не теряя тона серьёзного продукта.",
            ),
            _font_pairing(
                "narrative-product",
                "Product Journey",
                "Sora",
                "Manrope",
                notes="Больше современного продукта и меньше редакционного жеста.",
            ),
        ),
        "suggested_density": "Средняя, с последовательными секциями, рельсами прогресса и хорошо расставленными моментами.",
        "suggested_tone": "Ведомый, ясный и с ощущением движения вперёд.",
        "suggested_component": "Входной hero с рельсом шагов, преимуществами по этапам и финальным CTA прогресса.",
    },
)


STYLE_CATALOG_BY_ID: Dict[str, Dict[str, Any]] = {
    entry["id"]: entry for entry in STYLE_CATALOG
}

PALETTE_MODE_BY_ID: Dict[str, Dict[str, str]] = {
    entry["id"]: entry for entry in PALETTE_MODE_CATALOG
}


def get_style_catalog() -> List[Dict[str, Any]]:
    """Return the full catalog of visual families."""
    return [_with_style_cues(entry) for entry in STYLE_CATALOG]


def get_style_trend(style_id: str) -> Dict[str, Any]:
    """Return a canonical visual family by id."""
    normalized_id = str(style_id or "").strip()
    if normalized_id not in STYLE_CATALOG_BY_ID:
        raise KeyError(f"Unknown Designer style: {normalized_id}")
    return _with_style_cues(STYLE_CATALOG_BY_ID[normalized_id])


def get_palette_modes() -> List[Dict[str, str]]:
    """Return the canonical list of palette modes."""
    return [deepcopy(entry) for entry in PALETTE_MODE_CATALOG]


def resolve_palette_mode_meta(palette_mode: Optional[str]) -> Dict[str, str]:
    """Return the canonical metadata of a palette mode."""
    normalized_id = str(palette_mode or "").strip() or "recommended"
    meta = PALETTE_MODE_BY_ID.get(normalized_id)
    if meta is None:
        meta = PALETTE_MODE_BY_ID["recommended"]
    return deepcopy(meta)


def resolve_palette(style_id: str, palette_mode: Optional[str] = None) -> Tuple[Dict[str, str], str]:
    """Resolve the actual palette to use for a visual family."""
    style = get_style_trend(style_id)
    requested_mode = str(palette_mode or style["recommended_palette_mode"]).strip() or "recommended"
    palette_map = style["palettes"]

    if requested_mode in palette_map:
        return deepcopy(palette_map[requested_mode]), requested_mode

    fallback_mode = style["recommended_palette_mode"]
    return deepcopy(palette_map[fallback_mode]), fallback_mode


def resolve_font_pairing(
    style_id: str,
    *,
    pairing_id: Optional[str] = None,
    custom_google_fonts_url: Optional[str] = None,
    custom_headings: Optional[str] = None,
    custom_body: Optional[str] = None,
) -> Dict[str, str]:
    """Return the active font pairing for a visual family."""
    if custom_google_fonts_url:
        headings = str(custom_headings or custom_body or "Custom Headings").strip()
        body = str(custom_body or custom_headings or "Custom Body").strip()
        return {
            "id": "custom-google-fonts",
            "label": "Custom Google Fonts",
            "headings": headings,
            "body": body,
            "notes": "URL от пользователя, чтобы задать семейство шрифтов.",
            "headings_specimen_url": custom_google_fonts_url,
            "body_specimen_url": custom_google_fonts_url,
            "css_url": custom_google_fonts_url,
            "source": "custom-google-fonts",
            "custom_url": custom_google_fonts_url,
        }

    style = get_style_trend(style_id)
    pairings = list(style["font_pairings"])
    if pairing_id:
        for pairing in pairings:
            if pairing["id"] == pairing_id:
                return deepcopy(pairing)
    return deepcopy(pairings[0])


def _palette_to_roles(palette: Dict[str, str]) -> List[Dict[str, str]]:
    return [
        {"role": "surface", "value": palette["surface"]},
        {"role": "surface_alt", "value": palette["surface_alt"]},
        {"role": "accent", "value": palette["accent"]},
        {"role": "accent_alt", "value": palette["accent_alt"]},
        {"role": "ink", "value": palette["ink"]},
        {"role": "muted", "value": palette["muted"]},
    ]


def _palette_to_tokens(palette: Dict[str, str]) -> List[Dict[str, str]]:
    return [
        {"name": "color.bg.surface", "value": palette["surface"]},
        {"name": "color.bg.surface_alt", "value": palette["surface_alt"]},
        {"name": "color.text.primary", "value": palette["ink"]},
        {"name": "color.text.muted", "value": palette["muted"]},
        {"name": "color.brand.primary", "value": palette["accent"]},
        {"name": "color.brand.secondary", "value": palette["accent_alt"]},
    ]


def build_style_catalog_proposal(
    style_id: str,
    *,
    choice: str,
    palette_mode: Optional[str] = None,
    font_pairing_id: Optional[str] = None,
    custom_google_fonts_url: Optional[str] = None,
    custom_headings: Optional[str] = None,
    custom_body: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a Designer proposal from the catalog."""
    style = get_style_trend(style_id)
    palette, resolved_palette_mode = resolve_palette(style_id, palette_mode)
    palette_mode_meta = resolve_palette_mode_meta(resolved_palette_mode)
    font_pairing = resolve_font_pairing(
        style_id,
        pairing_id=font_pairing_id,
        custom_google_fonts_url=custom_google_fonts_url,
        custom_headings=custom_headings,
        custom_body=custom_body,
    )

    return {
        "choice": str(choice).strip(),
        "name": style["name"],
        "concept": style["description"],
        "style_family": style["id"],
        "style_family_label": style["name"],
        "palette_mode": resolved_palette_mode,
        "palette_mode_label": palette_mode_meta["label"],
        "palette": _palette_to_roles(palette),
        "typography": {
            "pairing_id": font_pairing["id"],
            "pairing_label": font_pairing["label"],
            "headings": font_pairing["headings"],
            "body": font_pairing["body"],
            "scale": "14 / 18 / 24 / 40 / 72",
            "notes": font_pairing["notes"],
            "headings_url": font_pairing["headings_specimen_url"],
            "body_url": font_pairing["body_specimen_url"],
            "css_url": font_pairing["css_url"],
            "source": font_pairing["source"],
            "custom_url": font_pairing.get("custom_url", ""),
        },
        "spacing_density": style["suggested_density"],
        "tone": style["suggested_tone"],
        "sample_component": style["suggested_component"],
        "visual_principles": list(style.get("visual_principles", [])),
        "layout_grammar": style.get("layout_grammar", ""),
        "surface_treatment": style.get("surface_treatment", ""),
        "shape_language": style.get("shape_language", ""),
        "motion_language": style.get("motion_language", ""),
        "signature_elements": list(style.get("signature_elements", [])),
        "implementation_guardrails": list(style.get("implementation_guardrails", [])),
        "prompt_seed": style.get("prompt_seed", ""),
        "rationale": style["when_to_use"],
        "not_this_direction": list(style["anti_patterns"]),
        "context_signals": list(style["context_signals"]),
        "reference_urls": [deepcopy(item) for item in style["references"]],
        "tokens": _palette_to_tokens(palette),
    }
