# ==============================================================================
# GARBAGE SERVICE
# ==============================================================================
# Track instances reachable from o.V and reclaim unretained data.
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

	# Release descendants when the last counted reference disappears.
	# ----------------------------------------------------------------------
	def _on_instance_unlink(self, instance, candidates=None):
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

			if candidates is not None:
				candidates[instance.id] = instance

	# Collect cyclic components without scanning unrelated LMDB instances.
	# ----------------------------------------------------------------------
	def _collect_disconnected_subgraph(self, candidate, owner, removed):
		instances = {}
		edges     = {}
		pending   = [candidate]

		# Traverse the active outgoing graph, excluding the pending removed edge.
		# ----------------------------------------------------------------------
		while pending:
			instance = pending.pop()
			is_active = isinstance(instance, o.T.V) or self.refcounts.get(instance.id, 0) > 0

			if instance.id not in instances and is_active:
				instances[instance.id] = instance
				references = []
				skipped    = False

				for child in instance.__get_outgoing_references__():
					skip_edge = (
						owner is not None
						and instance.id == owner.id
						and child.id == removed.id
						and not skipped
					)

					if skip_edge:
						skipped = True

					if not skip_edge:
						references.append(child)

				edges[instance.id] = references
				pending.extend(references)

		# External incoming references identify the remaining entry points.
		# ----------------------------------------------------------------------
		internal = dict.fromkeys(instances, 0)

		for references in edges.values():
			for child in references:
				if child.id in internal:
					internal[child.id] += 1

		pending = [
			instance for id, instance in instances.items()
			if isinstance(instance, o.T.V) or self.refcounts.get(id, 0) > internal[id]
		]
		reachable = set()

		while pending:
			instance = pending.pop()

			if instance.id not in reachable:
				reachable.add(instance.id)
				pending.extend(child for child in edges[instance.id] if child.id in instances)

		# Disconnected cycles lose their mutual counts; live nodes lose dead edges.
		# ----------------------------------------------------------------------
		unreachable = set(instances) - reachable

		for id in unreachable:
			self.refcounts.unset(id, id)
			self.garbage.set(id, instances[id].__proto__, id)

		for id in unreachable:
			for child in edges[id]:
				if child.id in reachable:
					count = self.refcounts.get(child.id, 0) - 1

					if count == 0:
						self.refcounts.unset(child.id, child.id)

					if count > 0:
						self.refcounts.set(child.id, count, child.id)

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

	# Remove counted edges and investigate possible disconnected graph cycles.
	# ----------------------------------------------------------------------
	def on_instance_unlink(self, instance, owner=None):
		if self._is_reachable(owner):
			with o.services.Memory.write():
				candidates = {} if not o.TREE_MODE else None
				self._on_instance_unlink(instance, candidates)

				if candidates is not None:
					for candidate in candidates.values():
						if self.refcounts.get(candidate.id, 0) > 0:
							self._collect_disconnected_subgraph(candidate, owner, instance)

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
