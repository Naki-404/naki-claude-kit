# Security model · Модель безопасности

**English** · [Русский](#русский)

## What runs

| Component | What it does | What it never does |
|---|---|---|
| `hooks/kit_hooks.py` | Reads one hook event from stdin and prints at most one JSON decision. Keeps a per-session list of edited paths in `state/`, deleted at the end of each turn | Network access, logging commands or file contents |
| `mcp/kit_mcp.py` | Answers JSON-RPC over stdio: hashes protected files, counts dataset fields, lists results, reads small text files inside configured results folders, runs `git status/log/rev-parse/rev-list` | Writing files, returning dataset records, reading outside configured folders (path traversal is rejected) |
| `tools/codemap.py` | Builds the Code Map from source files (Python `ast`, a built-in TypeScript/JavaScript scanner) into `<repo>/.codemap/`, excluded from git, and serves it read-only over stdio MCP. Re-parses only changed files | Reading data or secret files (only source code extensions), network access, running the code it maps |
| `install.py` | Copies files into `~/.claude` and the project, merges JSON settings, backs up every file it changes | Touching hooks or settings it did not create |

External programs are started with fixed argument lists and without a shell: `git`, `nvidia-smi`, the checkers named
in `kit.json` (only if the executable exists inside the project) and a background Code Map rebuild.

## Limits

The hooks catch common mistakes; they are not a sandbox. A determined command can avoid pattern matching, for example
by building a path at runtime. Keep Claude Code's own permission prompts on. When a hook fails internally it lets
the action through, so a broken config never blocks work; run the tests after editing `kit.json`.

## Reporting

Please report security problems privately to the repository owner rather than in a public issue.

---

## Русский

### Что запускается

| Компонент | Что делает | Чего не делает никогда |
|---|---|---|
| `hooks/kit_hooks.py` | Читает одно событие хука из stdin и печатает не больше одного JSON-решения. Хранит список изменённых за сессию файлов в `state/` и удаляет его в конце ответа | Не ходит в сеть, не записывает команды и содержимое файлов |
| `mcp/kit_mcp.py` | Отвечает по JSON-RPC через stdio: считает хеши защищённых файлов и поля датасетов, показывает результаты, читает небольшие текстовые файлы в настроенных папках, вызывает `git status/log/rev-parse/rev-list` | Не пишет файлы, не отдаёт записи датасетов, не читает за пределами настроенных папок |
| `tools/codemap.py` | Строит карту кода по исходникам (Python через `ast`, встроенный сканер TypeScript/JavaScript) в `<repo>/.codemap/`, исключённую из git, и отдаёт её только на чтение по MCP. Разбирает только изменённые файлы | Не читает данные и секреты (только файлы исходного кода), не ходит в сеть, не запускает разбираемый код |
| `install.py` | Копирует файлы в `~/.claude` и проект, сливает JSON-настройки, делает копию каждого изменяемого файла | Не трогает чужие хуки и настройки |

Внешние программы запускаются с фиксированными аргументами и без оболочки: `git`, `nvidia-smi`, проверки из
`kit.json` (только если исполняемый файл лежит внутри проекта) и фоновое обновление карты кода.

### Ограничения

Хуки ловят типичные ошибки, но это не песочница: намеренно составленная команда может обойти шаблоны. Не отключайте
собственные запросы разрешений Claude Code. Если хук сам падает, действие проходит, чтобы сломанная настройка не
блокировала работу; после правки `kit.json` запускайте тесты.

### Сообщить о проблеме

О проблемах безопасности пишите владельцу репозитория лично, а не в публичный issue.
