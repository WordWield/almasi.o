# O Sync architecture

Sync observes committed owner-ID invalidations, not mutations in progress.
Local Memory commits and incoming Transport invalidations share one worker.
Remote delivery invalidates cached O entities before notifying resources.
Adjacent queued events are coalesced without crossing local/remote origin
boundaries. A None invalidation matches every observed resource, including
empty dependency scopes.

## Resource ownership

`o.ComputedResource` owns its listeners through `almasi.Resource`.
Sync observes that resource once while subscribed and indexes its dependency
IDs. It preserves the sparse/dense index, broad scope, immutable matching
snapshots and registration order. A successful tracked computation replaces
the scope under the existing publication lock. A matching change calls
`resource.update(matching_ids)` once; the computed resource clears its
cached value before dispatching to its listeners. Last cancellation removes
the resource and its index entries.

## Raw invalidations

`o.services.Sync.subscribe(ids=None, callback=None, local_only=False)`
remains available for consumers such as Transport. The callback-only form
means all IDs. IDs must be a set, frozenset or None; the scope is snapshotted.
Each call creates a notification-only Resource with that source scope and
returns its cancellable Subscription. The callback receives matching
frozenset IDs, or None for full invalidation. Local-only observers never
receive incoming remote changes. Replace a raw scope by canceling and
subscribing to the new scope; Subscription has no update method.

## Commit observations

`Sync.watch_commits(callback)` observes successful commits synchronously
before they enter the worker. Its callback receives (ids, local). Tracker
uses that channel to observe writes and to reject a read computation if
an observed owner changed before the result was committed. Publication
and computed dependency replacement use the same existing lock.

Ordinary callbacks run on the worker outside the publication lock, with
failure isolation. Cancellation does not wait for an already executing
callback. Remote cache invalidation is performed even without listeners.
Unobserved local changes are not queued for future subscribers.

## Verification

Native Sync, Transport, Tracker and ComputedResource tests cover transaction
boundaries, cache invalidation, origin filtering, dependency replacement,
independent listener lifetime, worker ordering and reentrancy.
