"""Custom readability checks for backend Python code."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DOC_REQUIRED_SECTIONS = ("Args:", "Returns:")
OPTIONAL_EXCEPTION_SECTION = "Raises:"
EXCEPTION_TAGS = {
    "readability-exception: bulk-assignment",
    "readability-exception: long-signature",
}


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    message: str
    level: str = "ERROR"

    def render(self) -> str:
        return f"[{self.level}] {self.path}:{self.line} {self.message}"


def iter_python_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return sorted(root.rglob("*.py"))


def is_public(name: str) -> bool:
    return not name.startswith("_")


def get_source_line(lines: list[str], index: int) -> str:
    if 0 <= index < len(lines):
        return lines[index]
    return ""


def collect_function_violations(path: Path, tree: ast.AST, lines: list[str], max_lines: int) -> list[Violation]:
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not is_public(node.name):
            continue

        doc = ast.get_docstring(node)
        if not doc:
            violations.append(
                Violation(path, node.lineno, "public 函数缺少 docstring。")
            )
        else:
            for section in DOC_REQUIRED_SECTIONS:
                if section not in doc:
                    violations.append(
                        Violation(
                            path,
                            node.lineno,
                            f"public 函数 docstring 缺少 `{section}` 段落。",
                        )
                    )

        end_lineno = getattr(node, "end_lineno", node.lineno)
        func_len = end_lineno - node.lineno + 1
        if func_len <= max_lines:
            continue

        pre_line = get_source_line(lines, node.lineno - 2).strip()
        has_exception = any(tag in pre_line for tag in EXCEPTION_TAGS)
        if not has_exception:
            violations.append(
                Violation(
                    path,
                    node.lineno,
                    f"函数长度 {func_len} 行，超过 {max_lines} 行且未声明可读性例外标签。",
                )
            )

    return violations


def collect_module_violations(path: Path, tree: ast.Module) -> list[Violation]:
    violations: list[Violation] = []
    public_classes = [
        node for node in tree.body if isinstance(node, ast.ClassDef) and is_public(node.name)
    ]
    if len(public_classes) > 1:
        violations.append(
            Violation(
                path,
                public_classes[1].lineno,
                "同一模块包含多个 public class，建议拆分为单一职责。",
                level="WARN",
            )
        )

    public_functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and is_public(node.name)
    ]
    if public_classes and public_functions:
        violations.append(
            Violation(
                path,
                public_functions[0].lineno,
                "同一模块同时包含 public class 与 public function，建议避免混合职责。",
                level="WARN",
            )
        )
    return violations


def analyze_file(path: Path, max_lines: int) -> list[Violation]:
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    try:
        tree = ast.parse(raw, filename=str(path))
    except SyntaxError as exc:
        line = exc.lineno or 1
        return [Violation(path, line, f"语法错误，无法进行可读性检查: {exc.msg}")]

    result = []
    result.extend(collect_function_violations(path, tree, lines, max_lines))
    result.extend(collect_module_violations(path, tree))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Python readability gate.")
    parser.add_argument("--path", default="backend", help="检查目录，默认 backend")
    parser.add_argument("--max-lines", type=int, default=100, help="函数最大行数")
    args = parser.parse_args()

    root = Path(args.path)
    files = list(iter_python_files(root))
    if not files:
        print(f"[INFO] 未发现 Python 文件，跳过检查: {root}")
        return 0

    errors: list[Violation] = []
    warnings: list[Violation] = []
    for file in files:
        for violation in analyze_file(file, args.max_lines):
            if violation.level == "WARN":
                warnings.append(violation)
            else:
                errors.append(violation)

    for warning in warnings:
        print(warning.render())
    for error in errors:
        print(error.render())

    if errors:
        print(f"[FAIL] 可读性检查失败: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1

    print(f"[PASS] 可读性检查通过: {len(files)} file(s), {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

