# Architecture: computed resources in O

**Status:** implemented on the feature PR branch; full MCP integration and dependency
on the generic Almasi Resource contract are verified separately.

## Meaning and responsibility

`o.resources.Computed(o.Resource)` inherits `Module` from the shared Almasi
`Resource`, without another direct base. Its stable
`id` is supplied by the caller, and its `value` is initially
`o.Undefined`. `read()` returns that value and never invokes the code that
computed it. `None` is a valid cached result.

O does not know a Web controller, MCP URI, user identity or argument list.
Web MCP decides which controller to invoke on a cache miss; O observes only
the ordinary Python code that executes inside its read scope.

## Observed computation

`o.services.Tracker.track_reads(list)` retains its existing behavior.
Passing a `o.resources.Computed` instead establishes an observation for
that existing resource and yields it:

~~~python
resource = o.resources.Computed()

with o.services.Tracker.track_reads(resource) as observed:
	observed.value = some_o_object.value
~~~

A result assigned inside this scope is **staged**, not published until
the block succeeds. O tracks the owner IDs read inside all nested operations;
on successful exit it updates the existing source subscriptions to those
IDs and publishes the staged value. An exception abandons the candidate
without changing the old dependency scope.

A temporary broad Sync registration is active while the block executes.
Unlike ordinary asynchronous subscribers, this internal commit observer sees
published owner IDs synchronously **after successful O commit and before**
the update enters the worker queue. The source's publication lock also guards
the final dependency replacement and value publication, so an intersecting
locally published change cannot pass between conflict checking and the handoff.

An intersecting change rejects the result with a retryable `RuntimeError`.
No partially computed value or replacement dependency scope is published.
Web translates that failure into the existing MCP `-32603` error.
The synchronous commit channel uses a Resource; no second dependency index,
change revision, or replayable function is introduced.

**Boundary:** an independent process may commit before its Transport message
reaches this process. Sync cannot detect that unseen remote commit and makes
no global ordering guarantee. Once the remote notification arrives, it
invalidates relevant cached values normally. Strict multiprocess read
linearizability remains unproven without a cross-process validation mechanism.

## Subscription source

`o.resources.Computed` inherits `Resource.subscribe(callback)` and owns its
listeners. Sync indexes each actively observed resource once. A resource
without a computed dependency scope starts with broad observation. Successful
recomputation replaces that resource's scope atomically under the publication
lock, without changing any listener.

On a matching invalidation Sync calls `resource.update(changed_ids)` once.
The resource invalidates its value to `o.Undefined` before delivering to all
live listeners. The last canceled listener releases the resource's index
entry. The synchronous commit channel used by Tracker is separate from
asynchronous dependency matching.

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
