# ==============================================================================
# ONTOLOGY LIBRARY
# ==============================================================================
# Publish the ontology namespace without starting persistent storage on import.
# ==============================================================================

import a


o = a.extend('o')

# Publish ontology-specific reload behavior for the library and its forks.
# ----------------------------------------------------------------------
type(o).Reloadable       = o.read('reloadable.py')
type(o).ReloadableModule = o.read('reloadable_module.py')

o.DATA_DIR    = None
o.MEMORY_SIZE = 1073741824
o.TREE_MODE   = False

# Each ontology starts explicitly; fork() only selects its isolated world.
# sync=True flushes LMDB commits; False favors throughput over durability.
o.start = o.services.Ontology.start
o.fork  = o.services.Ontology.fork
