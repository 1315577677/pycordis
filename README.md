# PyCordis / Python Cordis

[English](#english) · [中文](#中文)

> **Status:** active work in progress. PyCordis aims to reproduce the complete
> Cordis framework in Python, step by step. It is not intended to be merely a
> simplified plugin library.

## English

PyCordis is a Python implementation of the Cordis framework that underpins
DeepSeek Harness. The compatibility target is the Cordis programming model:
contexts, services, fibers, reversible effects, the plugin registry, event
dispatch, isolation, interception, and the supporting loader/logging layers.

The project is deliberately being built from the kernel outward. Agent loops,
models, tools, storage, and user interfaces are Cordis plugins—not kernel
features—and will be implemented only after their hosting runtime is complete.

### Implementation plan

| Area | Status | Scope |
| --- | --- | --- |
| Context, service dependency, reversible registration | In progress | Context hierarchy and plugin activation lifecycle |
| Fiber and effect lifecycle | First version complete | config validation, async effects, reload, restart, update, diagnostics |
| Registry and plugin forms | Next in kernel | function, class, and object plugins; injected configuration |
| Reflection and services | First version complete | `get`, `set`, `provide`, accessor, mixin, caller-aware `Service` invocation |
| Events | First version complete | `emit`, `parallel`, `serial`, `bail`, `waterfall`, `once`, target filters, global listeners |
| Structured logger | First version complete | named loggers, four severity levels, bounded records, scoped exporters |
| Declarative loader | First step complete | in-memory rows, incremental reconciliation, enable/disable, `module:attribute` resolution |
| Loader configuration and hot reload | Next | configuration files, diagnostics, change detection, module reload |
| Harness capabilities | After framework | models, tools, sessions, sandbox, storage, loops, scheduling, UI |

### Current kernel contracts

- A `Context` owns services, plugin mounts, event listeners, and child scopes.
- A plugin declares required services through `inject` and stays pending until
  they are available.
- `provide()`, `on()`, and `effect()` are reversible. Registrations made inside
  a plugin are automatically removed when that plugin unloads.
- Removing a dependency deactivates affected plugins; restoring it activates
  them again.
- Child contexts can consume parent services while keeping local registrations.
- All five dispatch modes (`emit`, `parallel`, `serial`, `bail`, and
  `waterfall`) support target filters and global listeners.
- A service method runs in the calling `Context`, including after an `await`;
  root contexts expose immutable `service_calls` records for diagnostics.
- `ctx.logger(name)` creates a named structured logger. The default level is
  `INFO`; `ctx.intercept("logger", ...)` can override a Context's name and
  threshold, and exporters registered in a plugin are released with its Fiber.
- `Loader.reconcile()` converges declarative `LoaderEntry` rows with live
  Fibers; unchanged entries stay active, while changed, disabled, or removed
  entries are updated or released in lifecycle order.

### Loader quick start

```python
import asyncio

from pycordis import Context, Loader, LoaderEntry

loader = Loader(Context())
asyncio.run(loader.reconcile([
    LoaderEntry("worker", "myapp.plugins:worker", {"retries": 3}),
]))
```

## 中文

PyCordis 是对 DeepSeek Harness 底层 **Cordis** 框架的 Python 复刻项目。目标是
逐步实现 Cordis 的完整编程模型：Context、Service、Fiber、可逆 Effect、插件注册表、
事件分发、隔离（isolate）、拦截（intercept），以及后续的 Loader 和 Logger。

项目不是只做一个轻量插件框架。目前采用“由内向外”的方式开发：先完成框架内核，
再实现模型、工具、存储、会话、Agent Loop 和 UI 等上层插件能力。

### 实现路线

| 模块 | 状态 | 内容 |
| --- | --- | --- |
| Context、服务依赖、可逆注册 | 进行中 | Context 层级与插件激活生命周期 |
| Fiber 与 Effect 生命周期 | 第一版完成 | 配置校验、异步 effect、重载、重启、更新、诊断 |
| Registry 与插件形态 | 内核下一步 | 函数、类、对象插件与注入配置 |
| Reflect 与 Service | 第一版完成 | `get`、`set`、`provide`、accessor、mixin、调用方感知的 `Service` 调用 |
| Events | 第一版完成 | `emit`、`parallel`、`serial`、`bail`、`waterfall`、`once`、目标过滤与全局监听 |
| 结构化 Logger | 第一版完成 | 命名 Logger、四级日志、有限记录缓冲区、作用域导出器 |
| 声明式 Loader | 第一步完成 | 内存配置行、增量调和、启用/禁用、`module:attribute` 解析 |
| Loader 配置与热更新 | 下一步 | 配置文件、诊断、变更检测、模块重载 |
| Harness 能力插件 | 框架完成后 | 模型、工具、Session、Sandbox、Storage、Loop、Schedule、UI |

### 当前内核约定

- `Context` 管理服务、插件挂载、事件监听器和子作用域。
- 插件通过 `inject` 声明依赖；依赖尚未可用时，插件保持等待状态。
- `provide()`、`on()`、`effect()` 都可逆；插件内部创建的注册会随插件卸载而释放。
- 服务消失时，依赖它的插件会停用；服务恢复后会重新激活。
- 子 Context 可以读取父 Context 的服务，同时保有自己的本地注册。
- 五种事件分发模式（`emit`、`parallel`、`serial`、`bail`、`waterfall`）均支持目标过滤与全局监听。
- Service 方法会在调用方 `Context` 中执行，跨 `await` 后仍保持该作用域；根 Context 通过只读的 `service_calls` 提供诊断记录。
- `ctx.logger(name)` 会创建具名的结构化 Logger，默认等级为 `INFO`；可通过 `ctx.intercept("logger", ...)` 为指定 Context 覆盖名称和等级，插件内注册的导出器会随 Fiber 卸载。
- `Loader.reconcile()` 会将声明式的 `LoaderEntry` 配置行调和为运行中的 Fiber；不变的条目保持运行，变更、禁用或删除的条目会遵循生命周期顺序更新或释放。

### Loader 快速开始

```python
import asyncio

from pycordis import Context, Loader, LoaderEntry

loader = Loader(Context())
asyncio.run(loader.reconcile([
    LoaderEntry("worker", "myapp.plugins:worker", {"retries": 3}),
]))
```
