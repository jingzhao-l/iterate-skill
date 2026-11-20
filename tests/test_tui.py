"""TUI 渲染器接口契约测试.

覆盖：
- question() 只打印问题头、返回 None（接口契约，防止签名与实现漂移）
- prompt_prefix() 已移除（曾返回 rich 标记字符串，会被当作 input() 提示
  文本直接显示，造成 `[iterate.dim]` 标记泄露到终端）
- _display_width() CJK 全角/半角宽度计算
- 各渲染方法（banner/intro/section/info/hint/warning/error/success/bullet/
  key_value/numbered_list/panel/cancel/empty_line）输出到注入 console
- error() 通过 stderr console 输出（注入模式下与主 console 复用）
- cli._should_show_banner 的 --no-banner / ITERATE_NO_BANNER / --json 逻辑
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, get_type_hints

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from iterate_cli import cli
from iterate_cli.tui import TUI, _display_width


class _RecordingConsole:
    """记录 print 调用的假 Console，仅实现 TUI 用到的接口."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    @property
    def is_terminal(self) -> bool:
        return False

    def print(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(args)


def _make_tui() -> tuple[TUI, _RecordingConsole]:
    console = _RecordingConsole()
    return TUI(console=console), console


def _rendered(console: _RecordingConsole) -> str:
    """将 console 记录的所有调用拼成纯文本（忽略 rich 标记）. """
    return "\n".join(" ".join(str(arg) for arg in call) for call in console.calls)


class TestQuestionContract:
    def test_return_annotation_is_none(self) -> None:
        """question() 声明的返回类型必须是 None（与实现一致）."""
        hints = get_type_hints(TUI.question)
        assert hints.get("return") is type(None), (
            "question() 签名声明的返回类型应为 None，当前为 "
            f"{hints.get('return')!r}"
        )

    def test_question_returns_none(self) -> None:
        tui, _ = _make_tui()
        assert tui.question("继续吗？") is None

    def test_question_prints_marker_and_message(self) -> None:
        tui, console = _make_tui()
        tui.question("请输入维度编号")
        rendered = " ".join(str(arg) for arg in console.calls[0])
        assert "请输入维度编号" in rendered


class TestPromptPrefixRemoved:
    def test_prompt_prefix_not_defined(self) -> None:
        """prompt_prefix() 应已删除：无调用方，且会把 rich 标记泄露进提示文本."""
        assert not hasattr(TUI, "prompt_prefix"), (
            "TUI.prompt_prefix 应删除（死代码，返回值含 rich 标记会被 "
            "input() 直接显示）"
        )


class TestDisplayWidth:
    def test_ascii_is_single_width(self) -> None:
        assert _display_width("abc123") == 6

    def test_cjk_is_double_width(self) -> None:
        assert _display_width("中文") == 4

    def test_mixed_width(self) -> None:
        assert _display_width("iter-中文") == 9  # 5 ascii + 4 cjk

    def test_control_characters_skipped(self) -> None:
        assert _display_width("\x00\x01a") == 1

    def test_fullwidth_punctuation(self) -> None:
        # 全角冒号/括号按双宽计算
        assert _display_width("：（）") == 6

    def test_emoji_is_double_width(self) -> None:
        # Emoji 在多数终端按 2 列渲染（U+1F000–U+1FAFF）
        assert _display_width("🚀") == 2
        assert _display_width("a🚀") == 3

    def test_combining_and_variation_selectors_are_zero_width(self) -> None:
        # 组合用记号与变体选择符（VS16）宽度为 0，跟随前一字符
        assert _display_width("e\u0301") == 1  # e + combining acute
        assert _display_width("✋\ufe0f") == 1  # ️hand + VS16 (counted 1 via 0-width VS16)
        assert _display_width("中\u0301") == 2  # CJK + combining

    def test_del_and_c1_controls_skipped(self) -> None:
        assert _display_width("\x7f\x80\x81a") == 1


class TestRenderMethods:
    def test_banner_renders_iterate_ascii(self) -> None:
        tui, console = _make_tui()
        tui.banner()
        rendered = _rendered(console)
        assert "ITERATE" in rendered or "██" in rendered

    def test_intro_renders_title_and_subtitle(self) -> None:
        tui, console = _make_tui()
        tui.intro("Iterate Skill", "项目知识库初始化")
        rendered = _rendered(console)
        assert "Iterate Skill" in rendered
        assert "项目知识库初始化" in rendered
        assert "◆" in rendered

    def test_section_renders_title(self) -> None:
        tui, console = _make_tui()
        tui.section("技术栈 / Tech Stack")
        assert "技术栈 / Tech Stack" in _rendered(console)

    def test_info_hint_bullet_render_content(self) -> None:
        tui, console = _make_tui()
        tui.info("信息行")
        tui.hint("提示行")
        tui.bullet("列表项")
        rendered = _rendered(console)
        assert "信息行" in rendered
        assert "提示行" in rendered
        assert "列表项" in rendered

    def test_warning_renders_warning_symbol(self) -> None:
        tui, console = _make_tui()
        tui.warning("警告")
        assert "⚠" in _rendered(console)
        assert "警告" in _rendered(console)

    def test_error_renders_error_symbol(self) -> None:
        # 注入 console 时 _stderr_console 复用同一实例，error 也写入同一 console
        tui, console = _make_tui()
        tui.error("出错")
        assert "✗" in _rendered(console)
        assert "出错" in _rendered(console)

    def test_success_renders_check_mark(self) -> None:
        tui, console = _make_tui()
        tui.success("成功")
        assert "✓" in _rendered(console)
        assert "成功" in _rendered(console)

    def test_key_value_pads_label(self) -> None:
        tui, console = _make_tui()
        tui.key_value("语言", "zh")
        rendered = _rendered(console)
        assert "语言" in rendered
        assert "zh" in rendered

    def test_key_value_label_width_ignores_markup_escaping(self) -> None:
        """A ``[`` in the key must not widen the label column.

        The label is escaped for rich markup (``[`` -> ``\\[``); measuring the
        *escaped* text over-counted each bracket by one column and pushed the
        value to the right. The visible padded label must stay exactly
        ``KEY_VALUE_WIDTH`` columns wide either way.
        """
        import re

        from iterate_cli.tui import KEY_VALUE_WIDTH

        def _visible_label_width(render: str) -> int:
            match = re.search(r"\[iterate\.label\](.*?)\[/\]", render)
            assert match, render
            visible = match.group(1).replace(r"\[", "[")
            return _display_width(visible)

        tui_a, console_a = _make_tui()
        tui_a.key_value("a[b]", "v")
        tui_b, console_b = _make_tui()
        tui_b.key_value("axxb", "v")

        assert _visible_label_width(_rendered(console_a)) == KEY_VALUE_WIDTH
        assert _visible_label_width(_rendered(console_a)) == _visible_label_width(
            _rendered(console_b)
        )

    def test_long_hint_wraps_with_a_hanging_indent(self) -> None:
        """Continuation lines line up under the message, not at column 0.

        Rich's own paragraph wrap restarts continuation lines at column 0, so a
        long hint looked like a new block. The wrap budget is measured in
        display columns, so CJK text fits too.
        """
        from rich.console import Console

        console = Console(record=True, width=60, force_terminal=False)
        tui = TUI(console=console)
        tui.hint("这是一个很长的中文提示" * 4)

        lines = console.export_text().splitlines()
        assert len(lines) > 1
        assert all(_display_width(line) <= 60 for line in lines), lines
        assert all(line.startswith("  ") for line in lines), lines

    def test_command_is_never_wrapped(self) -> None:
        """Suggestions must stay copy-pasteable as one shell command."""
        from rich.console import Console

        console = Console(record=True, width=40, force_terminal=False)
        tui = TUI(console=console)
        command = "iterate config set dimensions " + ",".join(["a"] * 20)
        tui.command(command)

        lines = console.export_text().splitlines()
        assert lines == [f"  {command}"]

    def test_long_warning_keeps_its_marker_only_on_the_first_line(self) -> None:
        from rich.console import Console

        console = Console(record=True, width=50, force_terminal=False)
        tui = TUI(console=console)
        tui.warning("warning " * 12)

        lines = console.export_text().splitlines()
        assert "⚠" in lines[0]
        assert all("⚠" not in line for line in lines[1:])
        assert all(_display_width(line) <= 50 for line in lines), lines

    def test_key_value_wrapped_rows_fit_the_console_width(self) -> None:
        """A long breakable value must wrap inside the console, not past it.

        The separator space between the padded label and the value was left out
        of the wrap budget, so the first row was exactly one column too wide;
        rich then folded the value onto its own line at column 0.
        """
        from rich.console import Console

        console = Console(record=True, width=80, force_terminal=False)
        tui = TUI(console=console)
        value = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
        tui.key_value("Notes", value)

        lines = console.export_text().splitlines()
        assert len(lines) > 1
        assert all(_display_width(line) <= 80 for line in lines), lines
        # The value starts on the label row and continues at the value column,
        # never at column 0.
        assert "Notes:" in lines[0] and "alpha" in lines[0]
        assert lines[1].startswith(" " * 24)

    def test_key_value_keeps_a_long_path_intact(self) -> None:
        """A path has no break points: keep it on one copy-pasteable line.

        Hard-splitting inserted the continuation indent inside the path, so a
        copied value was corrupted (``…/complet`` + ``ions/…``) and the label
        was left alone on its row. Overflowing one long line is recoverable;
        a broken path is not.
        """
        from rich.console import Console

        console = Console(record=True, width=80, force_terminal=False)
        tui = TUI(console=console)
        path = (
            "/private/var/folders/5h/2m890d1n4nn1ntfmb9lcnkm80000gn/"
            "T/opencode/demo"
        )
        tui.key_value("Project", path)

        lines = console.export_text().splitlines()
        assert lines == [f"  {'Project:':<22} {path}"]

    def test_key_value_wraps_long_cjk_without_overflowing(self) -> None:
        """CJK has no spaces but can be hard-split; it must still fit."""
        from rich.console import Console

        console = Console(record=True, width=50, force_terminal=False)
        tui = TUI(console=console)
        tui.key_value("说明", "这是一个很长的中文值" * 5)

        lines = console.export_text().splitlines()
        assert len(lines) > 1
        assert all(_display_width(line) <= 50 for line in lines), lines
        assert all(line.startswith("  ") for line in lines), lines

    def test_key_value_accepts_an_empty_value(self) -> None:
        """A template with no description renders a label and no value."""
        from rich.console import Console

        console = Console(record=True, width=80, force_terminal=False)
        tui = TUI(console=console)
        tui.key_value("ITERATE.template.md", "")

        assert console.export_text().splitlines() == [
            f"  {'ITERATE.template.md:':<22} "
        ]

    def test_numbered_list_with_markers(self) -> None:
        tui, console = _make_tui()
        tui.numbered_list(["a", "b"], markers=["✓", ""])
        rendered = _rendered(console)
        assert "1." in rendered
        assert "2." in rendered
        assert "✓" in rendered

    def test_panel_renders_content_and_title(self) -> None:
        from rich.panel import Panel

        tui, console = _make_tui()
        tui.panel("面板内容", title="面板标题")
        assert len(console.calls) == 1
        panel = console.calls[0][0]
        assert isinstance(panel, Panel)
        assert "面板内容" in str(panel.renderable)
        assert "面板标题" in str(panel.title)

    def test_markup_in_user_text_is_escaped(self) -> None:
        """User-supplied text must not be parsed as rich markup (F24).

        A hostile/mistyped message like ``[red]x[/]`` must be escaped to
        ``\\[red\\]x\\[/\\]`` so rich prints it literally instead of applying
        the style tag.
        """
        tui, console = _make_tui()
        tui.info("[red]breaks[/]")
        tui.error("[bold]oops[/]")
        tui.hint("[italic]hint[/]")
        tui.warning("[cyan]warn[/]")
        tui.success("[green]ok[/]")
        tui.bullet("[magenta]item[/]")
        tui.key_value("k", "[blue]v[/]")
        tui.numbered_list(["[red]first[/]"])
        tui.question("[red]q?[/]")
        tui.panel("[red]content[/]", title="[red]title[/]")
        tui.intro("[red]title[/]", "[blue]sub[/]")
        tui.section("[red]sec[/]")
        rendered = _rendered(console)
        assert r"\[red]breaks\[/]" in rendered
        assert r"\[bold]oops\[/]" in rendered
        assert r"\[green]ok\[/]" in rendered
        # The literal bracket form must never reach the console unresolved.
        assert "[red]breaks[/]" not in rendered

    def test_cancel_renders_cancelled(self) -> None:
        tui, console = _make_tui()
        tui.cancel()
        rendered = _rendered(console)
        assert "已取消" in rendered

    def test_empty_line_renders(self) -> None:
        tui, console = _make_tui()
        tui.empty_line()
        assert len(console.calls) == 1


class TestShouldShowBanner:
    def _args(self, **overrides: Any) -> argparse.Namespace:
        defaults: dict[str, Any] = {"no_banner": False, "json": False}
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_default_shows_banner_on_tty(self, monkeypatch) -> None:
        monkeypatch.delenv("ITERATE_NO_BANNER", raising=False)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        assert cli._should_show_banner(self._args()) is True

    def test_no_banner_flag_disables(self, monkeypatch) -> None:
        monkeypatch.delenv("ITERATE_NO_BANNER", raising=False)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        assert cli._should_show_banner(self._args(no_banner=True)) is False

    def test_env_var_disables(self, monkeypatch) -> None:
        monkeypatch.setenv("ITERATE_NO_BANNER", "1")
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        assert cli._should_show_banner(self._args()) is False

    def test_empty_env_var_keeps_banner_on_tty(self, monkeypatch) -> None:
        monkeypatch.setenv("ITERATE_NO_BANNER", "")
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        assert cli._should_show_banner(self._args()) is True

    def test_redirected_stdout_disables_banner(self, monkeypatch) -> None:
        """A pipe must never receive the eight-line ASCII banner.

        Regression: it was written to stdout regardless of redirection, so
        `v=$(iterate --version)` captured block art plus the version line,
        contradicting the call site's own promise of a bare parseable line.
        """
        monkeypatch.delenv("ITERATE_NO_BANNER", raising=False)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
        assert cli._should_show_banner(self._args()) is False

    def test_redirected_stdout_beats_an_empty_env_var(self, monkeypatch) -> None:
        monkeypatch.setenv("ITERATE_NO_BANNER", "")
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
        assert cli._should_show_banner(self._args()) is False


class TestJsonHelpText:
    """``iterate --help`` must name every command that accepts ``--json``.

    Regression: the help listed only "status/show/doctor/refresh/config", so a
    script author reading it would wrongly conclude that
    `iterate guard pre-check --json`, `invariant`, `fingerprint` and `update`
    had no structured mode — all four do (verified against the subparsers).
    """

    JSON_CAPABLE = (
        "status",
        "scan",
        "show",
        "doctor",
        "refresh",
        "config",
        "guard",
        "invariant",
        "fingerprint",
        "update",
    )

    @staticmethod
    def _help_text() -> str:
        return cli._build_parser().format_help()

    @staticmethod
    def _json_option_help() -> str:
        """The unwrapped `--json` option string, independent of wrapping.

        `format_help()` hard-wraps to the terminal width, so grepping a line of
        it for a command name breaks whenever the sentence happens to wrap
        between two commands.
        """
        parser = cli._build_parser()
        for action in parser._actions:
            if "--json" in getattr(action, "option_strings", []):
                return action.help or ""
        raise AssertionError("the global --json flag is missing")

    def test_every_json_capable_command_is_listed(self) -> None:
        json_help = self._json_option_help()
        for command in self.JSON_CAPABLE:
            assert command in json_help, (
                f"`--json` help does not mention `{command}`: {json_help!r}"
            )

    def test_help_still_notes_that_interactive_commands_reject_it(self) -> None:
        assert "interactive" in self._help_text().lower()

    def test_the_flag_really_exists_on_each_listed_subcommand(self) -> None:
        """The help must not promise a flag a subcommand lacks."""
        import argparse

        parser = cli._build_parser()
        subactions = [
            a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
        ]
        assert subactions, "expected subparsers"
        choices = subactions[0].choices
        for command in self.JSON_CAPABLE:
            assert command in choices, command
            flags = {
                opt
                for action in choices[command]._actions
                for opt in getattr(action, "option_strings", [])
            }
            assert "--json" in flags, f"`{command}` does not accept --json"


class TestWarningGoesToStderr:
    """Warnings must not pollute stdout: `--json` promises exactly one JSON
    document on stdout for every command, and several commands emit warnings
    while building their payload."""

    def test_warning_writes_to_stderr_only(self, capsys) -> None:
        from iterate_cli.tui import tui as real_tui

        real_tui.warning("careful now")
        captured = capsys.readouterr()
        assert "careful now" in captured.err
        assert "careful now" not in captured.out

    def test_error_and_warning_share_the_stderr_stream(self, capsys) -> None:
        from iterate_cli.tui import tui as real_tui

        real_tui.error("bad thing")
        captured = capsys.readouterr()
        assert "bad thing" in captured.err
        assert "bad thing" not in captured.out
