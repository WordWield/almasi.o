# Garbage Collection Invariants

## Purpose

Persisted O instances survive restart exactly when reachable through holding
edges from `o.V`. Local Python references do not retain persistent instances.
Cycles do not constitute independent retention.

Garbage owns collection and uses the existing identity registry. T and container
classes own their stored holding edges. They perform no garbage bookkeeping
when an edge changes or an instance is created.

## Startup

Ontology.start() opens Memory and Id, loads the ontology classes, and ensures
that `o.V` exists. Only then does Garbage.initialize() invoke collect().

The collector runs under one LMDB write transaction:

1. Traverse holding edges from `o.V`, marking visited instance IDs.
2. Read the existing `ids/` registry and identify persisted instance entries
   by their instance-version suffix.
3. Remove only unvisited instance records, their stored data, ID mappings, and
   tree-mode parent relationships.
4. Clear obsolete `garbage/refcounts/` and `garbage/items/` records from
   earlier collector implementations.

The transaction prevents concurrent writers from changing graph edges between
marking and sweeping. Persisted class definitions and their ID mappings are
not instances and therefore are not collected.

## Holding edges

`T.__get_outgoing_references__()` enumerates persisted field references and
list values. `Dict.__get_outgoing_references__()` also enumerates stored
dictionary **keys**. The traversal visits each instance once, regardless of
the number of incoming links or cycles.

These operations remain independent of garbage collection:

- Object creation and regular field changes.
- List and dictionary mutations.
- Graph-mode link and unlink.
- Tree-mode link validation and parent updates.

During an application session, disconnected objects remain accessible by ID.
They are physically removed at the next startup.

## Complexity

- Hot-path garbage bookkeeping: **none**.
- Restart traversal: O(V + E) for reachable instances and holding edges.
- Registry sweep: O(N) for all persisted instance IDs.
- Memory for the visited set and pending traversal: O(V + E) worst case.

No persistent reachability index, reference counter or garbage queue is needed.

## Verification

`TestGarbage.test_unattached_tree_is_collected_after_restart` exercises
creation, deletion, rooted and disconnected cycles, shared survivors, dictionary
keys, and class-ID preservation over two separate processes against a real
LMDB database in graph and tree modes.
