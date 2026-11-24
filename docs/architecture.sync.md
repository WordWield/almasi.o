# Architecture: Sync — owner-ID invalidation delivery

**Status:** Implemented in-process notification service with optional host-local
Transport forwarding; not a durable event log.

**Sources:** `root/services/sync.py`, `root/services/memory.py`,
`root/services/ontology.py`.
**Tests:** `root/tests/test_sync.py`, `root/tests/test_write_tracking.py`.
**Related:** [Tracker](architecture.tracker.md),
[application object API](architecture.public_api.md),
[ontology forks](architecture.fork.md),
[Transport](architecture.transport.md).

## Responsibility

Three separate owners provide reactive state:

1. **Tracker** records IDs of persistent objects *read* by a computation.
   It neither intercepts writes nor registers subscribers.
2. **Memory/Zone** persist changes and supply the affected owner IDs to
   **Sync**, independently of Tracker scopes.
3. **Computed** owns the cached computation, its dependencies and
   subscriptions. The consumer owns refetch policy and network delivery.

The necessary correctness condition within one ontology world is:

~~~text
result_before != result_after  =>  read_ids_before ∩ committed_write_ids != ∅
~~~

Tracking the public O object API and reporting corresponding write owners
are both necessary. Not every public transformation is fully observed;
see [architecture.public_api.md](architecture.public_api.md). Owner IDs
are identities, not property names, value diffs or snapshots.

## Startup, world identity, and naming

After the application has been selected via Almasi:

~~~python
from almasi import o

o.start()
sync = o.services.Sync
~~~

`Ontology.start()` initializes one Sync service/worker per world on first
startup; `Memory` binds to that world's Sync. An `o.fork('alice')` world
has a distinct Sync, classes, caches and LMDB. Numeric IDs must never be
mixed across worlds without qualifying world identity. Reopening an existing
world's Memory does not construct a new worker.

`o.start(sync=False)` is **LMDB disk-flush durability**. It does **not**
disable the `o.services.Sync` notification service. Likewise,
`tree_mode=None` restores the persisted topology mode (or defaults to
graph for a new world), independent of notifications. See
[architecture.fork.md](architecture.fork.md).

## Subscriber API

Sync indexes observed resources, not listener registrations. O implements
indexed owner-ID matching in `_dispatch()`; its worker and transport
remain O-owned. Computed inherits its listener registry from Resource.
Sync observes each computed resource once while it has listeners. It calls
`resource.update(matching_ids)` once per matching batch; the resource clears
its cached value before notifying its listeners. The final cancellation
removes the resource from the dependency index. Each ordered index entry is
reused by both sparse and dense dispatch snapshots. The same observation operation reconciles registration, cancellation and
recomputation. Unchanged IDs leave the index and snapshot untouched; a
changed scope updates only added and removed IDs.

| Call | Contract |
| --- | --- |
| `sync.subscribe(callback)` | Observe every owner change |
| `sync.subscribe(callback=callback)` | Same, explicit keyword |
| `sync.subscribe({id1, id2}, callback)` | Observe selected owner IDs |
| `sync.subscribe(callback, local_only=True)` | Transport-only local changes |
| `cancel()` (returned by Sync.subscribe) | Stop future delivery (idempotent, nonblocking) |
| `sync.publish_change(ids, local=False)` | Enqueue external invalidation |

Raw `sync.subscribe()` reuses one notification-only Resource per identical
immutable scope and origin filter. It returns a distinct cancellation callable for each listener. Delivery order is registration order within a
resource and first-observed order between resources, not a global listener
ordering across unrelated resources. A resource snapshots its listeners when
notified. The returned callable binds the resource and its opaque registration ID. Raw scope replacement is explicit: cancel the
old handle and subscribe with the new scope. Computed resources instead replace
their observed IDs automatically on successful recomputation.

The ID filter must be a `set`, `frozenset`, or `None`. All filters are
snapshotted; changing the input set does not affect a subscription. `None`
as a filter means all ordinary changes, while an empty set matches no
ordinary changes. `None` as an event denotes a full invalidation delivered
to all active subscribers, including empty-filter subscriptions. The value
`0` is an ordinary ID, not a special sentinel.

O's optional `local_only=True` remains a source-specific modifier. Its
subscribers see only changes originated by this process; Transport uses it
to forward invalidations without echoing incoming IPC. Remote changes are
always queued and invalidate the local cache **before** notifying ordinary
subscribers.

Ordinary callbacks receive `frozenset[int] | None` and run on the
`o-sync` worker thread. The internal `Sync.watch_commits(callback)` contract
is different: a notification-only Resource owns temporary listeners that
observe committed owner IDs synchronously on the publishing thread, before
worker delivery. Its callbacks receive one event tuple `(ids, local)`. The commit resource
exists only while observed; publication does not call an empty resource. `Sync.commit_resource(resource, identifiers)` uses the same source
lock to atomically validate observed changes, replace dependency scopes, and
publish a completed resource value. These calls are reserved for
`Tracker.track_reads(resource)`; ordinary clients should use
`subscribe()` and receive worker-delivered hints as before.

