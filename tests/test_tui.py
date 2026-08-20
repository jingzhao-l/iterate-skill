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

    def test_default_shows_banner(self, monkeypatch) -> None:
        monkeypatch.delenv("ITERATE_NO_BANNER", raising=False)
        assert cli._should_show_banner(self._args()) is True

    def test_no_banner_flag_disables(self, monkeypatch) -> None:
        monkeypatch.delenv("ITERATE_NO_BANNER", raising=False)
        assert cli._should_show_banner(self._args(no_banner=True)) is False

    def test_env_var_disables(self, monkeypatch) -> None:
        monkeypatch.setenv("ITERATE_NO_BANNER", "1")
        assert cli._should_show_banner(self._args()) is False

    def test_empty_env_var_keeps_banner(self, monkeypatch) -> None:
        monkeypatch.setenv("ITERATE_NO_BANNER", "")
        assert cli._should_show_banner(self._args()) is True
