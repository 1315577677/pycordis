# PyCordis 内核设计 / Kernel Design

## 目标 / Goal

PyCordis 的目标是复刻 Cordis 的完整运行时模型，而非仅提供一个插件接口。
实现以官方 Cordis 的模块边界为参照，并在 Python 的对象模型与 `asyncio` 语义下提供等价行为。

PyCordis aims to reproduce Cordis's complete runtime model, rather than expose
only a plugin interface. The implementation follows the official module
boundaries while using idiomatic Python objects and `asyncio` semantics.

## 运行时关系 / Runtime relationships

```text
Context
 ├─ service scope ── Service implementations
 ├─ intercept scope ── per-service configuration overlays
 ├─ event bus ── emit / parallel / serial / bail / waterfall
 ├─ registry ── Plugin runtime records
 └─ Fiber ── plugin lifecycle and reversible effects
       └─ Plugin ── function / class / object implementation
```

`Context` 是服务发现和作用域的中心；`Fiber` 是一次插件运行的生命周期单元；
所有通过插件创建的服务、事件订阅和 effect 都由 Fiber 反向释放。

`Context` is the center of service discovery and scoping. A `Fiber` represents
one plugin lifecycle. Services, event subscriptions, and effects created by a
plugin are released in reverse order when its fiber unloads.

## 官方模块映射 / Official module mapping

| Cordis 模块 | PyCordis 对应设计 | 当前状态 |
| --- | --- | --- |
| `context.ts` | `Context`、`child()`、`extend()`、`isolate()`、`intercept()` | 已实现基础语义 |
| `registry.ts` | `PluginRegistry`、`Context.plugin()`、`Context.inject()` | 已实现基础语义 |
| `fiber.ts` | `Fiber`、依赖激活、同步/异步 effect、配置校验、restart/update、诊断 | 已实现第一版 |
| `reflect.ts` | `get()`、`set()`、`provide()`、`accessor()`、`mixin()`、调用方作用域绑定 | 已实现第一版 |
| `service.ts` | `Service` 基类、稳定服务名与 `ServiceCall` 调用记录 | 已实现第一版 |
| `events.ts` | `emit()`、`parallel()`、`serial()`、`bail()`、`waterfall()`、`once()`、目标过滤、全局监听 | 已实现第一版 |
| `logger.ts` | 结构化 Logger、按 Fiber 命名、等级过滤、有限记录缓冲区和可逆导出器 | 已实现第一版 |
| loader packages | 配置行、模块解析、热更新 | 待实现 |

“第一版”表示核心行为已被测试覆盖，但仍会持续对齐官方的错误诊断、过滤器、可观测性和边界语义。

“First version” means the core behavior is tested, while diagnostics, filters,
observability, and edge semantics will continue to converge with Cordis.

## 生命周期 / Lifecycle

1. `Context.plugin()` 创建 Fiber，并解析 `inject` 依赖。
2. 缺少依赖时 Fiber 为 `PENDING`。
3. 所有依赖可见时，Fiber 执行插件并进入 `ACTIVE`。
4. 插件返回的 cleanup、可迭代 cleanup 或异步可迭代 cleanup 都作为 effect 记录。
5. 服务消失、服务替换、`restart()` 或 `update()` 会按反向顺序释放 effect。
6. 依赖再次满足后，Fiber 用当前配置重新运行。
7. `dispose()` 则永久移除 Fiber 和它在 Registry 中的记录。

## 不变量 / Invariants

- 同一 Context 不能重复提供同名本地服务。
- 服务只能由提供它的 Context 通过 `set()` 替换。
- 所有插件产生的注册必须可释放，并以 LIFO 顺序清理。
- `False`、`None` 不是 bail 值；其他返回值都会中止 bail/serial 分发。
- `waterfall` 中不调用 `next_()` 即表示短路后续行为。
- `isolate(name)` 不会修改父 Context，且允许子 Context 为该服务提供独立实现。
- Service 方法总是从取得服务的调用方 Context 读取作用域和配置；异步调用跨 `await` 后仍保持该 Context。
- Logger 默认记录 `ERROR`、`WARN`、`INFO`，可由 `intercept("logger", ...)` 在调用方 Context 中覆盖名称和阈值；每条记录保留时间、序号、名称、等级、原始参数及 Fiber 名称。

## 下一阶段 / Next stage

下一步实现 Loader：配置行、模块解析和热更新。
随后才构建 Harness 层的模型、工具、Session、Sandbox、Storage、Loop、Schedule 和 UI 插件。

Next, implement the Loader: configuration rows, module resolution, and hot
updates. Only after that should Harness plugins for models, tools, sessions,
sandboxing, storage, loops, scheduling, and UI be added.
