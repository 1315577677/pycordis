# PyCordis

PyCordis is a small Python plugin kernel inspired by the Cordis design used by
DeepSeek Harness. It deliberately implements the kernel only: contexts,
services, dependency-aware plugins, reversible registrations, and event
dispatch. Agent loops, model providers, configuration loaders, and scheduling
belong in plugins built on top of it.

## Kernel contracts

- A `Context` owns services, plugin mounts, event listeners, and child scopes.
- A `Plugin` declares the services it needs through `inject`.
- Plugins remain pending until all declared dependencies are available.
- `provide()`, `on()`, and `effect()` are reversible. Registrations made during
  `Plugin.apply()` are automatically disposed with that plugin.
- Removing a dependency deactivates affected plugins; restoring it activates
  them again.
- Child contexts can read parent services while maintaining their own local
  registrations.

## Event contracts

- `emit`: notify listeners and ignore return values.
- `bail`: stop at the first non-`None` return value.
- `waterfall`: around-middleware. A listener receives the event arguments plus
  `next_`; returning without calling `next_` short-circuits downstream work.

The first implementation is synchronous and dependency-free by design. Async
dispatch and configuration loading will be separate extensions once the
lifecycle contract is stable.
