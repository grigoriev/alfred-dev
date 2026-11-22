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
        self.assertIsNone(classify_prompt("/alfred-dev:fix el login"))
        self.assertIsNone(classify_prompt("/compact"))

    def test_classifies_common_spanish_phrases(self):
        cases = {
            "sigue donde lo dejé": "resume",
            "el login peta con eñes": "fix",
            "cambia el texto del botón": "quick",
            "esto va a producción": "ship",
            "qué decidimos de auth": "memory",
            "mapea este repo": "map-codebase",
            "audita la security": "audit",
        }
        for prompt, route in cases.items():
            match = classify_prompt(prompt)
            self.assertIsNotNone(match, prompt)
            self.assertEqual(match["route"], route, prompt)

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
            "добавь экспорт в CSV": "feature",
            "поменяй текст кнопки": "quick",
            "исправь опечатку в заголовке": "quick",
        }
        for prompt, route in cases.items():
            match = classify_prompt(prompt)
            self.assertIsNotNone(match, prompt)
            self.assertEqual(match["route"], route, prompt)

    def test_cto_route_keywords_and_legacy_aliases(self):
        for prompt in ("позови cto", "нужен технический директор", "пусть люциус посмотрит", "ask lucius"):
            match = classify_prompt(prompt)
            self.assertIsNotNone(match, prompt)
            self.assertEqual(match["route"], "cto", prompt)
            self.assertEqual(match["command"], "/alfred-dev:cto", prompt)

    def test_russian_routes_map_to_commands(self):
        self.assertEqual(classify_prompt("пауза")["command"], "/alfred-dev:pause")
        self.assertEqual(classify_prompt("исследуй это")["command"], "/alfred-dev:spike")
        self.assertIn("/alfred-dev:fix", render_route_hint(classify_prompt("логин падает")))

    def test_short_or_empty_is_silent(self):
        self.assertIsNone(classify_prompt("ok"))
        self.assertIsNone(classify_prompt("hola"))
        self.assertIsNone(classify_prompt("   "))
        self.assertIsNone(classify_prompt("привет"))

    def test_hint_mentions_command(self):
        match = classify_prompt("el endpoint falla con 500")
        self.assertIsNotNone(match)
        self.assertIn("/alfred-dev:fix", render_route_hint(match))

    def test_hook_emits_additional_context(self):
        script = os.path.join(os.path.dirname(__file__), "..", "hooks", "prompt-route.py")
        result = subprocess.run(
            [sys.executable, script],
            input=json.dumps({"prompt": "el login peta"}),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        context = payload["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("/alfred-dev:fix", context)

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
            input=json.dumps({"prompt": "hola"}),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
