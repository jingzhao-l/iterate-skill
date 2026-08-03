"""统一 TUI 渲染层 — skills.sh 风格.

本模块提供所有 CLI 交互的视觉组件，基于 rich 库实现。
设计参考 @clack/prompts 的符号体系和配色方案：
  ◆ intro/outro 标志
  ◇ 问题块标志
  │ └ 垂直连接线
  ● ○ 单选选中/未选
  ✓ ✗ 成功/失败

所有组件均通过 ``TUI`` 类的实例方法调用，便于测试时注入 mock console。
"""

from __future__ import annotations

from typing import Any, Sequence

from rich.console import Console
from rich.panel import Panel
from rich.theme import Theme

# ---------------------------------------------------------------------------
# 设计令牌 / Design Tokens
# ---------------------------------------------------------------------------

# 主题配色 — skills.sh 风格青色主调 + 语义色
_ITERATE_THEME = Theme({
    # 主色调
    "iterate.primary": "bold cyan",
    "iterate.accent": "magenta",
    # 语义色
    "iterate.success": "green",
    "iterate.error": "bold red",
    "iterate.warning": "yellow",
    "iterate.info": "blue",
    # 中性色
    "iterate.dim": "dim",
    "iterate.bold": "bold",
    "iterate.title": "bold cyan",
    "iterate.subtitle": "dim",
    "iterate.label": "bold",
    "iterate.value": "white",
    "iterate.hint": "dim italic",
})

# 符号系统 — 仿 @clack/prompts
SYM_INTRO = "◆"
SYM_QUESTION = "◇"
SYM_CONNECTOR = "│"
SYM_END = "└"
SYM_SELECTED = "●"
SYM_UNSELECTED = "○"
SYM_CHECKED = "◆"
SYM_UNCHECKED = "◇"
SYM_BULLET = "●"
SYM_SUCCESS = "✓"
SYM_ERROR = "✗"
SYM_WARNING = "⚠"
SYM_ARROW = "→"
SYM_SPINNER = "✻"

# ITERATE 立体 ASCII 横幅 — 仿 skills.sh 顶部 Logo
_ITERATE_BANNER_LINES = (
    "██╗████████╗███████╗██████╗  █████╗ ████████╗███████╗",
    "██║╚══██╔══╝██╔════╝██╔══██╗██╔══██╗╚══██╔══╝██╔════╝",
    "██║   ██║   █████╗  ██████╔╝███████║   ██║   █████╗  ",
    "██║   ██║   ██╔══╝  ██╔══██╗██╔══██║   ██║   ██╔══╝  ",
    "██║   ██║   ███████╗██║  ██║██║  ██║   ██║   ███████╗",
    "╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ╚══════╝",
)


# ---------------------------------------------------------------------------
# TUI 渲染器
# ---------------------------------------------------------------------------


