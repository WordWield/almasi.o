# ==============================================================================
# TEST GARBAGE
# ==============================================================================
# PURPOSE:
# Verify persisted graphs are collected by rooted reachability at startup.
#
# RESPONSIBILITY BOUNDARIES:
# Owns: Restart-based garbage collection integration tests.
# Delegates: Persistent state and traversal semantics to O.
# ==============================================================================

import os
import subprocess
import sys
import tempfile

from almasi import o


class TestGarbage(o.Tester):

	# ======================================================================
	# PRIVATE METHODS
	# ======================================================================

	# Verify rooted, detached, and orphaned objects in separate processes.
	# ----------------------------------------------------------------------
	@classmethod
	def _check_root_reachability_after_restart(cls, tree_mode):
		with tempfile.TemporaryDirectory(prefix='o_garbage_restart_') as directory:
			source = '''
import json
import os
import sys

from types import SimpleNamespace
from almasi import o

type(o).__app__ = SimpleNamespace(__lib_path__=sys.argv[1])
o.start(path=os.path.join(sys.argv[1], 'ontology'), tree_mode=sys.argv[3] == 'tree')

if sys.argv[2] == 'create':
	rogue_child = o.Dict({})
	rogue       = o.Dict({'child': rogue_child})
	kept_child    = o.Dict({})
	kept          = o.Dict({'child': kept_child})
	removed_child = o.Dict({})
	removed       = o.Dict({'child': removed_child})
	o.V.gc_retained = kept
	o.V.gc_removed  = removed
	del o.V.gc_removed

	rogue_key   = o.services.Entity.get(next(iter(rogue.__items__)))
	kept_key    = o.services.Entity.get(next(iter(kept.__items__)))
	removed_key = o.services.Entity.get(next(iter(removed.__items__)))

	objects = {
		'rogue'         : rogue,
		'rogue_child'   : rogue_child,
		'rogue_key'     : rogue_key,
		'kept'          : kept,
		'kept_child'    : kept_child,
		'kept_key'      : kept_key,
		'removed'       : removed,
		'removed_child' : removed_child,
		'removed_key'   : removed_key,
	}
	if sys.argv[3] == 'graph':
		cycle_a = o.List([])
		cycle_b = o.List([cycle_a])
		cycle_a.append(cycle_b)
		o.V.gc_cycle = cycle_a
		del o.V.gc_cycle

		nested_a = o.List([])
		nested_b = o.List([nested_a])
		nested_a.append(nested_b)
		o.V.gc_cycle_parent = o.List([nested_a])
		del o.V.gc_cycle_parent

		shared_a = o.List([])
		shared_b = o.List([shared_a])
		shared_a.append(shared_b)
		o.V.gc_shared_a = shared_a
		o.V.gc_shared_b = shared_b
		del o.V.gc_shared_a

		objects.update({
			'cycle_a'  : cycle_a,
			'cycle_b'  : cycle_b,
			'nested_a' : nested_a,
			'nested_b' : nested_b,
			'shared_a' : shared_a,
			'shared_b' : shared_b,
		})

	objects = {name: (item.id, item.__proto__) for name, item in objects.items()}
	assert not list(o.services.Memory.keys('garbage/')), 'Hot path wrote GC metadata'

	with open(os.path.join(sys.argv[1], 'objects.json'), 'w', encoding='utf-8') as file:
		json.dump(objects, file)
else:
	with open(os.path.join(sys.argv[1], 'objects.json'), encoding='utf-8') as file:
		objects = json.load(file)

	present = {}

	for name, (id, proto) in objects.items():
		present[name] = o.services.Memory.has(proto)
		assert o.services.Id.has(id) == present[name], f'ID mapping disagrees for {name}'
		print(f'{name}: id={id}, present={present[name]}', flush=True)

	assert not list(o.services.Memory.keys('garbage/')), 'Obsolete GC metadata survived restart'
	assert present['kept'], 'Object linked to o.V disappeared'
	assert present['kept_child'], 'Child linked through o.V disappeared'
	assert present['kept_key'], 'Dictionary key linked through o.V disappeared'
	assert not present['removed'], 'Object detached from o.V survived restart'
	assert not present['removed_child'], 'Child detached through o.V survived restart'
	assert not present['removed_key'], 'Dictionary key detached through o.V survived restart'
	assert not present['rogue'], 'ROGUE: unattached object survived restart'
	assert not present['rogue_child'], 'ROGUE: unattached child survived restart'
	assert not present['rogue_key'], 'ROGUE: unattached dictionary key survived restart'

	if sys.argv[3] == 'graph':
		for name in ('cycle_a', 'cycle_b', 'nested_a', 'nested_b'):
			assert not present[name], f'Detached cycle survived restart: {name}'

		for name in ('shared_a', 'shared_b'):
			assert present[name], f'Externally retained cycle was collected: {name}'


o.services.Memory.env.close()
'''
			environment = dict(os.environ)
			environment['PYTHONPATH'] = os.pathsep.join((
				os.path.dirname(o.__lib_file__),
				os.path.join(os.path.dirname(os.path.dirname(o.__lib_file__)), 'almasi'),
			))

			for mode in ('create', 'verify'):
				result = subprocess.run(
					[sys.executable, '-c', source, directory, mode, tree_mode],
					env            = environment,
					capture_output = True,
					text           = True,
					timeout        = 30,
				)
				assert result.returncode == 0, result.stdout + result.stderr


	# ======================================================================
	# PUBLIC METHODS
	# ======================================================================

	# Verify garbage invariants in both graph and tree modes.
	# ----------------------------------------------------------------------
	@classmethod
	def test_unattached_tree_is_collected_after_restart(cls):
		for tree_mode in ('graph', 'tree'):
			cls._check_root_reachability_after_restart(tree_mode)


if __name__ == '__main__':
	TestGarbage.run()
