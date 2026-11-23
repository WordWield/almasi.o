# Future: Drastic Speedup — Persistence Begins at the Root

**Status:** Architectural proposal, not implemented. This document is independent of the current garbage-collection PR.

## Intent

**One clean boundary:** an O instance becomes persistent when it is attached to an already-persistent object. The first such object is `o.V`.

Before that transition, O instances are ordinary Python objects: fields and collections exist in Python memory, with no LMDB instance records, durable IDs, persistent Cache registrations, or Sync notifications. If unused, Python's GC reclaims them (including cycles). O's disk collector never needs to know they existed.

After the transition, O owns durable identity and storage. Promotion happens **once** and is irreversible during the instance's lifetime. A subsequently detached published object remains persistent until `o.collect()`; otherwise every mutation would again require a reachability calculation.

```python
Node = o.T.extend('Node', child=o.F(o.T, default=None))

a = Node()
b = Node()

a.child = b       # Python memory, no LMDB writes
b.child = a       # Python GC can reclaim this cycle if abandoned

o.V.node = a      # Atomically publish the entire graph
```

Assigning a new transient child to *any* already-persistent field, list, or dictionary similarly publishes its transient descendants. A persistent owner is not automatically demoted just because it loses its path from `o.V`.

## Necessary invariants

1. **One identity:** promotion preserves the same Python instances, aliases, shared descendants, and cycles. It must not clone objects or create a parallel object hierarchy.
2. **Zero storage writes for transient instances:** construction and local mutations do not create persistent IDs, instance records or persistent Sync events. Type/schema definitions are a separate concern.
3. **Atomic publication:** all new IDs, records, fields, list entries, and dictionary keys/values commit in one LMDB transaction or none do.
4. **Rollback remains transient:** after a failed publication, no object, Cache entry or ID claims uncommitted persistent identity; the original Python graph remains usable.
5. **Existing persistent children stay existing:** publishing a mixed graph never duplicates an already-persistent child or silently crosses an ontology/fork boundary.
6. **Graph and tree semantics stay distinct:** cycles and aliases work in graph mode; tree mode validates parent uniqueness and acyclicity before committing.
7. **Tracker and Sync follow durability:** transient reads/writes have no persistent owner IDs; publication and subsequent persistent changes notify committed owners only.
8. **Published object access stays compatible:** after publication, normal O fields, collections, ID lookup, serialization and cross-process visibility behave as before.
9. **One GC per ownership domain:** Python collects abandoned transient graphs; `o.collect()` traces and sweeps unreachable *published* graphs. No second persistent GC or per-mutation reference counting.
10. **Object identity survives publication:** no replacement instance is required for clients already holding the original Python reference.

## Publication: one discovery, one transaction

1. Traverse the transient graph using Python object identity and a visited set. Include object fields, list elements, dictionary **keys and values**, and references to already-persistent entities.
2. Validate types and ownership, including tree-mode constraints, without side effects.
3. Allocate durable IDs for all new instances **before** serializing any edges, so cycles and shared references are representable.
4. Persist new instances and edges atomically, while retaining enough uncommitted local state to roll back cleanly.
5. After a successful commit, activate persistent storage for the *same* Python instances, register their Id/Cache identities, and deliver post-commit Sync notifications.

This is a semantic contract, not permission to expose partially promoted objects. Transaction, cache and notification ordering must be established from the real O implementation.

## Necessary differences in the current implementation

- `T.__new__()` currently immediately invokes `__write__()` and `__read__()`, allocating a durable version/ID and creating records. A transient instance instead requires native Python identity until promotion.
- `T.__setattr__()` and `T.__getattr__()` currently use persistent Zones and numeric child IDs. Before promotion, values must be held as Python values/references. **Unify field semantics; isolate only the unavoidable storage representation difference.**
- `List` and `Dict` currently encode entries as persistent IDs. Their transient variants must operate on direct references without duplicating validation and mutation logic.
- `Id` and the persistent `Cache` must not retain transient objects. Otherwise abandoned transient graphs cannot be collected by Python.
- `obj.id` presently exists immediately after construction. Under this proposal, durable ID appears upon publication; an explicit, simple pre-publication identity contract is needed, including stable hash/equality if objects serve as keys.
- Published objects detached from `o.V` keep their storage semantics. A Python reference alone cannot keep such an instance persistent after an explicit `o.collect()`.
- A transient object must not be visible to another process until it is published. Any consumer relying on eager durable birth must be revised deliberately.

## Expected performance

| Workload | Current O | Proposed O |
| --- | --- | --- |
| Construct unrooted object | LMDB instance and ID writes | Python allocation |
| Mutate unrooted object | LMDB writes and Sync | Python mutation |
| Abandon unrooted graph | O collection on startup / explicit call | Python GC |
| Attach unrooted graph to persistent owner | Existing persisted objects, one edge write | One atomic graph publication |
| Mutate published object | LMDB-backed | LMDB-backed |
| Detach published object | Remains on disk until O GC | Same |
| Startup or explicit `o.collect()` | Rooted sweep over published records | Same |

These are hypotheses, **not measured results**. First publication may cost more and use additional transient memory. Performance should be reported in absolute units for construction, transient mutation, publication of shared/cyclic graphs, regular persistent mutation, startup/collection and peak memory.

## Minimal vertical-slice experiment

1. Construct and mutate an unrooted `Node`; verify no LMDB instance or ID keys are written.
2. Build a two-node cycle and drop Python references; verify Python GC collects it and persistent Cache retains nothing.
3. Publish a shared/cyclic graph via `o.V`; restart in another process and verify identity/topology.
4. Force a publication rollback; verify zero partial disk writes and usable original Python objects.
5. Exercise list/dict keys, already-published children, fork boundaries, tree mode and post-commit Sync.
6. Compare both models using the same benchmarks and include **absolute timings**.

## Architectural decision criterion

Adopt this only if the lifecycle boundary reduces **total** complexity, not just the number of database writes. If maintaining transient and persistent representations requires duplicated field/collection engines, reconsider where storage responsibility belongs.

**Everything necessary exists. Every invariant holds. Every essential difference is preserved. Nothing unnecessary remains.**
