# ==============================================================================
# NAMESPACE ASSIGNMENT DIAGNOSTIC
# ==============================================================================
# Compare cached reads without touching the underlying namespace dictionaries.
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
		scope   = {
			'o'        : o,
			'items'    : items,
			'ids'      : items.__items__,
			'get'      : o.services.Entity.get,
			'value'    : o.services.Entity.value,
			'services' : o.services,
		}
		cases = {
			'list'     : 'items[i % 5]',
			'get'      : 'get(ids[i % 5])',
			'value'    : 'value(ids[i % 5])',
			'chain'    : 'o.services.Cache.entities',
			'last_two' : 'services.Cache.entities',
		}

		for name, statement in cases.items():
			timer   = timeit.Timer('for i in range(100000): ' + statement, timer=time.thread_time, globals=scope)
			samples = timer.repeat(repeat=5, number=1)
			results[name] = statistics.median(samples) * 10

		o.services.Memory.env.close()

	print(json.dumps(results))


if __name__ == '__main__':
	run()
