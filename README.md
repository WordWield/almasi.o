# Almasi O — Persistent Objects for an AI-Native World

**AI can generate answers. But intelligent software needs a world that survives the answer.**
Almasi O makes Python types, entities, relationships and collections part of **one persistent, inspectable object system**.
**One model for code, state and schema—not three representations stitched together.**
[Watch the technical overview](https://youtu.be/M8GxATOocD0) · [Almasi Core](https://github.com/WordWield/almasi.a) · [Almasi Do: Agents](https://github.com/WordWield/almasi.do)

## Try it: the object is the database

Python 3.11+; install Almasi Core from GitHub:

```bash
python -m pip install git+https://github.com/WordWield/almasi.git
mkdir -p my-o-demo/root
cd my-o-demo
```

Save the following as `demo.py`, beside that empty `root/` directory:

```python
from almasi import o

demo = o.extend('demo')
o.start()

Note = o.T.extend(
	'Note',
	text = o.F(str),
)

o.V.note = Note(text='I exist beyond this process')
print(o.V.note.text)
```

Run `python demo.py`. Almasi acquires `o` on first import. Your application's persistent ontology lives in its own local storage. Read and mutate it using ordinary Python attributes—no `save()` and no separate ORM mapping.

```python
o.V.note.text = 'Still here'
print(o.V.note.id)
```

**The interesting part:** the entity has persistent identity. Nested persistent lists and dictionaries also persist their own mutations, rather than requiring you to serialize and replace their parent.

> The application is selected by `o.extend('demo')` in `demo.py`; its sibling `root/` directory is required by Almasi. Persistent storage starts explicitly with `o.start()`. A bare `from almasi import o` does **not** initialize a database.

## The missing primitive

Most applications describe the same concept over and over:

```text
Python object → validation model → DTO → ORM → database schema
```

Each translation creates synchronization work and opportunities for drift.

Almasi O starts from a different question: **why can't the Python entity itself be persistent?**

```text
                 Persistent Python entity
                  /      |      |      \
           identity   fields  schema  relationships
                  \      |      |      /
                     LMDB-backed O
```

This is not a SQL ORM with hidden mapping. The ontology owns persistent types, entities and the references between them. The object graph is the persistent graph.

### Capabilities available today

| Primitive | Why it matters |
| --- | --- |
| `o.T` and `o.F` | Define typed persistent entities and field semantics in Python |
| `o.V` | Address persistent application state from a stable root |
| `o.List` / `o.Dict` | Mutate nested collections without rewriting entire parent objects |
| Persistent identity | Resolve entities across references and application restarts |
| Runtime type extension | Extend the vocabulary of an application as its domain evolves |
| JSON, JSON Schema, prompt schema | Derive external representations from the same type system |
| Structural serialization | Carry definitions needed to reconstruct runtime-defined types |
| Transactions and LMDB | Group persistent changes and preserve storage integrity |
| Tracker and Changes | Observe supported public reads and notify affected owners after commits |

### Types carry meaning

```python
Person = o.T.extend(
	'Person',
	name = o.F(str, description='Name shown to other people'),
	age  = o.F(int, default=None),
)

person = Person(name='Ada')
o.V.person = person

print(Person.to_json_schema())
print(Person.to_prompt_schema())
```

Fields are defined once. Their types and descriptions can be reused by serialization, schema generation and AI-facing structures. Not every transformation has complete reactive tracking coverage; consult the [public API contract](docs/architecture.public_api.md) before relying on automatic invalidation.

### Deep state, shallow syntax

```python
o.V.tasks = o.List(['design', 'implement'])
o.V.tasks.append('verify')

o.V.settings = o.Dict({'theme': 'light'})
o.V.settings['theme'] = 'dark'
```

Persistent mutations follow the objects being changed. Referenced entities retain identity; graph ownership, not Python variable lifetime alone, determines persistent reachability.

### Identity is not a memory address

```python
person_id = o.V.person.id

# On a later run against the same ontology:
assert o.V.person.id == person_id
```

Persistent classes and entities use canonical ontology paths and stable storage IDs. An app can keep working with its domain entities across process lifetimes.

### Structure and meaning are complementary

Almasi O provides *structure* and persistent ownership. Field descriptions and metadata add *meaning*. External embeddings and vector indexes can be built on top, but **a vector database is not bundled into O**, and semantic retrieval is not being presented as a shipped feature.

This matters for AI agents: an agent's memory can be a graph of typed, inspectable entities rather than only a transcript or a set of anonymous vectors.

## Designed for systems that keep evolving

O is especially relevant to:

- AI-native applications requiring durable agent state and structured memory
- Multi-process systems sharing a persistent ontology
- Developer tools that introspect types and generate schemas
- Application backends seeking fewer DTO/ORM/schema translations
- Systems where new domain concepts are discovered at runtime

This is a **foundational technology**, not a claim that O already includes every higher-level AI feature. The intention is to make those features easier to build without creating separate representations of the same facts.

## Performance and operational semantics

Storage uses **LMDB**. Persistent reads can be fast; writes have transaction costs, and grouping related mutations matters. Results depend on workload, hardware, transaction shape and durability settings. See [performance notes](docs/performance.txt) and the repository's own benchmarks rather than treating a single headline number as a universal promise.

```python
with o.services.Memory.write():
	o.V.settings['theme'] = 'dark'
	o.V.tasks.append('release')
```

The `Memory` service is an infrastructure API for transaction management, **not** the recommended way for application services to read or mutate domain state. Application data should use the public O object API.

Forked ontologies can have separate persistence and runtime identity:

```python
other = o.fork('other')
other.start()
```

Startup and storage ownership are explicit. Read tracking, commit notifications, multi-process transport and tree mode have distinct contracts; see the architecture references below.

## Architecture and boundaries

- [Public object API and reactive guarantees](docs/architecture.public_api.md)
- [Read dependency tracking](docs/architecture.tracker.md)
- [Committed change delivery](docs/architecture.sync.md)
- [Multiprocess transport](docs/architecture.transport.md)
- [Forked runtime state](docs/architecture.fork.md)
- [Tree mode](docs/tree_mode.md)

For correctness, the difference between **observed reads** and **committed writes** matters. O reports changes through persistence boundaries; consumers such as the Web layer own subscription lifecycle and browser updates. We do not claim universal automatic reactivity for every reflective method.

## Place in the Almasi ecosystem

**[Almasi Core](https://github.com/WordWield/almasi.a)** supplies filesystem-native library composition; the installed Almasi loader acquires libraries lazily.

**Almasi O** supplies persistent entities, types, relationships, identity and schema.

**[Almasi Do](https://github.com/WordWield/almasi.do)** builds native agent execution and provider orchestration on the same foundations.

Together they suggest a different architecture for agentic software: **one persistent, understandable domain model that software and AI can both work with.**

## Status, contribution and license

Actively developed research software. Public APIs and performance characteristics may evolve. Python 3.11+; Apache-2.0.

[Source](https://github.com/WordWield/almasi.o) · [Issues](https://github.com/WordWield/almasi.o/issues) · [Technical overview](https://youtu.be/M8GxATOocD0)

**Created by Alexander Podgorny** — AI systems architect and researcher. [LinkedIn](https://www.linkedin.com/in/podgorny/).
