# Architecture: computed resources in O

**Status:** implemented on the feature PR branch; full MCP integration and dependency
on the generic Almasi Resource contract are verified separately.

## Meaning and responsibility

`o.ComputedResource` is the O specialization of `a.Resource`. Its stable
`id` is supplied by the caller, and its `value` is initially
`o.Undefined`. `read()` returns that value and never invokes the code that
computed it. `None` is a valid cached result.

O does not know a Web controller, MCP URI, user identity or argument list.
Web MCP decides which controller to invoke on a cache miss; O observes only
the ordinary Python code that executes inside its read scope.

## Observed computation

`o.services.Tracker.track_reads(list)` retains its existing behavior.
Passing a `ComputedResource` instead establishes an observation for
that existing resource and yields it:

~~~python
resource = o.ComputedResource('server-supplied-identity')

with o.services.Tracker.track_reads(resource) as observed:
	observed.value = some_o_object.value
~~~

A result assigned inside this scope is **staged**, not published until
the block succeeds. O tracks the owner IDs read inside all nested operations;
on successful exit it updates the existing source subscriptions to those
IDs and publishes the staged value. An exception abandons the candidate
without changing the old dependency scope.

A temporary broad O Sync observer is active while the block executes.
If an intersecting invalidation is delivered during the block, its result
is rejected with a `RuntimeError` explaining temporary unavailability.
That internal exception is converted to an existing MCP error by Web;
no protocol-specific error code is defined by O. Future O notifications
can invalidate the value again; no function body is stored for replay.

## Subscription source

`resource.subscribe(callback)` calls `o.services.Sync.subscribe(resource,
callback)`. Each call creates a distinct `a.Subscription` owned and indexed
by the existing `a.Subscribable` registry inside `o.Sync`.
A not-yet-computed resource initially uses broad observation, then
subscriptions are narrowed to its read owner IDs. On invalidation
`value` becomes `o.Undefined`, and existing observation remains active.
Successful recomputation refreshes the source's active handles. The
resource does not keep its own listener registry.

Cancel the listener's source subscription to release observation. Once the
last registered handle and any external cache references are released,
the resource is eligible for Python garbage collection.

## Verification

`root/tests/test_computed_resource.py` exercises stable result identity,
`o.Undefined`, valid `None`, refreshed dependency scope, invalidation
inside a tracked block, failure cleanup and collection via
`weakref` / `gc.collect()`. Existing tracker, sync, write-tracking and
multiprocess tests must remain green.

**Boundary:** this O-level read observation does not serialize HTTP/MCP
requests or supply a global persistent change log. Concurrent cache
reads and full transport/reconnection consistency are verified by the
Web integration layer, not assumed to arise from `read()` alone.
