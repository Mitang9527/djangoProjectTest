# sync-init: skip
"""
API 接口抓包封装
=================

基于 Playwright 的 ``page.on("response")`` 监听，自动收集 XHR/Fetch 调用，并导出：

- Markdown 文档 (``.md``)
- Excel 表格 (``.xlsx``)
- Postman Collection v2.1 JSON (``.json``)

使用场景：

1. 一行起浏览器人工点，关闭自动导出（最常用）：

    .. code-block:: python

       from extensions.web_automation.playwright import APICaptureSession
       with APICaptureSession(
           target_url="https://stage.example.com/login",
           username="admin",
           password="a123456",
       ) as sess:
           sess.wait_for_close()
           sess.export_all(output_dir="data/api_captures/")

2. 与 PlaywrightClient 结合使用（复用已有浏览器会话，不另起）：

    .. code-block:: python

       from extensions.web_automation.playwright import PlaywrightClient, APICaptureSession
       client = PlaywrightClient()
       sess = APICaptureSession.attach(client)
       client.goto("https://example.com")
       ...  # 你的操作
       sess.export_markdown("out.md")
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from loguru import logger

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    _HAS_OPENPYXL = True
except ImportError:  # pragma: no cover
    _HAS_OPENPYXL = False

from .client import PlaywrightClient
from .exceptions import CaptureError, ExportError, ConfigError


# ============================================================
# 默认配置
# ============================================================


CAPTURE_RESOURCE_TYPE_DEFAULT = {"xhr", "fetch"}

IGNORE_KEYWORDS_DEFAULT = [
    ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".eot", ".map",
    "analytics", "tracking", "beacon", "sentry", "datadog", "logging",
]

LOGIN_SELECTORS_DEFAULT: List[Tuple[str, str]] = [
    ("input[name='username']", "input[name='password']"),
    ("input[name='account']", "input[name='password']"),
    ("input[type='text']", "input[type='password']"),
    ("input[id*='user']", "input[id*='pass']"),
    ("input[id*='account']", "input[id*='pass']"),
    ("input[placeholder*='账']", "input[placeholder*='密']"),
    ("input[placeholder*='user']", "input[placeholder*='pass']"),
    ("input[placeholder*='邮箱']", "input[placeholder*='密码']"),
]


# ============================================================
# 数据结构
# ============================================================


@dataclass
class CapturedAPI:
    method: str
    url: str
    path: str
    status: int
    host: str
    query_params: Dict[str, List[str]] = field(default_factory=dict)
    request_body: str = ""
    response_body: str = ""
    count: int = 1
    first_time: str = field(default_factory=lambda: time.strftime("%H:%M:%S"))
    last_status: int = 0

    @property
    def dedup_key(self) -> str:
        return f"{self.method} {self.path}"

    def update(self, status: int, request_body: str = "", response_body: str = "") -> None:
        self.count += 1
        self.last_status = status
        self.status = status
        # 覆盖为首次以外最新的一次 body，避免旧 body 误导
        if request_body:
            self.request_body = request_body
        if response_body:
            self.response_body = response_body


# ============================================================
# 主类
# ============================================================


class APICaptureSession:
    """
    可复用的 API 抓包会话。

    Parameters
    ----------
    target_url : str, optional
        打开的起始 URL（一般是登录页）。若为 None，需要调用方自行 goto。
    username : str, optional
        用于自动填充登录表单。
    password : str, optional
        用于自动填充登录表单。
    browser : str
        传给 :class:`PlaywrightClient`，默认 ``chromium``。
    headless : bool
        默认 ``False``（人工点菜单时需要可视化）。
    output_dir : str, optional
        输出目录，默认 ``data/api_captures/``。
    resource_types : set[str]
        捕获的资源类型集合，默认仅 XHR + Fetch。
    ignore_keywords : list[str]
        忽略 URL 关键词（大小写不敏感）。
    capture_request_body : bool
        是否记录请求体。默认 True。
    capture_response_body : bool
        是否记录响应体。默认 True。
    max_response_bytes : int
        超过该字节数的响应 body 不记录，避免超大返回卡死。默认 ``50 * 1024``。
    auto_login : bool
        是否尝试自动填充登录表单。
    login_selectors : list[(user_sel, pass_sel)]
        自动登录时按顺序尝试的选择器。
    viewport : (int, int)
        视口大小，默认 (1600, 900)。
    extra_launch_options : dict
        透传给 PlaywrightClient。
    """

    # --------------------------------------------------------
    # 构造 & 生命周期
    # --------------------------------------------------------

    def __init__(
        self,
        target_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        *,
        browser: str = "chromium",
        headless: bool = False,
        output_dir: str = "data/api_captures",
        resource_types: Optional[Iterable[str]] = None,
        ignore_keywords: Optional[List[str]] = None,
        capture_request_body: bool = True,
        capture_response_body: bool = True,
        max_response_bytes: int = 50 * 1024,
        auto_login: bool = True,
        login_selectors: Optional[List[Tuple[str, str]]] = None,
        viewport: Tuple[int, int] = (1600, 900),
        extra_launch_options: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._target_url = target_url
        self._username = username
        self._password = password
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._resource_types: set[str] = set(resource_types) if resource_types else CAPTURE_RESOURCE_TYPE_DEFAULT
        self._ignore_keywords: List[str] = list(ignore_keywords) if ignore_keywords else IGNORE_KEYWORDS_DEFAULT
        self._capture_request_body = capture_request_body
        self._capture_response_body = capture_response_body
        self._max_response_bytes = max_response_bytes
        self._auto_login = auto_login and bool(username and password)
        self._login_selectors: List[Tuple[str, str]] = list(login_selectors) if login_selectors else LOGIN_SELECTORS_DEFAULT

        self._client_owned: bool = False
        self._client: Optional[PlaywrightClient] = None
        self._extra_launch_options = dict(extra_launch_options or {})
        self._extra_launch_options.setdefault("browser", browser)
        self._extra_launch_options.setdefault("headless", headless)
        self._extra_launch_options.setdefault("viewport", viewport)

        # 存储 API 记录（dict 去重，key = method + path）
        self._records: Dict[str, CapturedAPI] = {}

        # 可选：用户自定义钩子
        self.on_captured_hook: Optional[Callable[[CapturedAPI], None]] = None

    # --------------------------------------------------------
    # 对外：attach 到已有 PlaywrightClient
    # --------------------------------------------------------

    @classmethod
    def attach(cls, client: PlaywrightClient, **kwargs: Any) -> "APICaptureSession":
        """附加到已有的 PlaywrightClient 实例上，不另起浏览器。"""
        sess = cls(**kwargs)
        sess._client = client
        sess._client_owned = False
        sess._register_listener()
        return sess

    # --------------------------------------------------------
    # 上下文管理
    # --------------------------------------------------------

    def __enter__(self) -> "APICaptureSession":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.stop()
        finally:
            # 如果异常导致也顺手关一下自己的 client
            if self._client_owned and self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass

    def start(self) -> "APICaptureSession":
        """显式启动（若不是通过 with）。"""
        if self._client is None:
            self._client = PlaywrightClient(**self._extra_launch_options)
            self._client_owned = True
        self._register_listener()

        if self._target_url:
            self._client.goto(self._target_url)
            if self._auto_login:
                try:
                    self.try_auto_login()
                except Exception as e:
                    logger.warning(f"[APICapture] 自动登录失败，请手动登录：{e}")
        return self

    def stop(self) -> None:
        """停止监听（不自动关浏览器，除非是自己启动的）。"""
        if self._client_owned and self._client is not None:
            self._client.close()
            self._client = None
        logger.info(f"[APICapture] 停止监听，共捕获 {len(self._records)} 个去重接口")

    # --------------------------------------------------------
    # 内部：注册响应监听
    # --------------------------------------------------------

    def _register_listener(self) -> None:
        if self._client is None:
            raise CaptureError("PlaywrightClient 尚未就绪")
        # 只注册一次
        if not getattr(self, "_listener_registered", False):
            self._client.page.on("response", self._on_response)
            self._listener_registered = True

    def _should_ignore(self, url: str) -> bool:
        """
        判断 URL 是否应被忽略。

        匹配规则（避免裸子串误伤）：
        - 以 ``.`` 开头的关键字（静态资源后缀，如 ``.js`` ``.map``）：任意路径段以该
          后缀结尾即忽略；
        - 其它关键字（如 ``analytics`` ``logging``）：仅当它是**完整的路径段**或
          **query 参数名**时才忽略，避免 ``log`` 误伤 ``login`` / ``catalog`` /
          ``blog`` 等正常接口。
        """
        low = url.lower()
        parsed = urlparse(low)
        segments = [seg for seg in parsed.path.split("/") if seg]
        tokens = set(segments)
        for k in parse_qs(parsed.query):
            tokens.add(k)
        for kw in self._ignore_keywords:
            kw = kw.lower()
            if kw.startswith("."):
                if any(seg.endswith(kw) for seg in segments):
                    return True
            elif kw in tokens:
                return True
        return False

    def _on_response(self, response: Any) -> None:
        try:
            request = response.request
            res_type = (request.resource_type or "").lower()

            if res_type not in self._resource_types:
                return

            url = request.url or ""
            if not url or self._should_ignore(url):
                return

            method = (request.method or "GET").upper()
            status = int(response.status or 0)

            parsed = urlparse(url)
            path = parsed.path or "/"
            host = parsed.hostname or ""
            query_params = parse_qs(parsed.query)

            request_body: str = ""
            if self._capture_request_body:
                try:
                    raw = request.post_data
                    if raw:
                        try:
                            request_body = json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
                        except Exception:
                            request_body = str(raw)[:4000]
                except Exception:
                    pass

            response_body: str = ""
            if self._capture_response_body:
                try:
                    body = response.body()
                    if body and len(body) <= self._max_response_bytes:
                        text = body.decode("utf-8", errors="replace")
                        try:
                            response_body = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
                        except Exception:
                            response_body = text[:2000]
                except Exception:
                    pass

            dedup_key = f"{method} {path}"
            if dedup_key not in self._records:
                self._records[dedup_key] = CapturedAPI(
                    method=method,
                    url=url,
                    path=path,
                    status=status,
                    host=host,
                    query_params=query_params,
                    request_body=request_body,
                    response_body=response_body,
                    last_status=status,
                )
                if callable(self.on_captured_hook):
                    try:
                        self.on_captured_hook(self._records[dedup_key])
                    except Exception:
                        pass
            else:
                self._records[dedup_key].update(
                    status=status,
                    request_body=request_body,
                    response_body=response_body,
                )
        except Exception as e:
            # 任何捕获异常都不影响浏览器主进程
            logger.debug(f"[APICapture] 处理 response 时出错（忽略）：{e}")

    # --------------------------------------------------------
    # 自动登录
    # --------------------------------------------------------

    def try_auto_login(self, timeout_ms: int = 10_000) -> bool:
        """按 selector 列表尝试找到用户名/密码输入框并自动填充。"""
        if not self._client:
            raise CaptureError("PlaywrightClient 尚未就绪")
        if not self._username or not self._password:
            raise ConfigError("未提供 username/password，无法自动登录")

        page = self._client.page
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            # networkidle 某些站点触发不到，退而用 domcontentloaded
            try:
                page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            except Exception:
                pass

        for user_sel, pass_sel in self._login_selectors:
            try:
                user_count = page.locator(user_sel).count()
                pass_count = page.locator(pass_sel).count()
                if user_count > 0 and pass_count > 0:
                    page.locator(user_sel).first.fill(self._username)
                    page.locator(pass_sel).first.fill(self._password)
                    logger.success(
                        f"[APICapture] 已自动填充账号密码："
                        f"user=({user_sel}), pass=({pass_sel})"
                    )
                    return True
            except Exception:
                continue

        logger.warning("[APICapture] 未能自动识别登录表单，请手动输入账号密码")
        logger.warning(f"  账号：{self._username}")
        logger.warning(f"  密码：{'*' * len(self._password)}")
        return False

    # --------------------------------------------------------
    # 手动菜单遍历
    # --------------------------------------------------------

    def auto_traverse(
        self,
        menu_selectors: Optional[List[str]] = None,
        delay_ms: int = 1200,
        max_items: int = 200,
    ) -> int:
        """
        自动点击页面上可见的菜单项，触发接口调用。

        Parameters
        ----------
        menu_selectors : list[str]
            按顺序尝试的选择器。优先使用框架专用选择器。
        delay_ms : int
            每次点击后等待的毫秒数（等 XHR 返回）。
        max_items : int
            最多点击次数，防死循环。

        Returns
        -------
        int
            实际点击的菜单数。
        """
        if not self._client:
            raise CaptureError("PlaywrightClient 尚未就绪")

        selectors = list(menu_selectors or [
            "el-menu-item",
            "el-sub-menu__title",
            "a[role='menuitem']",
            "nav a",
            "aside a",
            ".menu a",
            ".sidebar a",
            "a",
        ])

        page = self._client.page
        visited: set[str] = set()
        clicked = 0

        for sel in selectors:
            try:
                elements = page.locator(sel).all()
                for el in elements:
                    if clicked >= max_items:
                        return clicked
                    try:
                        text = (el.inner_text() or "").strip()
                        href = (el.get_attribute("href") or "").strip()
                        key = f"{sel}|{text}|{href}"
                        if not text and not href:
                            continue
                        if key in visited:
                            continue
                        visited.add(key)

                        # 只点可见元素
                        if not el.is_visible():
                            continue

                        # 滚动到可视区域
                        try:
                            el.scroll_into_view_if_needed()
                        except Exception:
                            pass

                        # 使用 try-click 避免阻塞
                        try:
                            el.click(timeout=3000, no_wait_after=False)
                            clicked += 1
                            page.wait_for_timeout(delay_ms)
                        except Exception:
                            continue
                    except Exception:
                        continue
            except Exception:
                continue

        logger.info(f"[APICapture] 自动遍历点击 {clicked} 个菜单项")
        return clicked

    # --------------------------------------------------------
    # 阻塞等待（人工操作模式）
    # --------------------------------------------------------

    def wait_for_close(self, poll_ms: int = 1000) -> "APICaptureSession":
        """阻塞轮询直到浏览器被手动关闭（headless=False 时常用）。"""
        if not self._client:
            raise CaptureError("PlaywrightClient 尚未就绪")
        print("\n" + "=" * 60)
        print("📝 使用说明：")
        print("  1. 确认已登录后台")
        print("  2. 手动依次点击左侧菜单、查询、编辑、分页、弹窗等功能")
        print("  3. 每点击一个功能，接口会被自动捕获")
        print(f"  4. 当前已捕获：{len(self._records)} 个去重接口")
        print("  5. 全部操作完毕后，直接关闭浏览器窗口")
        print("     程序会自动导出：Markdown + Excel + Postman JSON 三份文件")
        print("=" * 60 + "\n")

        while self._client.is_alive:
            try:
                time.sleep(poll_ms / 1000.0)
            except KeyboardInterrupt:
                logger.info("[APICapture] 收到 Ctrl+C，提前结束")
                break
        return self

    # --------------------------------------------------------
    # 对外：取数接口
    # --------------------------------------------------------

    @property
    def captured_count(self) -> int:
        return len(self._records)

    def captured_apis(self) -> List[CapturedAPI]:
        return sorted(
            self._records.values(),
            key=lambda r: (r.method, r.path),
        )

    def clear_records(self) -> None:
        self._records.clear()

    # --------------------------------------------------------
    # 导出：Markdown
    # --------------------------------------------------------

    def export_markdown(self, filename: str = "接口清单.md") -> str:
        sorted_records = self.captured_apis()
        lines: List[str] = []
        lines.append("# 后台接口抓取清单")
        lines.append("")
        lines.append(f"- **抓取时间**：{time.strftime('%Y-%m-%d %H:%M:%S')}")
        if self._target_url:
            lines.append(f"- **目标站点**：{self._target_url}")
        lines.append(f"- **接口总数**：{len(sorted_records)} 个（已去重）")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## 接口速览表")
        lines.append("")
        lines.append("| 序号 | 方法 | 接口路径 | 状态码 | 调用次数 |")
        lines.append("| :---: | :---: | ---- | :---: | :---: |")

        for idx, r in enumerate(sorted_records, 1):
            lines.append(
                f"| {idx} | {r.method} | `{r.path}` | {r.status} | {r.count} |"
            )

        lines.extend(["", "---", "", "## 接口详情", ""])

        for idx, r in enumerate(sorted_records, 1):
            lines.extend([
                f"### {idx}. [{r.method}] {r.path}",
                "",
                f"- **完整 URL**：`{r.url}`",
                f"- **响应状态码**：{r.status}",
                f"- **调用次数**：{r.count}",
                f"- **首次捕获时间**：{r.first_time}",
                "",
            ])
            if r.query_params:
                lines.extend(["**查询参数（Query）**：", "", "```json"])
                lines.append(json.dumps(r.query_params, ensure_ascii=False, indent=2))
                lines.extend(["```", ""])
            if r.request_body:
                lines.extend(["**请求体（Request Body）**：", "", "```json"])
                lines.append(r.request_body)
                lines.extend(["```", ""])
            if r.response_body:
                lines.extend(["**响应体（Response Body）**：", "", "```json"])
                lines.append(r.response_body)
                lines.extend(["```", ""])
            lines.extend(["---", ""])

        out_path = self._output_dir / filename
        try:
            out_path.write_text("\n".join(lines), encoding="utf-8")
        except Exception as e:
            raise ExportError(f"导出 Markdown 失败：{e}") from e
        logger.success(f"[APICapture] Markdown 已输出：{out_path.resolve()}")
        return str(out_path.resolve())

    # --------------------------------------------------------
    # 导出：Excel
    # --------------------------------------------------------

    def export_excel(self, filename: str = "接口清单.xlsx") -> str:
        if not _HAS_OPENPYXL:
            raise ExportError(
                "未安装 openpyxl，无法导出 Excel。请执行：pip install openpyxl"
            )
        sorted_records = self.captured_apis()

        wb = Workbook()
        header_font = Font(name="微软雅黑", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
        thin_border = Border(
            left=Side(style="thin"),
            right=Side(style="thin"),
            top=Side(style="thin"),
            bottom=Side(style="thin"),
        )
        body_align = Alignment(vertical="center", wrap_text=True)
        method_colors = {
            "GET": "92D050",
            "POST": "FFC000",
            "PUT": "00B0F0",
            "DELETE": "FF0000",
            "PATCH": "FF9900",
        }

        # ========== Sheet1: 接口概览 ==========
        ws1 = wb.active
        ws1.title = "接口概览"
        headers = ["序号", "请求方法", "接口路径", "Host", "完整URL", "状态码", "调用次数", "首次捕获时间"]
        for col, h in enumerate(headers, 1):
            cell = ws1.cell(row=1, column=col, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align
            cell.border = thin_border

        for idx, r in enumerate(sorted_records, 1):
            row = idx + 1
            values = [idx, r.method, r.path, r.host, r.url, r.status, r.count, r.first_time]
            for col, val in enumerate(values, 1):
                cell = ws1.cell(row=row, column=col, value=val)
                cell.alignment = body_align
                cell.border = thin_border
                if col == 2 and val in method_colors:
                    cell.fill = PatternFill(start_color=method_colors[val], end_color=method_colors[val], fill_type="solid")
                    cell.font = Font(bold=True)
                if col == 6 and val and val != 200:
                    cell.font = Font(color="FF0000", bold=True)

        widths = [6, 10, 40, 20, 60, 8, 10, 14]
        for i, w in enumerate(widths, 1):
            ws1.column_dimensions[get_column_letter(i)].width = w
        ws1.freeze_panes = "A2"

        # ========== Sheet2: 接口详情 ==========
        ws2 = wb.create_sheet("接口详情")
        detail_headers = [
            "序号", "请求方法", "接口路径", "完整URL", "状态码", "调用次数",
            "Query参数", "请求Body", "响应内容",
        ]
        for col, h in enumerate(detail_headers, 1):
            cell = ws2.cell(row=1, column=col, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align
            cell.border = thin_border

        for idx, r in enumerate(sorted_records, 1):
            row = idx + 1
            query_str = json.dumps(r.query_params, ensure_ascii=False, indent=2) if r.query_params else ""
            values = [
                idx, r.method, r.path, r.url, r.status, r.count,
                query_str, r.request_body, r.response_body,
            ]
            for col, val in enumerate(values, 1):
                cell = ws2.cell(row=row, column=col, value=val)
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                cell.border = thin_border

        detail_widths = [6, 10, 35, 50, 8, 10, 30, 40, 50]
        for i, w in enumerate(detail_widths, 1):
            ws2.column_dimensions[get_column_letter(i)].width = w
        ws2.freeze_panes = "A2"

        out_path = self._output_dir / filename
        try:
            wb.save(out_path)
        except Exception as e:
            raise ExportError(f"导出 Excel 失败：{e}") from e
        logger.success(f"[APICapture] Excel 已输出：{out_path.resolve()}")
        return str(out_path.resolve())

    # --------------------------------------------------------
    # 导出：Postman Collection v2.1 JSON
    # --------------------------------------------------------

    def export_postman(
        self,
        filename: str = "postman_collection.json",
        collection_name: str = "抓取接口集合",
    ) -> str:
        items: List[Dict[str, Any]] = []
        for r in self.captured_apis():
            query_list: List[Dict[str, str]] = []
            if r.query_params:
                for k, v in r.query_params.items():
                    query_list.append({"key": k, "value": v[0] if v else ""})

            req_item: Dict[str, Any] = {
                "name": f"[{r.method}] {r.path}",
                "request": {
                    "method": r.method,
                    "url": {
                        "raw": r.url,
                        "query": query_list,
                    },
                },
            }
            if r.request_body:
                req_item["request"]["body"] = {
                    "mode": "raw",
                    "raw": r.request_body,
                    "options": {"raw": {"language": "json"}},
                }
            items.append(req_item)

        collection: Dict[str, Any] = {
            "info": {
                "name": collection_name,
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            },
            "item": items,
        }

        out_path = self._output_dir / filename
        try:
            out_path.write_text(
                json.dumps(collection, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            raise ExportError(f"导出 Postman JSON 失败：{e}") from e
        logger.success(f"[APICapture] Postman 已输出：{out_path.resolve()}")
        return str(out_path.resolve())

    # --------------------------------------------------------
    # 一键导出三份
    # --------------------------------------------------------

    def export_all(
        self,
        output_dir: Optional[str] = None,
        prefix: str = "",
    ) -> Dict[str, str]:
        """
        一键导出 Markdown / Excel / Postman 三份文件。

        Returns
        -------
        dict
            ``{"markdown": path, "excel": path, "postman": path}`` 绝对路径。
        """
        if output_dir:
            self._output_dir = Path(output_dir)
            self._output_dir.mkdir(parents=True, exist_ok=True)

        ts = time.strftime("%Y%m%d_%H%M%S")
        prefix = prefix or ("capture_" + ts)
        if prefix and not prefix.endswith("_"):
            prefix += "_"

        md_path = self.export_markdown(f"{prefix}接口清单.md")
        excel_path = self.export_excel(f"{prefix}接口清单.xlsx")
        postman_path = self.export_postman(f"{prefix}postman_collection.json")
        print("\n" + "=" * 60)
        print(f"✅ 抓取完成，共捕获 {len(self._records)} 个不重复接口")
        print("-" * 60)
        print(f"📄 Markdown : {md_path}")
        print(f"📊 Excel    : {excel_path}")
        print(f"📮 Postman  : {postman_path}")
        print("=" * 60)
        return {
            "markdown": md_path,
            "excel": excel_path,
            "postman": postman_path,
        }


__all__ = [
    "APICaptureSession",
    "CapturedAPI",
    "CAPTURE_RESOURCE_TYPE_DEFAULT",
    "IGNORE_KEYWORDS_DEFAULT",
    "LOGIN_SELECTORS_DEFAULT",
]
