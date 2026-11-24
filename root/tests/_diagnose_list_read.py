# ==============================================================================
# NAMESPACE ASSIGNMENT DIAGNOSTIC
# ==============================================================================
# Compare cached reads before and after ordinary namespace invalidation.
# ==============================================================================

import json
import os
import runpy
import statistics
import tempfile
import time
import timeit

from types import SimpleNamespace

import almasi
from almasi import o


# Measure each part of List indexing without changing the production methods.
# ------------------------------------------------------------------------------
def sample(items):
	service = o.services.Entity
	scope   = {
		'o'        : o,
		'items'    : items,
		'ids'      : items.__items__,
		'get'      : service.get,
		'value'    : service.value,
		'services' : o.services,
	}
	cases = {
		'list'         : 'items[i % 5]',
		'get'          : 'get(ids[i % 5])',
		'value'        : 'value(ids[i % 5])',
		'chain'        : 'o.services.Cache.entities',
		'last_two'     : 'services.Cache.entities',
		'entity_chain' : 'o.services.Entity',
		'full_value'   : 'o.services.Entity.value(items.__items__[i % 5])',
		'timer'        : "o.Timer.start('o.List.__getitem__'); o.Timer.stop('o.List.__getitem__')",
		'items'        : 'items.__items__[i % 5]',
	}
	samples = {name: [] for name in cases}
	timers  = {
		name: timeit.Timer('for i in range(100000): ' + statement, timer=time.thread_time, globals=scope)
		for name, statement in cases.items()
	}
	names = tuple(cases)

	for round_index in range(3):
		offset = round_index * len(names) // 3

		for name in names[offset:] + names[:offset]:
			samples[name].append(timers[name].timeit(number=1) * 10)

	return {name: statistics.median(values) for name, values in samples.items()}


# Measure the existing read path after normal ontology initialization.
# ------------------------------------------------------------------------------
def run():
	root = os.environ['EXPECTED_ROOT']

	assert os.path.realpath(o.__path__) == os.path.join(root, 'root')
	assert os.path.realpath(almasi.__lib_file__) == os.path.join(os.environ['EXPECTED_CORE'], 'almasi.py')

	benchmark = runpy.run_path(os.path.join(root, 'root/tests/_test_performance.py'))['TestPerformance']

	with tempfile.TemporaryDirectory(prefix='o_namespace_read_') as directory:
		type(o).__app__ = SimpleNamespace(__lib_path__=directory)
		o.start(tree_mode=False, multiprocess=False)
		o.Timer.enabled = False
		o.T.extend('APerfRun')
		o.Timer.reset()

		results = {'first_list': benchmark.trigger_list_getitem(1000) * 1000}
		items   = o.List([1, 2, 3, 4, 5])
		results.update(sample(items))
		cache = o.services.Cache
		o.services.invalidate('cache.py')
		assert o.services.Cache is cache

		for name, elapsed in sample(items).items():
			results['invalidated/' + name] = elapsed

		o.services.Memory.env.close()

	print(json.dumps(results))


if __name__ == '__main__':
	run()
