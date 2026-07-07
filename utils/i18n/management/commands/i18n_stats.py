# sync-init: skip
"""
i18n 翻译完整度统计
===================

``python manage.py i18n_stats`` — 列出每种语言的覆盖率
``python manage.py i18n_stats --lang en`` — 仅看英文
``python manage.py i18n_stats --check --min 0.8`` — CI 模式（不达标 exit 1）

只对数据库动态翻译（Translation 表 / 后端）有效。
"""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand

from utils.i18n import get_translation_stats, get_supported_languages


class Command(BaseCommand):
    help = "翻译完整度统计（数据库动态翻译）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--lang",
            type=str,
            help="只看指定语言（如 en / zh-hans）",
        )
        parser.add_argument(
            "--min",
            type=float,
            default=0.0,
            dest="min_coverage",
            help="最低覆盖率（CI 模式下不达标返回 1）",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="CI 模式：低于 --min 时 exit 1",
        )
        parser.add_argument(
            "--format",
            choices=["table", "json"],
            default="table",
            help="输出格式",
        )

    def handle(self, *args, **options):
        langs = (
            [options["lang"]]
            if options.get("lang")
            else [code for code, _ in get_supported_languages()]
        )
        min_cov = options["min_coverage"]
        check = options["check"]
        fmt = options["format"]

        results = []
        for lang in langs:
            try:
                stats = get_translation_stats(lang)
            except Exception as e:
                self.stderr.write(self.style.WARNING(f"[{lang}] stats failed: {e}"))
                stats = {"lang": lang, "total_keys": 0, "translated": 0, "missing": 0, "coverage": 0.0}
            results.append(stats)

        if fmt == "json":
            import json
            self.stdout.write(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            self._print_table(results)

        # CI 校验
        if check:
            failed = [r for r in results if r.get("coverage", 0.0) < min_cov]
            if failed:
                self.stderr.write(
                    self.style.ERROR(
                        f"\nCoverage below {min_cov:.1%}: "
                        + ", ".join(f"{r['lang']}={r['coverage']:.1%}" for r in failed)
                    )
                )
                raise SystemExit(1)
            self.stdout.write(self.style.SUCCESS(f"\nAll languages pass {min_cov:.1%} coverage"))

    def _print_table(self, results: list[dict]) -> None:
        # 表头
        self.stdout.write(
            f"{'lang':<12}{'total':>10}{'translated':>14}{'missing':>10}{'coverage':>12}"
        )
        self.stdout.write("-" * 60)
        for r in results:
            cov = r.get("coverage", 0.0)
            color = (
                self.style.SUCCESS
                if cov >= 0.9
                else (self.style.WARNING if cov >= 0.6 else self.style.ERROR)
            )
            self.stdout.write(
                f"{r.get('lang', '?'):<12}"
                f"{r.get('total_keys', 0):>10}"
                f"{r.get('translated', 0):>14}"
                f"{r.get('missing', 0):>10}"
                + color(f"{cov:>11.1%}")
            )
