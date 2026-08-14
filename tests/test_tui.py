"""TUI 渲染器接口契约测试.

覆盖：
- question() 只打印问题头、返回 None（接口契约，防止签名与实现漂移）
- prompt_prefix() 已移除（曾返回 rich 标记字符串，会被当作 input() 提示
  文本直接显示，造成 `[iterate.dim]` 标记泄露到终端）
"""

from __future__ import annotations

from typing import Any, get_type_hints

from iterate_cli.tui import TUI


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
