# Garbage Collection Invariants

## Purpose

Instances in O are durable only while reachable from `o.V`. Local Python references
do not retain persisted instances. Objects may remain on disk and addressable by ID
during a session, even when they are collectable at the next startup.

`o.services.Garbage` owns collectability and reference propagation. Classes and
containers report instance births and holding edges; they do not make GC decisions.

## Birth and collection

Every newly persisted instance is registered in `garbage/items/` in the same
LMDB transaction that creates its identity. The permanent `o.V` instance is
the only exception.

```text
new instance                 -> garbage[id] = proto
reachable from o.V           -> remove from garbage
last rooted holding edge lost -> garbage[id] = proto
next Garbage.initialize()    -> physically remove marked instance and its ID mapping
```

No full LMDB sweep is required. Rooted instances and their children are never
scheduled for collection.

## Holding edges

Persistent slots include object fields, list items, dictionary keys, and
dictionary values. A slot contributes to GC liveness **only if its owner is
already reachable from `o.V`**. An edge inside an unattached subtree has no
retention effect yet.

At the boundary of the retained graph:

- Linking the first retained owner increments the child's refcount from 0 to 1
  and recursively retains all its holding children.
- Linking an additional retained owner increments only the child's refcount.
- Unlinking one of multiple retained owners decrements only that refcount.
- Unlinking the last retained owner decrements from 1 to 0, marks the child as
  collectable, and recursively releases its holding children.

The root value is always retained without a counted incoming edge.
`on_instance_link(instance, owner)` and
`on_instance_unlink(instance, owner)` apply these rules. Their optional owner
defaults to `None` for explicit low-level calls without an enclosing object.

## Semantic dependants versus holding children

`__dependants__()` describes semantic child values, which other consumers
(e.g., representation) rely on. `__held_instances__()` enumerates **all**
GC edges and is used only for reference propagation.

For a normal instance and a list, both traversals have the same children.
For a dictionary, holding children also include the persisted key entities,
without adding them to the semantic `__dependants__()` output.

## Storage and startup

`refcounts` stores the number of incoming retained edges. Multiple direct
slots retain the same object independently; subtrees receive propagation only
when a node crosses the zero/nonzero boundary.

Garbage is collected on `Garbage.initialize()`, after the LMDB store opens.
Collection removes the instance record, its stored fields, its ID registry
mapping, and any tree-mode parent mapping.

This is deferred collection: it neither consults Python refcounts nor destroys
objects while callers might still be using their IDs during the current session.

## Regression evidence

`TestGarbage.test_unattached_tree_is_collected_after_restart` uses separate
Python processes over one isolated LMDB, exercising graph and tree modes.
It verifies that unattached and detached objects **and their descendants**
are removed, while objects reachable from `o.V` remain. Dictionary keys and
ID mappings are checked as well.
