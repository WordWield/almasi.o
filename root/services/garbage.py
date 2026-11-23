# ==============================================================================
# GARBAGE SERVICE
# ==============================================================================
# PURPOSE:
# Collect persisted instances no longer reachable from o.V.
#
# RESPONSIBILITY BOUNDARIES:
# Owns: Reference counts, cycle detection and deferred garbage collection.
# Delegates: Reference enumeration to O instances and storage to Memory.
# ==============================================================================

from almasi import o


class Garbage(o.Singleton):

	# ======================================================================
	# PRIVATE METHODS
	# ======================================================================

	# Consider o.V reachable and allow explicit calls without an owner.
	# ----------------------------------------------------------------------
	def _is_reachable(self, owner):
		return (
			owner is None
			or isinstance(owner, o.T.V)
			or self.refcounts.get(owner.id, 0) > 0
		)

	# Retain an instance and its descendants only when it first becomes live.
	# ----------------------------------------------------------------------
	def _on_instance_link(self, instance):
		old_count = self.refcounts.get(instance.id, 0)
		count     = old_count + 1

		self.refcounts.set(instance.id, count, instance.id)
		self.garbage.unset(instance.id, instance.id)

		if old_count == 0:
			for child in instance.__get_outgoing_references__():
				self._on_instance_link(child)

	# Release descendants and record positive counts for cycle detection.
	# ----------------------------------------------------------------------
	def _on_instance_unlink(self, instance, candidates):
		old_count = self.refcounts.get(instance.id, 0)
		count     = max(old_count - 1, 0)

		if count == 0:
			self.refcounts.unset(instance.id, instance.id)
			self.garbage.set(instance.id, instance.__proto__, instance.id)

			if old_count == 1:
				for child in instance.__get_outgoing_references__():
					self._on_instance_unlink(child, candidates)
		else:
			self.refcounts.set(instance.id, count, instance.id)
			candidates.append(instance)

	# Collect cycles with no external holding path.
	# ----------------------------------------------------------------------
	def _collect_cycles(self, instance, owner, removed):
		nodes      = {}
		references = {}
		pending    = [instance]
		skipped    = False

		# The caller has not yet removed the edge from persistent storage.
		# ----------------------------------------------------------------------
		while pending:
			node = pending.pop()

			if node.id not in nodes:
				nodes[node.id]      = node
				references[node.id] = []

				for child in node.__get_outgoing_references__():
					removed_edge = (
						owner is not None
						and node.id == owner.id
						and child.id == removed.id
						and not skipped
					)

					if removed_edge:
						skipped = True
					elif self.refcounts.get(child.id, 0) > 0:
						references[node.id].append(child.id)

						if child.id not in nodes:
							pending.append(child)

		# Internal edges alone cannot keep a graph alive.
		# ----------------------------------------------------------------------
		internal = {id: 0 for id in nodes}

		for children in references.values():
			for child_id in children:
				internal[child_id] += 1

		pending = [
			id for id, node in nodes.items()
			if isinstance(node, o.T.V) or self.refcounts.get(id, 0) > internal[id]
		]
		reachable = set()

		while pending:
			id = pending.pop()

			if id not in reachable:
				reachable.add(id)
				pending.extend(references[id])

		# Release only the contributions from dead owners to surviving nodes.
		# ----------------------------------------------------------------------
		for id, node in nodes.items():
			if id not in reachable:
				self.refcounts.unset(id, id)
				self.garbage.set(id, node.__proto__, id)

				for child_id in references[id]:
					if child_id in reachable:
						count = self.refcounts.get(child_id, 0)
						self.refcounts.set(child_id, count - 1, child_id)


	# ======================================================================
	# PUBLIC METHODS
	# ======================================================================

	# Resume the persistent garbage queues and collect previously marked data.
	# ----------------------------------------------------------------------
	def initialize(self):
		memory = o.services.Memory

		self.refcounts = memory.zone('garbage/refcounts/')
		self.garbage   = memory.zone('garbage/items/')

		self.collect()

	# Mark new instances other than o.V for deletion until reachable.
	# ----------------------------------------------------------------------
	def on_instance_create(self, cls, id, proto):
		if cls is not o.T.V:
			self.garbage.set(id, proto, id)

	# Count new edges only when the containing object is reachable.
	# ----------------------------------------------------------------------
	def on_instance_link(self, instance, owner=None):
		if self._is_reachable(owner):
			with o.services.Memory.write():
				self._on_instance_link(instance)

	# Remove one edge, probing for cycles only in graph mode.
	# ----------------------------------------------------------------------
	def on_instance_unlink(self, instance, owner=None):
		if self._is_reachable(owner):
			with o.services.Memory.write():
				candidates = []
				self._on_instance_unlink(instance, candidates)

				if not o.TREE_MODE:
					for candidate in candidates:
						if self.refcounts.get(candidate.id, 0) > 0:
							self._collect_cycles(candidate, owner, instance)

	# Delete marked instances and their ID mappings at the next startup.
	# ----------------------------------------------------------------------
	def collect(self):
		memory = o.services.Memory

		with memory.write():
			for id, proto in self.garbage.items():
				instance_id = int(id)
				class_id    = o.services.Id.hash(proto.rsplit('.', 1)[0])

				if o.TREE_MODE:
					memory.unset(f'tree/parents/{instance_id}', instance_id)

				memory.unset(proto, (instance_id, class_id))
				memory.zone(f'{proto}.').clear()
				o.services.Id.unset(instance_id)

			self.clear()

	# Remove garbage queue entries after their persistent records are deleted.
	# ----------------------------------------------------------------------
	def clear(self):
		self.garbage.clear(int(id) for id in self.garbage.keys())
