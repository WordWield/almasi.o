# ==============================================================================
# GARBAGE SERVICE
# ==============================================================================
# PURPOSE:
# Remove persisted instances that are unreachable from o.V at startup.
#
# RESPONSIBILITY BOUNDARIES:
# Owns: Rooted reachability traversal and persistent instance collection.
# Delegates: Identity enumeration to Id and reference enumeration to O instances.
# ==============================================================================

from almasi import o


class Garbage(o.Singleton):

	# ======================================================================
	# PUBLIC METHODS
	# ======================================================================

	# Collect only after ontology classes and o.V have been initialized.
	# ----------------------------------------------------------------------
	def initialize(self):
		self.collect()

	# Mark from o.V and sweep unvisited instances in one LMDB transaction.
	# ----------------------------------------------------------------------
	def collect(self):
		memory = o.services.Memory

		with memory.write():
			visited = set()
			pending = [o.services.Entity.ensure_value()]

			while pending:
				instance = pending.pop()

				if instance.id not in visited:
					visited.add(instance.id)
					pending.extend(instance.__get_outgoing_references__())

			obsolete = [
				(int(id), proto)
				for id, proto in o.services.Id.zone.items()
				if o.TMeta.is_instance_version(proto.rsplit('.', 1)[-1])
				and int(id) not in visited
			]

			for id, proto in obsolete:
				if o.TREE_MODE:
					memory.unset(f'tree/parents/{id}', id)

				class_id = o.services.Id.hash(proto.rsplit('.', 1)[0])
				memory.unset(proto, (id, class_id))
				memory.zone(f'{proto}.').clear()
				o.services.Id.unset(id)

			# Drop obsolete bookkeeping from previous GC implementations.
			# ----------------------------------------------------------------------
			memory.zone('garbage/refcounts/').clear()
			memory.zone('garbage/items/').clear()