class TUI:
    """统一 TUI 渲染器，封装所有终端输出逻辑.

    所有 CLI 模块应通过此类输出内容，不直接调用 print()。
    测试时可通过 ``TUI(console=mock_console)`` 注入 mock。

    Attributes:
        console: rich Console 实例
        is_interactive: 是否为交互式终端（非管道/重定向）
    """

    def __init__(self, console: Console | None = None) -> None:
        """初始化 TUI 渲染器.

        Args:
            console: 可选的自定义 Console 实例，测试时注入 mock
        """
        if console is not None:
            self.console = console
            self.is_interactive = console.is_terminal
            # 测试时复用注入的 console 输出错误信息
            self._stderr_console = console
        else:
            # force_terminal=None 让 rich 自动检测
            self.console = Console(theme=_ITERATE_THEME, force_terminal=None)
            self.is_interactive = self.console.is_terminal
            # 独立的 stderr console，确保错误信息写入 stderr
            self._stderr_console = Console(
                theme=_ITERATE_THEME, stderr=True, force_terminal=None
            )

    # ------------------------------------------------------------------
    # 基础输出
    # ------------------------------------------------------------------

    def print(self, *args: Any, **kwargs: Any) -> None:
        """透传到 console.print，保持兼容性."""
        self.console.print(*args, **kwargs)

    def empty_line(self) -> None:
        """输出一个空行."""
        self.console.print()

    # ------------------------------------------------------------------
    # 横幅与结构
    # ------------------------------------------------------------------

    def banner(self) -> None:
        """输出 ITERATE 立体 ASCII 横幅 — 仿 skills.sh 顶部 Logo.

        横幅左对齐行首，不居中，与后续列表/步骤的缩进保持一致。
        可通过 ``--no-banner`` 或环境变量 ``ITERATE_NO_BANNER=1`` 禁用。
        """
        self.console.print()
        for line in _ITERATE_BANNER_LINES:
            self.console.print(
                f"[iterate.primary]{line}[/]",
                soft_wrap=True,
            )
        self.console.print()

    def intro(self, title: str, subtitle: str = "") -> None:
        """输出开始横幅 — 仿 @clack/prompts intro().

        格式:
          ◆ Iterate Skill — Onboarding
            项目知识库初始化

        Args:
            title: 主标题
            subtitle: 副标题（可选，dim 灰色显示）
        """
        self.console.print()
        self.console.print(
            f"[iterate.primary]{SYM_INTRO}[/] "
            f"[iterate.title]{title}[/]"
        )
        if subtitle:
            self.console.print(f"  [iterate.subtitle]{subtitle}[/]")
        self.console.print()

    def outro(self, message: str, success: bool = True) -> None:
        """输出结束横幅 — 仿 @clack/prompts outro().

        Args:
            message: 结束消息
            success: 是否为成功结束（绿色 ✓ vs 红色 ✗）
        """
        self.console.print()
        symbol = SYM_SUCCESS if success else SYM_ERROR
        color = "iterate.success" if success else "iterate.error"
        self.console.print(
            f"[iterate.primary]{SYM_INTRO}[/] "
            f"[{color}]{symbol}[/] {message}"
        )
        self.console.print()

    def section(self, title: str) -> None:
        """输出区块标题.

        格式:
          ── 技术栈 / Tech Stack ──

        Args:
            title: 区块标题（通常为中英双语）
        """
        self.console.print()
        self.console.print(f"  [iterate.label]── {title} ──[/]")

    def cancel(self) -> None:
        """输出取消消息."""
        self.console.print()
        self.console.print(
            f"  [iterate.dim]{SYM_END} 已取消 / Cancelled.[/]"
        )
        self.console.print()

    # ------------------------------------------------------------------
    # 信息展示
    # ------------------------------------------------------------------

    def info(self, message: str, indent: int = 2) -> None:
        """输出普通信息行.

        Args:
            message: 消息内容
            indent: 缩进空格数
        """
        prefix = " " * indent
        self.console.print(f"{prefix}{message}")

    def hint(self, message: str, indent: int = 2) -> None:
        """输出提示信息（dim 灰色）.

        Args:
            message: 提示内容
            indent: 缩进空格数
        """
        prefix = " " * indent
        self.console.print(f"{prefix}[iterate.dim]{message}[/]")

    def warning(self, message: str, indent: int = 2) -> None:
        """输出警告信息.

        Args:
            message: 警告内容
            indent: 缩进空格数
        """
        prefix = " " * indent
        self.console.print(
            f"{prefix}[iterate.warning]{SYM_WARNING} {message}[/]"
        )

    def error(self, message: str, indent: int = 0) -> None:
        """输出错误信息到 stderr.

        Args:
            message: 错误内容
            indent: 缩进空格数
        """
        prefix = " " * indent
        self._stderr_console.print(
            f"{prefix}[iterate.error]{SYM_ERROR} {message}[/]",
            soft_wrap=True,
        )

    def success(self, message: str, indent: int = 2) -> None:
        """输出成功信息.

        Args:
            message: 成功内容
            indent: 缩进空格数
        """
        prefix = " " * indent
        self.console.print(
            f"{prefix}[iterate.success]{SYM_SUCCESS} {message}[/]"
        )

    def bullet(self, message: str, indent: int = 2) -> None:
        """输出带圆点的列表项.

        Args:
            message: 列表项内容
            indent: 缩进空格数
        """
        prefix = " " * indent
        self.console.print(
            f"{prefix}[iterate.dim]{SYM_BULLET}[/] {message}"
        )

    def key_value(self, key: str, value: str, indent: int = 2) -> None:
        """输出键值对（key 加粗，value 正常）.

        Args:
            key: 键名
            value: 值
            indent: 缩进空格数
        """
        # 对齐 key 到 20 字符宽度
        padded_key = f"{key}:".ljust(22)
        prefix = " " * indent
        self.console.print(
            f"{prefix}[iterate.label]{padded_key}[/] [iterate.value]{value}[/]"
        )

    # ------------------------------------------------------------------
    # 列表展示
    # ------------------------------------------------------------------

    def numbered_list(
        self,
        items: Sequence[str],
        indent: int = 4,
        markers: Sequence[str] | None = None,
    ) -> None:
        """输出编号列表.

        Args:
            items: 列表项
            indent: 缩进空格数
            markers: 可选的自定义标记（如 ["✓", "", ""]），长度需与 items 一致
        """
        prefix = " " * indent
        for i, item in enumerate(items, 1):
            if markers and i - 1 < len(markers) and markers[i - 1]:
                marker_str = f"[iterate.success]{markers[i - 1]}[/] "
            else:
                marker_str = ""
            self.console.print(
                f"{prefix}[iterate.dim]{i}.[/] {marker_str}{item}"
            )

    def empty_list_placeholder(self, indent: int = 4) -> None:
        """输出空列表占位符."""
        prefix = " " * indent
        self.console.print(f"{prefix}[iterate.dim](空 / empty)[/]")

    # ------------------------------------------------------------------
    # 状态与进度
    # ------------------------------------------------------------------

    def status(self, message: str) -> Any:
        """返回一个 status 上下文管理器，用于耗时操作.

        用法:
            with tui.status("正在扫描项目..."):
                result = scan_project()

        Args:
            message: 状态消息

        Returns:
            rich Console.status 上下文管理器
        """
        return self.console.status(
            f"[iterate.primary]{SYM_SPINNER}[/] {message}",
            spinner="dots",
        )

    def panel(self, content: str, title: str = "", style: str = "") -> None:
        """输出带边框的面板.

        Args:
            content: 面板内容
            title: 面板标题
            style: 边框样式（如 "cyan", "green"）
        """
        border_style = style or "cyan"
        self.console.print(
            Panel(
                content,
                title=f"[iterate.title]{title}[/]" if title else None,
                title_align="left",
                border_style=border_style,
                padding=(0, 1),
            )
        )

    # ------------------------------------------------------------------
    # 交互输入（包装 input_func，添加样式）
    # ------------------------------------------------------------------

    def question(self, message: str) -> str:
        """输出问题标记行（不含输入），返回 prompt 前缀.

        用于在 input_func 调用前打印问题头。
        实际输入仍由调用方通过 input_func 完成。

        格式:
          ◇ 这是一个问题？

        Args:
            message: 问题文本

        Returns:
            无返回值，仅打印问题头
        """
        self.console.print(
            f"  [iterate.primary]{SYM_QUESTION}[/] {message}"
        )

    def prompt_prefix(self) -> str:
        """返回输入行的视觉前缀（连接线）.

        Returns:
            "  └ " 字符串，用于 input_func 的提示文本
        """
        return f"  [iterate.dim]{SYM_END}[/] "


# ---------------------------------------------------------------------------
# 单例实例 — 供整个 CLI 使用
# ---------------------------------------------------------------------------

# 全局 TUI 实例。模块级导入即可使用：
#   from iterate_cli.tui import tui
#   tui.intro("Hello")
#
# 测试时可替换：
#   from iterate_cli import tui as tui_module
#   tui_module.tui = TUI(console=mock_console)
tui = TUI()


def reset_tui() -> None:
    """重置全局 TUI 实例（测试用）.

    测试中如果修改了 ``tui`` 单例，调用此函数恢复默认实例。
    """
    global tui
    tui = TUI()


def set_tui(new_tui: TUI) -> None:
    """替换全局 TUI 实例（测试用）.

    Args:
        new_tui: 新的 TUI 实例
    """
    global tui
    tui = new_tui
