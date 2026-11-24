# ==============================================================================
# NAMESPACE READ DIAGNOSTIC
# ==============================================================================
# Isolate dependent attribute reads and reversible namespace dictionary layout.
# ==============================================================================

import dis
import json
import os
import runpy
import statistics
import sys
import tempfile
import time
import timeit

from contextlib    import nullcontext
from types         import SimpleNamespace
from unittest.mock import patch

import almasi
from almasi import o


# Compare identical expressions in rotating order to avoid phase bias.
# ------------------------------------------------------------------------------
def measure(cases, scope):
	samples = {name: [] for name in cases}
	timers  = {
		name: timeit.Timer('for i in range(100000): ' + statement, timer=time.thread_time, globals=scope)
		for name, statement in cases.items()
	}
	names = tuple(cases)

	for round_index in range(3):
		offset = round_index * len(names) // 3
		order  = names[offset:] + names[:offset]

		for name in order:
			samples[name].append(timers[name].timeit(number=1) * 10)

	if 'chain' in timers:
		dis.dis(timers['chain'].inner, adaptive=True, show_caches=True, file=sys.stderr)

	return {name: statistics.median(values) for name, values in samples.items()}


# Reorder existing attributes without changing their values or identities.
# ------------------------------------------------------------------------------
def reorder(instance, name):
	original = instance.__dict__
	reordered = {name: original[name]}

	for key, value in original.items():
		reordered[key] = value

	object.__setattr__(instance, '__dict__', reordered)

	return original


# Compare the original chain, its components and the same logical namespace.
# ------------------------------------------------------------------------------
def sample(items):
	services = o.services
	cache    = services.Cache
	entities = cache.entities
	scope    = {
		'o'        : o,
		'services' : services,
		'cache'    : cache,
		'entities' : entities,
		'items'    : items,
		'get'      : services.Entity.get,
		'ids'      : items.__items__,
	}

	cases = {
		'list'        : 'items[i % 5]',
		'get'         : 'get(ids[i % 5])',
		'chain'       : 'o.services.Cache.entities',
		'first_two'   : 'o.services.Cache',
		'last_two'    : 'services.Cache.entities',
		'services'    : 'o.services',
		'cache'       : 'services.Cache',
		'entities'    : 'cache.entities',
		'split'       : 'directory = o.services; registry = directory.Cache; data = registry.entities',
		'split_left'  : 'directory = o.services; data = directory.Cache.entities',
		'split_right' : 'registry = o.services.Cache; data = registry.entities',
		'dict_chain'  : "o.__dict__['services'].__dict__['Cache'].__dict__['entities']",
		'plain_chain' : 'plain.services.Cache.entities',
	}
	scope['plain'] = SimpleNamespace(services=SimpleNamespace(Cache=SimpleNamespace(entities=entities)))

	for instance in (o, services, cache):
		print({
			'type'       : type(instance).__name__,
			'dict_bytes' : sys.getsizeof(instance.__dict__),
			'keys'       : list(instance.__dict__),
		}, file=sys.stderr)

	results = measure(cases, scope)
	cases   = {name: cases[name] for name in ('list', 'get', 'chain', 'first_two', 'last_two')}

	for owner, instance, attribute in (
		('library', o, 'services'),
		('directory', services, 'Cache'),
		('cache', cache, 'entities'),
	):
		original = reorder(instance, attribute)

		try:
			assert o.services.Cache.entities is entities

			for name, elapsed in measure(cases, scope).items():
				results[owner + '/' + name] = elapsed
		finally:
			object.__setattr__(instance, '__dict__', original)

	assert o.services.Cache.entities is entities

	for name, elapsed in measure(cases, scope).items():
		results['restored/' + name] = elapsed

	return results


# Compare the real ontology startup with and without native observers.
# ------------------------------------------------------------------------------
def run():
	root        = os.environ['EXPECTED_ROOT']
	mode        = sys.argv[1]
	filesystem  = almasi.services.Filesystem
	benchmark   = runpy.run_path(os.path.join(root, 'root/tests/_test_performance.py'))['TestPerformance']
	observation = patch.object(type(filesystem), '_watch', return_value=None) if mode == 'no_watch' else nullcontext()

	assert os.path.realpath(o.__path__) == os.path.join(root, 'root')
	assert os.path.realpath(almasi.__lib_file__) == os.path.join(os.environ['EXPECTED_CORE'], 'almasi.py')

	with tempfile.TemporaryDirectory(prefix='o_read_diagnostic_') as directory:
		type(o).__app__ = SimpleNamespace(__lib_path__=directory)

		with observation:
			o.start(tree_mode=False, multiprocess=False)
			o.Timer.enabled = False
			o.T.extend('APerfRun')
			o.Timer.reset()

			first   = benchmark.trigger_list_getitem(1000) * 1000
			items   = o.List([1, 2, 3, 4, 5])
			results = sample(items)
			results['original_first'] = first

			o.services.Memory.env.close()

	print(json.dumps(results))


if __name__ == '__main__':
	run()
