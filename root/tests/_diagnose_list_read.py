# ==============================================================================
# ENTITY CACHE DIAGNOSTIC
# ==============================================================================
# Locate read overhead and test reversible dictionary layout changes.
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


# Measure expressions against the same cached objects and rotate case order.
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

	return {name: statistics.median(values) for name, values in samples.items()}


# Resolve cached entities while bypassing only namespace lookup.
# ------------------------------------------------------------------------------
def get_cached(entities, identifier, undefined):
	entity = entities.get(identifier, undefined)

	return entity


# Measure all stages of the ordinary cached read.
# ------------------------------------------------------------------------------
def sample(items):
	service  = o.services.Entity
	cache    = o.services.Cache
	entities = cache.entities
	ids      = items.__items__
	objects  = tuple(entities[identifier] for identifier in ids)
	scope    = {
		'o'          : o,
		'services'   : o.services,
		'cache'      : cache,
		'entities'   : entities,
		'ids'        : ids,
		'objects'    : objects,
		'items'      : items,
		'service'    : service,
		'get'        : service.get,
		'value'      : service.value,
		'lookup'     : entities.get,
		'undefined'  : o.Undefined,
		'get_cached' : get_cached,
	}

	assert all(service.get(identifier) is entity for identifier, entity in zip(ids, objects))
	assert all(entity.__value__ == index + 1 for index, entity in enumerate(objects))

	cases = {
		'list'         : 'items[i % 5]',
		'get'          : 'get(ids[i % 5])',
		'value'        : 'value(ids[i % 5])',
		'services'     : 'o.services',
		'cache'        : 'services.Cache',
		'entities'     : 'cache.entities',
		'chain'        : 'o.services.Cache.entities',
		'dict'         : 'entities.get(ids[i % 5], undefined)',
		'bound_dict'   : 'lookup(ids[i % 5], undefined)',
		'full_lookup'  : 'o.services.Cache.entities.get(ids[i % 5], undefined)',
		'cached_call'  : 'get_cached(entities, ids[i % 5], undefined)',
		'method'       : 'service.get(ids[i % 5])',
		'get_method'   : 'service.get',
		'flag'         : 'objects[i % 5].__class__.__is_atom__',
		'atom_value'   : 'objects[i % 5].__value__',
		'unwrap'       : 'entity = objects[i % 5]; result = entity.__value__ if entity.__class__.__is_atom__ else entity',
	}
	results = measure(cases, scope)

	print({
		'cache_size'  : len(entities),
		'cache_bytes' : sys.getsizeof(entities),
		'ids'         : ids,
		'entity_keys' : list(service.__dict__),
		'cache_keys'  : list(cache.__dict__),
		'types'       : [type(entity).__name__ for entity in objects],
	}, file=sys.stderr)

	# Rebuild the same registry in a different insertion order, then restore it.
	# ----------------------------------------------------------------------
	reordered = {key: entities[key] for key in ids}

	for key, entity in entities.items():
		reordered[key] = entity

	assert reordered == entities

	cases = {
		'list'  : 'items[i % 5]',
		'get'   : 'get(ids[i % 5])',
		'value' : 'value(ids[i % 5])',
	}

	try:
		cache.entities = reordered

		for name, elapsed in measure(cases, scope).items():
			results['reordered/' + name] = elapsed
	finally:
		cache.entities = entities

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
