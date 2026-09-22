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
| Fiber and effect lifecycle | Next in kernel | async effects, reload, restart, update, diagnostics |
| Registry and plugin forms | Next in kernel | function, class, and object plugins; injected configuration |
| Reflection and services | Next in kernel | `get`, `set`, `provide`, accessor, mixin, `Service` |
| Events | Next in kernel | `emit`, `parallel`, `serial`, `bail`, `waterfall`, `once`, filters |
| Loader, logger, configuration | After kernel | configuration rows, module loading, diagnostics |
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
- `emit`, `bail`, and `waterfall` are already implemented; the remaining
  Cordis dispatch modes are part of the kernel-completion work.

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
| Fiber 与 Effect 生命周期 | 内核下一步 | 异步 effect、重载、重启、更新、诊断 |
| Registry 与插件形态 | 内核下一步 | 函数、类、对象插件与注入配置 |
| Reflect 与 Service | 内核下一步 | `get`、`set`、`provide`、accessor、mixin、`Service` |
| Events | 内核下一步 | `emit`、`parallel`、`serial`、`bail`、`waterfall`、`once`、过滤器 |
| Loader、Logger、配置系统 | 内核后续 | 配置行、模块加载与诊断 |
| Harness 能力插件 | 框架完成后 | 模型、工具、Session、Sandbox、Storage、Loop、Schedule、UI |

### 当前内核约定

- `Context` 管理服务、插件挂载、事件监听器和子作用域。
- 插件通过 `inject` 声明依赖；依赖尚未可用时，插件保持等待状态。
- `provide()`、`on()`、`effect()` 都可逆；插件内部创建的注册会随插件卸载而释放。
- 服务消失时，依赖它的插件会停用；服务恢复后会重新激活。
- 子 Context 可以读取父 Context 的服务，同时保有自己的本地注册。
- 当前已实现 `emit`、`bail`、`waterfall`；其余 Cordis 事件模式将作为内核完成工作的一部分。