Cross-thread consumers hand off to their own event loop. Dispatch
uses the resource scope snapshot from the beginning of each batch. A scope
replacement takes effect on later batches. `cancel()` does not wait for a callback already
running; subsequent deliveries skip canceled registrations. Callbacks can
register or cancel subscriptions reentrantly. One callback's exception is
logged without suppressing delivery to the others.

Example of observing a computed resource:

~~~python
resource = o.resources.Computed()
subscription_id = resource.subscribe(on_change)

try:
	with o.services.Tracker.track_reads(resource) as computed:
		computed.value = o.V.counter['count']

	value = resource.read()
finally:
	resource.unsubscribe(subscription_id)
~~~

The tracked computation replaces the resource's dependency scope under
the publication lock. Recomputing does not replace any subscriber.

## Producer API (O infrastructure only)

Application code changes public O objects. `MemoryBatch` collects changed
owner IDs in a local list during each LMDB write transaction. Nested writes
share the same list, and failed transactions discard it.

After the outermost successful commit, `MemoryBatch` passes that complete
list to Sync in a single call, without copying or iterating it:

~~~python
sync.publish_change(ids, local=True)
~~~

A local commit without Sync subscribers needs no worker delivery and is
not queued. When a temporary computed-resource commit observer exists,
Sync confirms it synchronously after commit, under the source lock, even
though ordinary delivery stays queued. A subscribed local commit enqueues
the existing ID list without copying it.
A remote invalidation is always queued, even without subscribers, because it
must invalidate cached entities. The worker deduplicates IDs across adjacent
publications from the same origin and forwards local notifications to Transport.
Passing `None` requests full invalidation for listeners. Empty write batches,
missing-key deletions, and empty-prefix deletions do not notify. Read
transactions do not publish.

If publication fails after commit, the transaction remains committed and
`MemoryBatch` raises `RuntimeError('LMDB committed; Sync publication failed')`.
Sync is not a durable event log and cannot guarantee delivery if the process
crashes after committing.

## Worker and delivery timing

`Sync.initialize()` starts one worker. It blocks on `SimpleQueue.get()`
until a change arrives. Once an event arrives, a 100 µs window lets further
commits accumulate; the worker then drains the queue size captured at that
moment and delivers the resulting bounded burst. There is no idle timer,
wake flag, busy polling, or pre-commit speculative fallback.

- `local=True`: the worker normalizes IDs, informs matching local subscribers,
  and notifies Transport through its `local_only` subscription. It does not
  invalidate the writer's local object cache.
- `local=False`: the worker invalidates affected cached objects, then informs
  ordinary subscribers. It does not re-send the change through Transport.
- Adjacent events from the same origin in one worker cycle are coalesced into
  one invalidation. Their owner IDs are unioned; `None` dominates that
  origin's contiguous group. The worker preserves the order of local/remote
  groups, so remote changes are never echoed to Transport. Subscriber callbacks
  are invalidation hints, not per-commit events. Individual commit counts and
  intermediate values are not observable through Sync. Subscriber failures
  remain isolated.
- The worker is a daemon thread and runs for the application process lifetime.
  There is no `Sync.close()`, shutdown sentinel or queue flush on process exit.
  Events still queued at exit may be lost.
- If remote `Cache.invalidate(ids)` raises an exception, Sync logs the critical
  failure and terminates the process with `os._exit(1)` rather than continuing
  with potentially stale cached entities.

A Sync callback signals that locally committed or externally announced owner
state may have changed, not that the subscriber has applied the change.
Consumers re-read committed state through O APIs.

## Verification and non-goals

- `test_sync.py`: filtered/global/empty subscriptions, scope replacement,
  None/full invalidation, worker-thread callbacks, origin-preserving burst
  coalescing, no replay of unobserved changes, commit visibility, abort,
  concurrent producers, blocking queue delivery, reentrant and failing
  callbacks, and blocked listeners.
- `test_write_tracking.py`: actual field, collection, class and instance
  ownership; transaction nesting, rollback, Zone cache recovery and
  post-commit failure.
- `_test_performance_write_tracking.py --sync native` versus
  `--sync stub` compares native Sync with no-op producer callbacks, not
  distributed transport or browser latency.

The common subscription mechanism is specified in
[Almasi Resource](https://github.com/WordWield/almasi/blob/master/docs/architecture.resource.md).

Sync itself is **in-process, non-durable, non-replayable**. Optional Transport
provides host-local invalidation forwarding; Sync never references Transport
or owns its lifecycle. There is no revision ordering, authorization or UI
responsibility in Sync.
Consumers supply those capabilities where required. Web integrates it
through an optional injected pair `Tracker` / `Sync` without making O
depend on Web; see [Web MCP architecture](https://github.com/apodgorny/web/blob/master/docs/architecture.mcp.md).
