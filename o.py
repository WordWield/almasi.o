# ==============================================================================
# ONTOLOGY LIBRARY
# ==============================================================================
# Publish the ontology namespace without starting persistent storage on import.
# ==============================================================================

import almasi
o = almasi.extend('o')

o.DATA_DIR    = None
o.MEMORY_SIZE = 1073741824
o.TREE_MODE   = False

# Publish startup, forks, and explicit collection through their owning service.
# sync=True flushes LMDB commits; False favors throughput over durability.
o.start   = o.services.Ontology.start
o.fork    = o.services.Ontology.fork
o.collect = o.services.Ontology.collect
