#!/usr/bin/env python3
"""Revisão automática de arquivos .py alterados (uso em pipeline pós-merge).

Passos:
  1. Lista os .py alterados entre BASE_SHA e HEAD_SHA.
  2. Roda ruff (boas práticas), mypy (tipos) e bandit (segurança).
  3. Compara a API pública (funções, classes, parâmetros) com a versão
     anterior, para sinalizar possíveis quebras de compatibilidade.
  4. Gera o relatório em Markdown (REPORT_PATH).

Variáveis de ambiente:
  BASE_SHA        commit anterior (vazio ou zeros => usa HEAD~1)
  HEAD_SHA        commit analisado (padrão: HEAD)
  REPORT_PATH     arquivo de saída (padrão: review_report.md)
  FAIL_ON_ERRORS  "true" para falhar o job quando houver erros (padrão: false)

Limitação: a checagem de compatibilidade é heurística (AST). Não detecta
*args/**kwargs nem mudanças de comportamento. Use-a como alerta, não como
prova.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

REPORT_PATH = Path(os.environ.get("REPORT_PATH", "review_report.md"))
FAIL_ON_ERRORS = os.environ.get("FAIL_ON_ERRORS", "false").lower() == "true"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # árvore vazia do git
MAX_ROWS = 200  # linhas por seção
MAX_BODY = 60_000  # limite de tamanho de comentário no GitHub

MYPY_RE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+): (?P<sev>error|note|warning): (?P<msg>.*)$"
)


@dataclass
class Finding:
    tool: str
    file: str
    line: int
    severity: str  # error | warning | info
    message: str


@dataclass
class Breaking:
    file: str
    message: str
    usages: list[str] = field(default_factory=list)


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, 127, "", f"comando não encontrado: {cmd[0]}")


def rel(path: str) -> str:
    try:
        return os.path.relpath(path)
    except ValueError:
        return path


# ---------------------------------------------------------------- git / arquivos


def resolve_range() -> tuple[str, str]:
    head = os.environ.get("HEAD_SHA") or "HEAD"
    base = os.environ.get("BASE_SHA", "")
    if not base or set(base) == {"0"}:  # primeiro push da branch
        base = f"{head}~1"
    if run(["git", "rev-parse", "--verify", "-q", base]).returncode != 0:
        base = EMPTY_TREE  # commit raiz: tudo é novo
    return base, head


def changed_python_files(base: str, head: str) -> tuple[list[str], list[str]]:
    out = run(["git", "diff", "--name-status", "--diff-filter=ACMRD", base, head, "--", "*.py"])
    if out.returncode != 0:
        raise RuntimeError(f"git diff falhou: {out.stderr.strip()}")
    existing: list[str] = []
    removed: list[str] = []
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("D"):
            removed.append(parts[1])
        elif status.startswith("R"):  # renomeado: o caminho antigo some
            removed.append(parts[1])
            existing.append(parts[2])
        else:
            existing.append(parts[1])
    return [p for p in existing if Path(p).exists()], removed


def show(rev: str, path: str) -> str | None:
    res = run(["git", "show", f"{rev}:{path}"])
    return res.stdout if res.returncode == 0 else None


def references(name: str) -> list[str]:
    res = run(["git", "grep", "-n", "-w", "-e", name, "--", "*.py"])
    return res.stdout.splitlines()[:5] if res.returncode == 0 else []


# ---------------------------------------------------------------- ferramentas


def run_ruff(files: list[str]) -> list[Finding]:
    if not files:
        return []
    res = run(["ruff", "check", "--no-cache", "--output-format", "json", *files])
    try:
        data = json.loads(res.stdout or "[]")
    except json.JSONDecodeError:
        return [Finding("ruff", "-", 0, "error", res.stderr.strip() or "saída inválida")]
    return [
        Finding(
            "ruff",
            rel(d["filename"]),
            d["location"]["row"],
            "warning",
            f"{d['code']} {d['message']}",
        )
        for d in data
    ]


def run_mypy(files: list[str]) -> list[Finding]:
    if not files:
        return []
    res = run(["mypy", "--ignore-missing-imports", "--no-incremental", "--show-error-codes", *files])
    findings: list[Finding] = []
    for line in res.stdout.splitlines():
        m = MYPY_RE.match(line)
        if m and m["sev"] == "error":
            findings.append(Finding("mypy", rel(m["file"]), int(m["line"]), "error", m["msg"]))
    return findings


def run_bandit(files: list[str]) -> list[Finding]:
    if not files:
        return []
    res = run(["bandit", "-q", "-f", "json", *files])
    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError:
        return []
    sev_map = {"HIGH": "error", "MEDIUM": "warning", "LOW": "info"}
    return [
        Finding(
            "bandit",
            rel(r["filename"]),
            r["line_number"],
            sev_map.get(r["issue_severity"], "info"),
            f"{r['test_id']} {r['issue_text']}",
        )
        for r in data.get("results", [])
    ]


# ---------------------------------------------------------------- compatibilidade


def params_of(args: ast.arguments) -> dict[str, bool]:
    """Nome do parâmetro -> é obrigatório? (ignora self/cls)."""
    params: dict[str, bool] = {}
    positional = args.posonlyargs + args.args
    first_default = len(positional) - len(args.defaults)
    for i, arg in enumerate(positional):
        if arg.arg in ("self", "cls"):
            continue
        params[arg.arg] = i < first_default
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        params[arg.arg] = default is None
    return params


def public_api(source: str) -> dict[str, dict[str, dict[str, bool]]]:
    api: dict[str, dict[str, dict[str, bool]]] = {}
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            api[node.name] = {"params": params_of(node.args)}
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            init = next(
                (
                    n
                    for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "__init__"
                ),
                None,
            )
            api[node.name] = {"params": params_of(init.args) if init else {}}
    return api


def compat_check(base: str, files: list[str], removed: list[str]) -> list[Breaking]:
    problems: list[Breaking] = []
    for path in files + removed:
        old_src = show(base, path)
        if old_src is None:
            continue  # arquivo novo: nada a comparar
        new_src = Path(path).read_text(encoding="utf-8") if Path(path).exists() else None
        try:
            old_api = public_api(old_src)
            new_api = public_api(new_src) if new_src is not None else {}
        except SyntaxError as exc:
            problems.append(Breaking(path, f"não foi possível analisar a API (sintaxe: {exc.msg})"))
            continue

        for name, old_sym in old_api.items():
            new_sym = new_api.get(name)
            if new_sym is None:
                problems.append(Breaking(path, f"`{name}` removido (era público)", references(name)))
                continue
            old_params = old_sym["params"]
            new_params = new_sym["params"]
            for p in old_params:
                if p not in new_params:
                    problems.append(Breaking(path, f"`{name}`: parâmetro `{p}` removido"))
            for p, required in new_params.items():
                if required and (p not in old_params or not old_params[p]):
                    motivo = (
                        "novo parâmetro obrigatório"
                        if p not in old_params
                        else "parâmetro passou a ser obrigatório"
                    )
                    problems.append(Breaking(path, f"`{name}`: {motivo} `{p}`"))
    return problems


# ---------------------------------------------------------------- relatório


def esc(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def table(findings: list[Finding]) -> list[str]:
    rows = ["| Arquivo | Linha | Severidade | Mensagem |", "|---|---|---|---|"]
    for f in findings[:MAX_ROWS]:
        rows.append(f"| `{f.file}` | {f.line} | {f.severity} | {esc(f.message)} |")
    if len(findings) > MAX_ROWS:
        rows.append(f"| … | | | mais {len(findings) - MAX_ROWS} ocorrências omitidas |")
    return rows + [""]


def render(
    base: str,
    head: str,
    files: list[str],
    removed: list[str],
    findings: list[Finding],
    breaking: list[Breaking],
) -> str:
    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]
    out = [
        "# 🔍 Revisão automática de código Python",
        "",
        f"- **Commit analisado:** `{head[:10]}`",
        f"- **Comparado com:** `{base[:10]}`",
        f"- **Arquivos .py analisados:** {len(files)}",
        f"- **Arquivos .py removidos:** {len(removed)}",
        "",
        "## Resumo",
        "",
        f"- Erros: **{len(errors)}**",
        f"- Avisos: **{len(warnings)}**",
        f"- Possíveis quebras de compatibilidade: **{len(breaking)}**",
        "",
    ]

    if breaking:
        out += ["## ⚠️ Possíveis quebras de compatibilidade", ""]
        for b in breaking:
            out.append(f"- `{b.file}`: {b.message}")
            for usage in b.usages:
                out.append(f"  - ainda referenciado em `{usage}`")
        out.append("")
    else:
        out += ["## Compatibilidade", "", "Nenhuma quebra de API pública detectada. ✅", ""]

    sections = [("mypy", "Tipagem (mypy)"), ("ruff", "Boas práticas (ruff)"), ("bandit", "Segurança (bandit)")]
    for tool, title in sections:
        items = sorted((f for f in findings if f.tool == tool), key=lambda f: (f.file, f.line))
        out += [f"## {title}", ""]
        out += table(items) if items else ["Nenhum problema encontrado. ✅", ""]

    out += [
        "---",
        "_Revisão automática (ruff, mypy, bandit e checagem de API). "
        "Não substitui a revisão humana._",
    ]
    return "\n".join(out)


# ---------------------------------------------------------------- main


def main() -> int:
    base, head = resolve_range()
    files, removed = changed_python_files(base, head)
    print(f"Comparando {base[:10]} -> {head[:10]}: {len(files)} alterado(s), {len(removed)} removido(s)")

    if not files and not removed:
        REPORT_PATH.write_text(
            "# 🔍 Revisão automática\n\nNenhum arquivo `.py` foi alterado neste commit. ✅\n",
            encoding="utf-8",
        )
        return 0

    findings = run_ruff(files) + run_mypy(files) + run_bandit(files)
    breaking = compat_check(base, files, removed)
    report = render(base, head, files, removed, findings, breaking)
    if len(report) > MAX_BODY:
        report = report[:MAX_BODY] + "\n\n_Relatório truncado (limite do GitHub)._\n"
    REPORT_PATH.write_text(report, encoding="utf-8")

    errors = sum(f.severity == "error" for f in findings) + len(breaking)
    print(f"Relatório gravado em {REPORT_PATH} | erros/alertas graves: {errors}")
    return 1 if FAIL_ON_ERRORS and errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
