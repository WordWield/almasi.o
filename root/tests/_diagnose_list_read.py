# ==============================================================================
# NAMESPACE ALIAS DIAGNOSTIC
# ==============================================================================
# Test whether resolving Filesystem through O changes the cached read path.
# ==============================================================================

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


# Resolve the observer through the resource namespace, as in the baseline.
# ------------------------------------------------------------------------------
def observe(resource):
	service = resource._namespace_lib.services.Filesystem
	assert service is almasi.services.Filesystem

	return service.observe


# Measure the same read path with identical objects in rotating case order.
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
		'list'     : 'items[i % 5]',
		'get'      : 'get(ids[i % 5])',
		'chain'    : 'o.services.Cache.entities',
		'last_two' : 'services.Cache.entities',
		'dict'     : 'entities.get(ids[i % 5])',
	}
	timers  = {
		name: timeit.Timer('for i in range(100000): ' + statement, timer=time.thread_time, globals=scope)
		for name, statement in cases.items()
	}
	names   = tuple(cases)
	samples = {name: [] for name in cases}

	for round_index in range(3):
		offset = round_index * len(names) // 3

		for name in names[offset:] + names[:offset]:
			samples[name].append(timers[name].timeit(number=1) * 10)

	assert o.services.Cache.entities is entities

	return {name: statistics.median(values) for name, values in samples.items()}


# Test the original dictionary, alias addition/removal and a plain copy.
# ------------------------------------------------------------------------------
def diagnose(items):
	services = o.services
	original = services.__dict__
	exists   = 'Filesystem' in original
	results  = sample(items)

	print({'keys': list(original), 'has_alias': exists, 'dict_bytes': sys.getsizeof(original)}, file=sys.stderr)

	if exists:
		del original['Filesystem']
	else:
		assert services.Filesystem is almasi.services.Filesystem

	for name, elapsed in sample(items).items():
		results['toggled/' + name] = elapsed

	if exists:
		original['Filesystem'] = almasi.services.Filesystem
	else:
		del original['Filesystem']

	for name, elapsed in sample(items).items():
		results['untoggled/' + name] = elapsed

	try:
		object.__setattr__(services, '__dict__', original.copy())

		for name, elapsed in sample(items).items():
			results['copied/' + name] = elapsed
	finally:
		object.__setattr__(services, '__dict__', original)

	for name, elapsed in sample(items).items():
		results['restored/' + name] = elapsed

	return results


# Compare normal startup and startup using the original namespace lookup.
# ------------------------------------------------------------------------------
def run():
	root        = os.environ['EXPECTED_ROOT']
	mode        = sys.argv[1]
	benchmark   = runpy.run_path(os.path.join(root, 'root/tests/_test_performance.py'))['TestPerformance']
	observation = nullcontext()

	if mode == 'namespace_alias' and hasattr(almasi.FilesystemResource, '_observe'):
		observation = patch.object(almasi.FilesystemResource, '_observe', property(observe))

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
			results = diagnose(items)
			results['original_first'] = first

			o.services.Memory.env.close()

	print(json.dumps(results))


if __name__ == '__main__':
	run()
