#!/usr/bin/env python3
"""Classification of prompts without a slash."""

import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.prompt_route import classify_prompt, render_route_hint


class TestPromptRoute(unittest.TestCase):
    def test_slash_commands_are_ignored(self):
        self.assertIsNone(classify_prompt("/alfred-dev:fix логин"))
        self.assertIsNone(classify_prompt("/compact"))

    def test_classifies_common_russian_phrases(self):
        cases = {
            "продолжай с того места": "resume",
            "Продолжить работу": "resume",
            "что дальше?": "resume",
            "на чём мы остановились": "resume",
            "поставь на паузу": "pause",
            "Пауза, на сегодня всё": "pause",
            "приёмка результата": "uat",
            "выкати релиз": "ship",
            "ДЕПЛОЙ в прод": "ship",
            "нужно второе мнение": "cto",
            "проведи аудит безопасности": "audit",
            "составь карту кодовой базы": "map-codebase",
            "какой статус проекта": "progress",
            "покажи канбан": "progress",
            "что мы решили по auth": "memory",
            "логин падает на ёлке": "fix",
            "Нашёл баг в форме": "fix",
            "ошибка 500 на эндпоинте": "fix",
            "всё сломалось после обновления": "fix",
            "не знаю, как это сделать": "discuss",
            "исследуй варианты кэширования": "spike",
            "сравни Drizzle и Prisma": "spike",
            "новая фича для подписок": "feature",
            "где мы остановились вчера": "resume",
            "закончим на сегодня": "pause",
            "нужна ручная проверка": "uat",
            "нужен взгляд со стороны": "cto",
            "проверь безопасность кода": "audit",
            "разберись в репозитории": "map-codebase",
            "страница не грузится": "fix",
            "как лучше хранить сессии": "discuss",
            "реализуй экспорт отчётов": "feature",
            "добавь экспорт в CSV": "feature",
            "поменяй текст кнопки": "quick",
            "исправь опечатку в заголовке": "quick",
        }
        for prompt, route in cases.items():
            match = classify_prompt(prompt)
            self.assertIsNotNone(match, prompt)
            self.assertEqual(match["route"], route, prompt)

    def test_cto_route_keywords(self):
        for prompt in ("позови cto", "нужен технический директор", "нужно второе мнение"):
            match = classify_prompt(prompt)
            self.assertIsNotNone(match, prompt)
            self.assertEqual(match["route"], "cto", prompt)
            self.assertEqual(match["command"], "/alfred-dev:cto", prompt)

    def test_pr_route_keywords(self):
        for prompt in (
            "доведи PR до мержа",
            "смержи PR",
            "смержи, когда всё зелёное",
            "ревью PR от Greptile",
            "открой пулл-реквест",
            "посмотри пул реквест",
            "в PR упал SonarCloud, поправь",
            "в PR конфликт после релиза",
            "PR падает на CI",
            "merge pull request",
        ):
            match = classify_prompt(prompt)
            self.assertIsNotNone(match, prompt)
            self.assertEqual(match["route"], "pr", prompt)
            self.assertEqual(match["command"], "/alfred-dev:pr", prompt)

    def test_pr_route_does_not_capture_other_words(self):
        for prompt, route in (
            ("приёмка результата", "uat"),
            ("выкати релиз", "ship"),
            ("проверь продакшн после деплоя", "ship"),
            ("исправь опечатку в заголовке", "quick"),
        ):
            match = classify_prompt(prompt)
            self.assertIsNotNone(match, prompt)
            self.assertEqual(match["route"], route, prompt)

    def test_russian_routes_map_to_commands(self):
        self.assertEqual(classify_prompt("пауза")["command"], "/alfred-dev:pause")
        self.assertEqual(classify_prompt("исследуй это")["command"], "/alfred-dev:spike")
        self.assertIn("/alfred-dev:fix", render_route_hint(classify_prompt("логин падает")))

    def test_short_or_empty_is_silent(self):
        self.assertIsNone(classify_prompt("ok"))
        self.assertIsNone(classify_prompt("ага"))
        self.assertIsNone(classify_prompt("   "))
        self.assertIsNone(classify_prompt("привет"))

    def test_hint_mentions_command(self):
        match = classify_prompt("эндпоинт падает с 500")
        self.assertIsNotNone(match)
        self.assertIn("/alfred-dev:fix", render_route_hint(match))

    def test_hook_emits_additional_context_for_russian(self):
        script = os.path.join(os.path.dirname(__file__), "..", "hooks", "prompt-route.py")
        result = subprocess.run(
            [sys.executable, script],
            input=json.dumps({"prompt": "логин падает"}, ensure_ascii=False),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("/alfred-dev:fix", context)
        self.assertIn("Действуй как эта команда", context)

    def test_hook_is_silent_without_signal(self):
        script = os.path.join(os.path.dirname(__file__), "..", "hooks", "prompt-route.py")
        result = subprocess.run(
            [sys.executable, script],
            input=json.dumps({"prompt": "привет"}),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
